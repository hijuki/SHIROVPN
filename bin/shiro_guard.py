#!/usr/bin/env python3
"""
Shiro Real-time Guard Daemon:
  1. Auto-Purge Expired Accounts (Trial 30 mins & Regular dates).
  2. Multi-IP Limiter for ALL Protocols (SSH, Dropbear, VLESS, VMess, Trojan):
     - Correctly identifies ONLY true incoming client IP addresses.
     - 2-Strike Enforcement:
         * Strike 1: Warning notification to Telegram.
         * Strike 2: Auto-delete / permanent suspend + deletion notification.
  3. Auto-Purge Exceeded Bandwidth Quota.
"""
import os
import re
import sys
import time
import json
import pwd
import sqlite3
import datetime
import subprocess

def valid_username(u):
    return bool(re.match(r'^[a-z0-9_-]+$', u))

DB_PATH = "/var/lib/shirobot.db"
XRAY_CONFIG = "/usr/local/etc/xray/config.json"
ACCESS_LOG = "/var/log/xray/access.log"

# Persistent memory for violations: {username: {"strikes": int, "last_strike_time": float}}
VIOLATIONS = {}

def send_alert_box(title, badge, items, footer=""):
    try:
        sys.path.append("/usr/local/bin")
        from send_notif import send_notif
        body = [
            f"{badge} <b>{title.upper()}</b>",
            "━━━━━━━━━━━━━━━━━━━━━━"
        ]
        for k, v in items.items():
            body.append(f"{k} : {v}")
        body.append("━━━━━━━━━━━━━━━━━━━━━━")
        if footer:
            body.append(f"ℹ️ <i>{footer}</i>")
        send_notif("\n".join(body))
    except Exception as e:
        print(f"Error sending alert: {e}")

def delete_account_complete(acc_id, user_id, username, proto, reason="MULTI-IP VIOLATION (2/2)"):
    """Completely purges an account across Linux system, Xray, ZiVPN, WireGuard, and DB."""
    try:
        print(f"PURGING ACCOUNT: {username} ({proto}) [Reason: {reason}]")
        if proto == "ssh":
            if valid_username(username):
                subprocess.run(["pkill", "-9", "-u", username], capture_output=True)
                subprocess.run(["userdel", "-r", "-f", username], capture_output=True)
        elif proto in ["vless", "vmess", "trojan"]:
            remove_from_xray(username)
        elif proto == "zivpn":
            try:
                if os.path.exists("/etc/zivpn/users.db"):
                    with open("/etc/zivpn/users.db", "r") as f:
                        zlines = f.readlines()
                    with open("/etc/zivpn/users.db", "w") as f:
                        for zl in zlines:
                            if not zl.startswith(f"{username}:"):
                                f.write(zl)
                    subprocess.run(["systemctl", "restart", "zivpn"], capture_output=True)
            except Exception:
                pass
        elif proto == "wg":
            subprocess.run(["python3", "/usr/local/bin/manage_wg.py", "del", username], capture_output=True)

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM accounts WHERE id=?", (acc_id,))
        conn.commit()
        conn.close()

        VIOLATIONS.pop(username, None)

        send_alert_box(
            title="AKUN DIHAPUS OTOMATIS",
            badge="🚫",
            items={
                "👤 <b>Pengguna</b>  ": f"ID <code>{user_id}</code>",
                "🔑 <b>Akun</b>      ": f"<code>{username}</code>",
                "🔌 <b>Protokol</b>  ": f"<b>{proto.upper()}</b>",
                "⚠️ <b>Pelanggaran</b>": f"<code>{reason}</code>",
                "🛡️ <b>Tindakan</b>   ": "<code>Akun Dihapus & Dibanned</code>"
            },
            footer="Akun dihapus permanen oleh sistem karena telah melanggar batas multi-login 2 kali."
        )
    except Exception as e:
        print(f"Error purging account {username}: {e}")

def remove_from_xray(username):
    try:
        if not os.path.exists(XRAY_CONFIG):
            return
        with open(XRAY_CONFIG, "r") as f:
            cfg = json.load(f)
        
        modified = False
        for ib in cfg.get("inbounds", []):
            settings = ib.get("settings", {})
            clients = settings.get("clients", [])
            new_clients = []
            for cl in clients:
                email = cl.get("email", "")
                if email == username or email == f"{username}@shiro.id":
                    modified = True
                else:
                    new_clients.append(cl)
            settings["clients"] = new_clients
        
        if modified:
            with open(XRAY_CONFIG, "w") as f:
                json.dump(cfg, f, indent=2)
            subprocess.run(["systemctl", "restart", "xray"], capture_output=True)
            print(f"Xray clients updated, removed {username}")
    except Exception as e:
        print(f"Error removing {username} from Xray: {e}")

# 1. EXPIRED ACCOUNTS CHECKER & PURGE
def check_expired_accounts():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, user_id, username, protocol, exp_date FROM accounts")
        accounts = c.fetchall()
        now = datetime.datetime.now()

        for acc in accounts:
            acc_id, user_id, username, proto, exp_str = acc
            try:
                clean_exp = exp_str.replace(" WIB", "").strip()
                is_expired = False

                # Format 1: 30 Minutes / Menit with (HH:MM:SS) or (HH:MM)
                if "(" in clean_exp and ":" in clean_exp:
                    m = re.search(r'\((\d+):(\d+)(?::(\d+))?', clean_exp)
                    if m:
                        h, mn = int(m.group(1)), int(m.group(2))
                        sec = int(m.group(3)) if m.group(3) else 0
                        today = datetime.date.today()
                        exp_dt = datetime.datetime(today.year, today.month, today.day, h, mn, sec)
                        if now >= exp_dt:
                            is_expired = True
                # Format 2: DD/MM/YYYY HH:MM:SS or DD/MM/YYYY HH:MM
                elif "/" in clean_exp:
                    clean_dt = clean_exp.split()[0] + " " + clean_exp.split()[1] if " " in clean_exp else clean_exp
                    parts = clean_dt.split()
                    d_parts = parts[0].split("/")
                    t_parts = parts[1].split(":") if len(parts) > 1 else ["00", "00"]
                    exp_dt = datetime.datetime(int(d_parts[2]), int(d_parts[1]), int(d_parts[0]), int(t_parts[0]), int(t_parts[1]))
                    if now >= exp_dt:
                        is_expired = True
                # Format 3: YYYY-MM-DD
                elif "-" in clean_exp:
                    d_parts = clean_exp[:10].split("-")
                    exp_dt = datetime.datetime(int(d_parts[0]), int(d_parts[1]), int(d_parts[2]), 23, 59, 59)
                    if now >= exp_dt:
                        is_expired = True

                if is_expired:
                    delete_account_complete(acc_id, user_id, username, proto, reason=f"MASA AKTIF HABIS ({exp_str})")
            except Exception as e:
                print(f"Error parsing exp for {username}: {e}")

        conn.close()
    except Exception as e:
        print(f"DB Error check_expired: {e}")

# 2. UNIVERSAL 2-STRIKE MULTI-IP ENFORCER
def process_multi_ip_violation(acc_id, user_id, username, proto, limit, detected_ips):
    """
    Handles Multi-IP violation with 2-Strike system:
    - Strike 1: Warning notification to Telegram.
    - Strike 2: Delete account permanently.
    """
    now = time.time()
    v_data = VIOLATIONS.get(username, {"strikes": 0, "last_time": 0})
    
    # Cooldown 120s to prevent spamming notifications on the same incident
    if (now - v_data.get("last_time", 0)) < 120:
        return

    v_data["strikes"] += 1
    v_data["last_time"] = now
    VIOLATIONS[username] = v_data

    strike_num = v_data["strikes"]

    if strike_num == 1:
        # Warning (Strike 1)
        send_alert_box(
            title=f"PERINGATAN MULTI-IP (1/2) - {proto.upper()}",
            badge="⚠️",
            items={
                "👤 <b>Pengguna</b>  ": f"ID <code>{user_id}</code>",
                "🔑 <b>Akun</b>      ": f"<code>{username}</code>",
                "🔌 <b>Protokol</b>  ": f"<b>{proto.upper()}</b>",
                "🌐 <b>Batas Limit</b>": f"<b>{limit} Device/IP</b>",
                "🚨 <b>Terdeteksi</b> ": "<b>Login lebih dari batas</b>",
                "⚡ <b>Status</b>     ": "<code>PERINGATAN PERTAMA</code>"
            },
            footer="Jika terdeteksi multi-login sekali lagi (Peringatan 2/2), akun akan otomatis DIHAPUS permanen."
        )
    elif strike_num >= 2:
        # Strike 2: Auto-Delete
        delete_account_complete(acc_id, user_id, username, proto, reason=f"MULTI-IP (Melebihi Limit {limit} Device)")

# 3. SSH MULTI-IP CHECKER (Inspects pure INCOMING client connections only)
def enforce_ssh_ip_limit():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, user_id, username, ip_limit FROM accounts WHERE protocol='ssh'")
        ssh_accounts = {row[2]: (row[0], row[1], row[3] or 2) for row in c.fetchall()}
        conn.close()

        if not ssh_accounts:
            return

        user_ips = {}

        # Source 1: Check environment variables of user session processes for SSH_CONNECTION
        for pid in os.listdir("/proc"):
            if pid.isdigit():
                try:
                    p_stat = os.stat(f"/proc/{pid}")
                    uname = pwd.getpwuid(p_stat.st_uid).pw_name
                    if uname in ssh_accounts:
                        with open(f"/proc/{pid}/environ", "rb") as f:
                            env = f.read().decode("utf-8", errors="ignore")
                            if "SSH_CONNECTION=" in env:
                                for line in env.split("\0"):
                                    if line.startswith("SSH_CONNECTION="):
                                        parts = line.split("=")[1].split()
                                        if parts:
                                            clip = parts[0]
                                            if clip not in ["127.0.0.1", "::1", "localhost", "95.111.196.242"]:
                                                user_ips.setdefault(uname, set()).add(clip)
                except Exception:
                    pass

        # Source 2: Check `who` command for active SSH login terminals
        out_who = subprocess.run(["who"], capture_output=True, text=True).stdout
        for line in out_who.splitlines():
            parts = line.strip().split()
            if len(parts) >= 5:
                uname = parts[0]
                ip_match = re.search(r'\(([^)]+)\)', line)
                if uname in ssh_accounts and ip_match:
                    rip = ip_match.group(1).replace("::ffff:", "")
                    if rip and rip not in ["localhost", "127.0.0.1", "::1", "95.111.196.242"]:
                        user_ips.setdefault(uname, set()).add(rip)

        for uname, ips in user_ips.items():
            acc_id, uid, limit = ssh_accounts[uname]
            if len(ips) > limit:
                print(f"SSH MULTI-IP VIOLATION: {uname} using {len(ips)} IPs -> {ips} (Limit: {limit})")
                process_multi_ip_violation(acc_id, uid, uname, "ssh", limit, ips)

    except Exception as e:
        print(f"SSH IP limit check error: {e}")

# 4. XRAY (VLESS / VMESS / TROJAN) MULTI-IP CHECKER
def enforce_xray_ip_limit():
    try:
        if not os.path.exists(ACCESS_LOG):
            return
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, user_id, username, protocol, ip_limit FROM accounts WHERE protocol IN ('vless', 'vmess', 'trojan')")
        xray_accounts = {row[2]: (row[0], row[1], row[3], row[4] or 2) for row in c.fetchall()}
        conn.close()

        if not xray_accounts:
            return

        # Read last 100 lines of access log
        out = subprocess.run(["tail", "-n", "100", ACCESS_LOG], capture_output=True, text=True).stdout
        user_ips = {}
        for line in out.strip().splitlines():
            m = re.search(r"from (?:tcp:)?([0-9.]+):\d+.*email:\s*([a-zA-Z0-9_-]+)", line)
            if m:
                ip, email = m.group(1), m.group(2).split("@")[0]
                if email in xray_accounts and ip not in ["127.0.0.1", "95.111.196.242"]:
                    user_ips.setdefault(email, set()).add(ip)

        for uname, ips in user_ips.items():
            acc_id, uid, proto, limit = xray_accounts[uname]
            if len(ips) > limit:
                print(f"XRAY MULTI-IP VIOLATION: {uname} using {len(ips)} IPs -> {ips} (Limit: {limit})")
                process_multi_ip_violation(acc_id, uid, uname, proto, limit, ips)

    except Exception as e:
        print(f"Xray IP limit error: {e}")

# 5. QUOTA DATA ENFORCER
def enforce_quota_limits():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, user_id, username, protocol, quota_gb, used_bytes FROM accounts")
        rows = c.fetchall()
        conn.close()
        
        for r in rows:
            aid, uid, uname, proto, quota_str, used_b = r
            if not quota_str or "unlimited" in str(quota_str).lower():
                continue
            m = re.search(r'(\d+)', str(quota_str))
            if m:
                total_bytes = float(m.group(1)) * (1024**3)
                if (used_b or 0) >= total_bytes:
                    delete_account_complete(aid, uid, uname, proto, reason=f"KUOTA DATA HABIS ({quota_str})")
    except Exception as e:
        print(f"Quota enforcement error: {e}")

def main():
    print("Shiro Real-time 2-Strike Multi-Protocol Guard Daemon Active...")
    while True:
        check_expired_accounts()
        enforce_ssh_ip_limit()
        enforce_xray_ip_limit()
        enforce_quota_limits()
        time.sleep(5)

if __name__ == "__main__":
    main()
