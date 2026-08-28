#!/usr/bin/env python3
"""
Shiro Traffic Collector - per-user bandwidth accounting for:
  - Xray Core (vless / vmess / trojan / ss) -> via statsquery API
  - WireGuard (wg0)                        -> via wg show wg0 transfer
  - SSH / OpenSSH / Dropbear               -> via safe iptables accounting chain (SHIRO_SSH)
"""
import json
import os
import re
import pwd
import sqlite3
import subprocess
import time

DB_PATH = "/var/lib/shirobot.db"
XRAY_BIN = "/usr/local/bin/xray"
XRAY_API = "127.0.0.1:10085"
STATE_DIR = "/var/lib/shiro_traffic"
INTERVAL = 10

os.makedirs(STATE_DIR, exist_ok=True)

def db():
    return sqlite3.connect(DB_PATH, timeout=10)

def init_ssh_iptables_chain():
    """Ensure SHIRO_SSH accounting chain exists and is attached to OUTPUT & INPUT (RETURN only, no drop)."""
    try:
        subprocess.run(["iptables", "-N", "SHIRO_SSH"], capture_output=True)
        out_chk = subprocess.run(["iptables", "-C", "OUTPUT", "-j", "SHIRO_SSH"], capture_output=True)
        if out_chk.returncode != 0:
            subprocess.run(["iptables", "-I", "OUTPUT", "1", "-j", "SHIRO_SSH"], capture_output=True)
    except Exception:
        pass

def sync_ssh_iptables_rules():
    """Sync iptables rules for all active SSH accounts in DB."""
    try:
        conn = db()
        c = conn.cursor()
        c.execute("SELECT username FROM accounts WHERE protocol='ssh'")
        ssh_users = [row[0] for row in c.fetchall()]
        conn.close()

        # Get existing rules in SHIRO_SSH
        out = subprocess.run(["iptables", "-L", "SHIRO_SSH", "-n"], capture_output=True, text=True).stdout
        existing_uids = set(re.findall(r"OWNER UID match (\d+)", out))

        for u in ssh_users:
            try:
                p_uid = str(pwd.getpwnam(u).pw_uid)
                if p_uid not in existing_uids:
                    subprocess.run(["iptables", "-A", "SHIRO_SSH", "-m", "owner", "--uid-owner", p_uid, "-j", "RETURN"], capture_output=True)
            except KeyError:
                continue
    except Exception:
        pass

# ---------- SSH TRAFFIC VIA IPTABLES ----------
def collect_ssh():
    totals = {}
    try:
        out = subprocess.run(["iptables", "-L", "SHIRO_SSH", "-v", "-n", "-x"], capture_output=True, text=True).stdout
        uid_bytes = {}
        for line in out.strip().splitlines():
            m = re.search(r"^\s*\d+\s+(\d+)\s+RETURN.*OWNER UID match (\d+)", line)
            if m:
                b, uid = int(m.group(1)), int(m.group(2))
                uid_bytes[uid] = uid_bytes.get(uid, 0) + b

        # Map UID back to DB username
        conn = db()
        c = conn.cursor()
        c.execute("SELECT username FROM accounts WHERE protocol='ssh'")
        for (u,) in c.fetchall():
            try:
                p_uid = pwd.getpwnam(u).pw_uid
                if p_uid in uid_bytes:
                    totals[u] = uid_bytes[p_uid]
            except KeyError:
                continue
        conn.close()
    except Exception:
        pass
    return totals

# ---------- XRAY (vless / vmess / trojan / ss) ----------
def collect_xray():
    try:
        out = subprocess.run(
            [XRAY_BIN, "api", "statsquery", f"--server={XRAY_API}"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except Exception:
        return {}

    totals = {}
    try:
        data = json.loads(out or "{}")
    except Exception:
        return {}

    for stat in data.get("stat", []) or []:
        name = stat.get("name", "")
        try:
            value = int(stat.get("value", 0) or 0)
        except (TypeError, ValueError):
            continue
        m = re.match(r"user>>>([^>]+)>>>traffic>>>(uplink|downlink)$", name)
        if m:
            uname = m.group(1).split("@")[0]
            totals[uname] = totals.get(uname, 0) + value
    return totals

# ---------- WIREGUARD ----------
def collect_wireguard():
    try:
        out = subprocess.run(
            ["wg", "show", "wg0", "transfer"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except Exception:
        return {}

    pk_map = {}
    try:
        conn = db()
        c = conn.cursor()
        c.execute(
            "SELECT username, uuid_or_pass, uuid, config_link "
            "FROM accounts WHERE protocol='wg'"
        )
        for uname, uop, uuid_col, conf in c.fetchall():
            for src in (uop, uuid_col, conf):
                if not src:
                    continue
                m = re.search(r"([A-Za-z0-9+/]{42,43}=)", str(src))
                if m:
                    pk_map[m.group(1)] = uname
                    break
        conn.close()
    except Exception:
        return {}

    totals = {}
    for line in (out or "").strip().split("\n"):
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        pubkey, rx, tx = parts[0], parts[-2], parts[-1]
        uname = pk_map.get(pubkey)
        if not uname:
            continue
        try:
            totals[uname] = totals.get(uname, 0) + int(rx) + int(tx)
        except ValueError:
            continue
    return totals

# ---------- SNAPSHOT / DELTA ----------
def load_snapshot(source):
    path = os.path.join(STATE_DIR, f"{source}.snap")
    snap = {}
    if os.path.exists(path):
        try:
            with open(path) as f:
                for line in f:
                    if ":" in line:
                        k, v = line.rsplit(":", 1)
                        try:
                            snap[k] = int(v.strip())
                        except ValueError:
                            pass
        except OSError:
            pass
    return snap

def save_snapshot(source, data):
    path = os.path.join(STATE_DIR, f"{source}.snap")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        for k, v in data.items():
            f.write(f"{k}:{v}\n")
    os.replace(tmp, path)

def apply_deltas(current, source):
    if not current:
        return
    prev = load_snapshot(source)
    conn = db()
    c = conn.cursor()
    for uname, cur_val in current.items():
        prev_val = prev.get(uname, 0)
        delta = cur_val - prev_val if cur_val >= prev_val else cur_val
        if delta > 0:
            c.execute(
                "UPDATE accounts "
                "SET used_bytes = COALESCE(used_bytes,0) + ?, "
                "    used_gb = (COALESCE(used_bytes,0) + ?) / 1073741824.0 "
                "WHERE username=?",
                (delta, delta, uname),
            )
    conn.commit()
    conn.close()
    save_snapshot(source, current)

def main():
    print("Shiro Universal Traffic Collector started (SSH + Xray + WireGuard).")
    init_ssh_iptables_chain()
    while True:
        try:
            sync_ssh_iptables_rules()
            apply_deltas(collect_ssh(), "ssh")
            apply_deltas(collect_xray(), "xray")
            apply_deltas(collect_wireguard(), "wireguard")
        except Exception as e:
            print(f"Collector error: {e}")
        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()
