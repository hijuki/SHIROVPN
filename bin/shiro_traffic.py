#!/usr/bin/env python3
"""
Shiro Traffic Collector - Real-time bandwidth accounting.
Collects per-user traffic from Xray API, WireGuard, and SSH (iptables),
then writes cumulative used_bytes into /var/lib/shirobot.db.
"""
import os
import re
import sqlite3
import subprocess
import time

DB_PATH = "/var/lib/shirobot.db"
XRAY_BIN = "/usr/local/bin/xray"
XRAY_API = "127.0.0.1:10085"
STATE_DIR = "/var/lib/shiro_traffic"
os.makedirs(STATE_DIR, exist_ok=True)

def db():
    return sqlite3.connect(DB_PATH)

# ---------- XRAY (vless/vmess/trojan) ----------
def collect_xray():
    """Query Xray stats API, return {email: total_bytes_delta_snapshot}."""
    try:
        out = subprocess.run(
            [XRAY_BIN, "api", "statsquery", f"--server={XRAY_API}", "-reset=false"],
            capture_output=True, text=True, timeout=10
        ).stdout
    except Exception as e:
        return {}
    # Format lines: "user>>>EMAIL>>>traffic>>>uplink" : value
    totals = {}
    # xray returns JSON; parse name/value pairs
    import json
    try:
        data = json.loads(out)
        for stat in data.get("stat", []):
            name = stat.get("name", "")
            value = int(stat.get("value", 0) or 0)
            m = re.match(r"user>>>([^>]+)>>>traffic>>>(uplink|downlink)", name)
            if m:
                email = m.group(1)
                # email format: username or username@shiro.id
                uname = email.split("@")[0]
                totals[uname] = totals.get(uname, 0) + value
    except: 
        pass
    return totals

# ---------- WIREGUARD ----------
def collect_wireguard():
    """Map wg peer pubkey->username via DB uuid_or_pass, return {username: bytes}."""
    totals = {}
    try:
        out = subprocess.run(["wg", "show", "wg0", "transfer"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return {}
    # Build pubkey -> username map from DB
    conn = db(); c = conn.cursor()
    c.execute("SELECT username, uuid_or_pass, uuid, config_link FROM accounts WHERE protocol='wg'")
    pk_map = {}
    for uname, uop, uuid_col, conf in c.fetchall():
        # WG public key is usually stored in config or uuid field; try to extract PublicKey
        for src in (uop, uuid_col, conf):
            if src:
                m = re.search(r"([A-Za-z0-9+/]{42,43}=)", str(src))
                if m:
                    pk_map[m.group(1)] = uname
                    break
    conn.close()
    for line in out.strip().split("\n"):
        parts = line.split("\t")
        if len(parts) >= 3:
            pubkey, rx, tx = parts[0], parts[-2], parts[-1]
            try:
                total = int(rx) + int(tx)
            except:
                continue
            uname = pk_map.get(pubkey)
            if uname:
                totals[uname] = totals.get(uname, 0) + total
    return totals

# ---------- SSH (iptables per-uid accounting) ----------
def ensure_ssh_iptables():
    """Ensure OUTPUT/INPUT owner-match rules exist for each SSH user (per-uid byte counters)."""
    conn = db(); c = conn.cursor()
    c.execute("SELECT username FROM accounts WHERE protocol='ssh'")
    ssh_users = [r[0] for r in c.fetchall()]
    conn.close()
    for uname in ssh_users:
        try:
            uid = subprocess.run(["id", "-u", uname], capture_output=True, text=True).stdout.strip()
            if not uid.isdigit():
                continue
            chain = f"SHIRO_{uname[:20]}"
            # Create chain if not exists
            subprocess.run(["iptables", "-N", chain], capture_output=True)
            # OUTPUT: traffic owned by this uid
            check = subprocess.run(["iptables", "-C", "OUTPUT", "-m", "owner", "--uid-owner", uid, "-j", chain], capture_output=True)
            if check.returncode != 0:
                subprocess.run(["iptables", "-I", "OUTPUT", "-m", "owner", "--uid-owner", uid, "-j", chain], capture_output=True)
        except Exception:
            pass

def collect_ssh():
    """Read iptables byte counters per SSH user chain."""
    totals = {}
    conn = db(); c = conn.cursor()
    c.execute("SELECT username FROM accounts WHERE protocol='ssh'")
    ssh_users = [r[0] for r in c.fetchall()]
    conn.close()
    for uname in ssh_users:
        try:
            uid = subprocess.run(["id", "-u", uname], capture_output=True, text=True).stdout.strip()
            if not uid.isdigit():
                continue
            out = subprocess.run(["iptables", "-L", "OUTPUT", "-n", "-v", "-x"], capture_output=True, text=True).stdout
            for line in out.split("\n"):
                if f"owner UID match {uid}" in line:
                    parts = line.split()
                    if len(parts) >= 2 and parts[1].isdigit():
                        totals[uname] = totals.get(uname, 0) + int(parts[1])
        except Exception:
            pass
    return totals

# ---------- SNAPSHOT & CUMULATIVE LOGIC ----------
def load_snapshot(name):
    path = os.path.join(STATE_DIR, f"{name}.snap")
    snap = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                if ":" in line:
                    k, v = line.rsplit(":", 1)
                    try: snap[k] = int(v.strip())
                    except: pass
    return snap

def save_snapshot(name, data):
    path = os.path.join(STATE_DIR, f"{name}.snap")
    with open(path, "w") as f:
        for k, v in data.items():
            f.write(f"{k}:{v}\n")

def apply_deltas(current, source):
    """current is absolute counters; compute delta vs last snapshot; add to DB used_bytes."""
    prev = load_snapshot(source)
    conn = db(); c = conn.cursor()
    for uname, cur_val in current.items():
        prev_val = prev.get(uname, 0)
        # If counter reset (cur < prev), treat cur as delta
        delta = cur_val - prev_val if cur_val >= prev_val else cur_val
        if delta > 0:
            c.execute("UPDATE accounts SET used_bytes = COALESCE(used_bytes,0) + ?, used_gb = (COALESCE(used_bytes,0) + ?) / 1073741824.0 WHERE username=?", (delta, delta, uname))
    conn.commit(); conn.close()
    save_snapshot(source, current)

def main():
    print("Shiro Traffic Collector started.")
    while True:
        try:
            ensure_ssh_iptables()
            apply_deltas(collect_xray(), "xray")
            apply_deltas(collect_wireguard(), "wireguard")
            apply_deltas(collect_ssh(), "ssh")
        except Exception as e:
            print(f"Collector error: {e}")
        time.sleep(20)

if __name__ == "__main__":
    main()
