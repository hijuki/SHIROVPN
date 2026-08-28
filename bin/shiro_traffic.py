#!/usr/bin/env python3
"""
Shiro Traffic Collector - per-user bandwidth accounting.

Sources:
  - Xray stats API (vless/vmess/trojan/ss)  -> `xray api statsquery`
  - WireGuard peer transfer                 -> `wg show wg0 transfer`

NOTE: this daemon NEVER touches iptables. An earlier version inserted
owner-match rules into the OUTPUT chain on every loop; the -C check could
fail repeatedly and the rules piled up until all outbound traffic (including
sshd banners and the Xray TLS handshake) was dropped, locking the box out.
SSH byte accounting is therefore intentionally not implemented here.
ponytail: SSH/ZiVPN usage is not counted. If needed, add a dedicated
nftables counter table set up ONCE at install time, never from this loop.
"""
import json
import os
import re
import sqlite3
import subprocess
import time

DB_PATH = "/var/lib/shirobot.db"
XRAY_BIN = "/usr/local/bin/xray"
XRAY_API = "127.0.0.1:10085"
STATE_DIR = "/var/lib/shiro_traffic"
INTERVAL = 20

os.makedirs(STATE_DIR, exist_ok=True)


def db():
    return sqlite3.connect(DB_PATH, timeout=10)


# ---------- XRAY (vless / vmess / trojan / ss) ----------
def collect_xray():
    """Absolute cumulative bytes per user, keyed by username."""
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
    """current = absolute counters. Add only the growth since last tick."""
    if not current:
        return
    prev = load_snapshot(source)
    conn = db()
    c = conn.cursor()
    for uname, cur_val in current.items():
        prev_val = prev.get(uname, 0)
        # counter reset (service restart) -> treat current as the delta
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
    print("Shiro Traffic Collector started (xray + wireguard, no iptables).")
    while True:
        try:
            apply_deltas(collect_xray(), "xray")
            apply_deltas(collect_wireguard(), "wireguard")
        except Exception as e:
            print(f"Collector error: {e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
