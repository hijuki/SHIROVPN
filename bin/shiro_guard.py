#!/usr/bin/env python3
import os
import re
import sys
import time
import json
import sqlite3
import datetime
import subprocess

def valid_username(u):
    return bool(re.match(r'^[a-z0-9_-]+$', u))

DB_PATH = "/var/lib/shirobot.db"
XRAY_CONFIG = "/usr/local/etc/xray/config.json"
ACCESS_LOG = "/var/log/xray/access.log"

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
                    print(f"PURGING EXPIRED ACCOUNT: {username} ({proto}) [Exp: {exp_str}]")
                    
                    if proto == "ssh":
                        if valid_username(username):
                            subprocess.run(["pkill", "-9", "-u", username], capture_output=True)
                            subprocess.run(["userdel", "-r", "-f", username], capture_output=True)
                        else:
                            print(f"Invalid username, skipping purge: {username}")
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
                        except Exception: pass
                    elif proto == "wg":
                        subprocess.run(["python3", "/usr/local/bin/manage_wg.py", "del", username], capture_output=True)

                    c.execute("DELETE FROM accounts WHERE id=?", (acc_id,))
                    conn.commit()

                    # Send Notification
                    send_alert_box(
                        title="AKUN EXPIRED DIHAPUS",
                        badge="⏳",
                        items={
                            "👤 <b>Pengguna</b>": f"ID <code>{user_id}</code>",
                            "🔑 <b>Akun</b>    ": f"<code>{username}</code>",
                            "🔌 <b>Protokol</b>": f"<b>{proto.upper()}</b>",
                            "📅 <b>Expired</b> ": f"<code>{exp_str}</code>",
                            "🛡️ <b>Status</b>  ": "<code>Berhasil Dihapus</code>"
                        },
                        footer="Masa aktif akun telah berakhir dan telah dibersihkan otomatis."
                    )
            except Exception as e:
                print(f"Error parsing exp for {username}: {e}")

        conn.close()
    except Exception as e:
        print(f"DB Error check_expired: {e}")

# 2. SSH MULTI-IP & SESSION LIMITER
def enforce_ssh_ip_limit():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT username, ip_limit, user_id FROM accounts WHERE protocol='ssh'")
        ssh_users = {row[0]: (row[1] or 2, row[2]) for row in c.fetchall()}
        conn.close()

        out = subprocess.run("ps -eo pid,user,args | grep -E 'sshd:|dropbear' | grep -v grep", shell=True, capture_output=True, text=True).stdout
        user_pids = {}
        for line in out.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2:
                pid, uname = parts[0], parts[1]
                if uname in ssh_users:
                    user_pids.setdefault(uname, []).append(pid)

        for uname, pids in user_pids.items():
            limit, uid = ssh_users[uname]
            if len(pids) > limit:
                print(f"SSH IP VIOLATION: {uname} has {len(pids)} sessions (Limit: {limit})")
                excess = pids[limit:]
                for p in excess:
                    subprocess.run(["kill", "-9", p], capture_output=True)
                
                send_alert_box(
                    title="PERINGATAN MULTI-LOGIN SSH",
                    badge="🚨",
                    items={
                        "👤 <b>Pengguna</b>  ": f"ID <code>{uid}</code>",
                        "🔑 <b>Akun</b>      ": f"<code>{uname}</code>",
                        "🌐 <b>Limit Device</b>": f"<b>{limit} IP</b>",
                        "⚠️ <b>Terdeteksi</b>  ": f"<b>{len(pids)} Koneksi Aktif</b>",
                        "🛡️ <b>Tindakan</b>    ": "<code>Koneksi berlebih diputus</code>"
                    },
                    footer="Koneksi yang melebihi batas perangkat otomatis diputus."
                )
    except Exception as e:
        print(f"SSH IP limit check error: {e}")

# 3. XRAY (VLESS / VMESS / TROJAN) MULTI-IP LIMITER
def enforce_xray_ip_limit():
    try:
        if not os.path.exists(ACCESS_LOG):
            return
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT username, ip_limit, user_id, protocol FROM accounts WHERE protocol IN ('vless', 'vmess', 'trojan')")
        xray_users = {row[0]: (row[1] or 2, row[2], row[3]) for row in c.fetchall()}
        conn.close()

        if not xray_users:
            return

        # Read last 200 lines of access log
        out = subprocess.run(["tail", "-n", "200", ACCESS_LOG], capture_output=True, text=True).stdout
        user_ips = {}
        for line in out.strip().splitlines():
            m = re.search(r"from (?:tcp:)?([0-9.]+):\d+.*email:\s*([a-zA-Z0-9_-]+)", line)
            if m:
                ip, email = m.group(1), m.group(2).split("@")[0]
                if email in xray_users:
                    user_ips.setdefault(email, set()).add(ip)

        for uname, ips in user_ips.items():
            limit, uid, proto = xray_users[uname]
            if len(ips) > limit:
                print(f"XRAY MULTI-IP VIOLATION: {uname} using {len(ips)} IPs (Limit: {limit})")
                send_alert_box(
                    title=f"PERINGATAN MULTI-IP {proto.upper()}",
                    badge="🚨",
                    items={
                        "👤 <b>Pengguna</b>  ": f"ID <code>{uid}</code>",
                        "🔑 <b>Akun</b>      ": f"<code>{uname}</code>",
                        "🔌 <b>Protokol</b>  ": f"<b>{proto.upper()}</b>",
                        "🌐 <b>Limit Device</b>": f"<b>{limit} IP</b>",
                        "⚠️ <b>IP Aktif</b>   ": f"<code>{', '.join(list(ips)[:3])}</code> ({len(ips)} IP)",
                        "🛡️ <b>Status</b>    ": "<code>Monitoring Alert Terkirim</code>"
                    },
                    footer="Pengguna terdeteksi melebihi batas login perangkat."
                )
    except Exception as e:
        print(f"Xray IP limit error: {e}")

# 4. QUOTA DATA ENFORCER
def enforce_quota_limits():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, user_id, username, protocol, quota_gb, used_bytes FROM accounts")
        rows = c.fetchall()
        
        for r in rows:
            aid, uid, uname, proto, quota_str, used_b = r
            if not quota_str or "unlimited" in str(quota_str).lower():
                continue
            m = re.search(r'(\d+)', str(quota_str))
            if m:
                total_bytes = float(m.group(1)) * (1024**3)
                if (used_b or 0) >= total_bytes:
                    print(f"QUOTA EXCEEDED: {uname} used {used_b} >= {total_bytes}")
                    if proto == "ssh":
                        if valid_username(uname):
                            subprocess.run(["pkill", "-9", "-u", uname], capture_output=True)
                            subprocess.run(["userdel", "-r", "-f", uname], capture_output=True)
                        else:
                            print(f"Invalid username, skipping quota purge: {uname}")
                    elif proto in ["vless", "vmess", "trojan"]:
                        remove_from_xray(uname)
                    elif proto == "wg":
                        subprocess.run(["python3", "/usr/local/bin/manage_wg.py", "del", uname], capture_output=True)

                    c.execute("DELETE FROM accounts WHERE id=?", (aid,))
                    conn.commit()

                    send_alert_box(
                        title="KUOTA DATA HABIS",
                        badge="📦",
                        items={
                            "👤 <b>Pengguna</b>  ": f"ID <code>{uid}</code>",
                            "🔑 <b>Akun</b>      ": f"<code>{uname}</code>",
                            "🔌 <b>Protokol</b>  ": f"<b>{proto.upper()}</b>",
                            "📦 <b>Batas Kuota</b>": f"<code>{quota_str}</code>",
                            "🛡️ <b>Status</b>    ": "<code>Akun Dihapus Otomatis</code>"
                        },
                        footer="Akun dinonaktifkan otomatis karena telah mencapai batas kuota pemakaian data."
                    )
        conn.close()
    except Exception as e:
        print(f"Quota enforcement error: {e}")

def main():
    print("Shiro Real-time Multi-Protocol Guard Daemon Active...")
    while True:
        check_expired_accounts()
        enforce_ssh_ip_limit()
        enforce_xray_ip_limit()
        enforce_quota_limits()
        time.sleep(5)

if __name__ == "__main__":
    main()
