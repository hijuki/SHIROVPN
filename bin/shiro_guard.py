#!/usr/bin/env python3
import os
import re
import sys
import time
import json
import sqlite3
import datetime
import subprocess

DB_PATH = "/var/lib/shirobot.db"
XRAY_CONFIG = "/usr/local/etc/xray/config.json"
ACCESS_LOG = "/var/log/xray/access.log"

def send_alert_box(title, badge, items, footer=""):
    try:
        sys.path.append("/usr/local/bin")
        from send_notif import send_notif
        body = [
            "╭━━━━━━━━━━━━━━━━━━━━━━╮",
            f"  {badge} <b>{title}</b>",
            "╰━━━━━━━━━━━━━━━━━━━━━━╯\n",
            "┌〔 📄 <b>ᴛᴇʟᴇᴍᴇᴛʀʏ ɪɴꜰᴏ</b> 〕"
        ]
        for idx, (k, v) in enumerate(items.items()):
            prefix = "└" if idx == len(items) - 1 else "├"
            body.append(f"{prefix} {k} : {v}")
        body.append("\n━━━━━━━━━━━━━━━━━━━━━━")
        if footer:
            body.append(f"<i>{footer}</i>")
        else:
            body.append("🤖 <i>Shiro Automatic Security Guard Daemon</i>")
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
                        except: pass
                    elif proto == "wg":
                        subprocess.run(["python3", "/usr/local/bin/manage_wg.py", "del", username], capture_output=True)

                    c.execute("DELETE FROM accounts WHERE id=?", (acc_id,))
                    conn.commit()

                    # Send Notification
                    send_alert_box(
                        title="ᴀᴋᴜɴ ᴇxᴘɪʀᴇᴅ ᴅɪᴘᴜʀɢᴇ",
                        badge="⏳",
                        items={
                            "👤 <b>ᴜꜱᴇʀɴᴀᴍᴇ</b>": f"<code>{username}</code>",
                            "🔌 <b>ᴘʀᴏᴛᴏᴋᴏʟ</b>": f"<b>{proto.upper()}</b>",
                            "📅 <b>ᴇxᴘɪʀᴇᴅ</b> ": f"<code>{exp_str}</code>",
                            "🆔 <b>ᴜꜱᴇʀ ɪᴅ</b> ": f"<code>{user_id}</code>",
                            "🛡️ <b>ᴀᴋꜱɪ</b>    ": "<code>AUTO PURGED (DELETED)</code>"
                        },
                        footer="Masa aktif akun telah berakhir dan telah dihapus dari server."
                    )
            except Exception as e:
                print(f"Error parsing exp for {username}: {e}")

        conn.close()
    except Exception as e:
        print(f"DB Error check_expired: {e}")

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
                    title="ᴘᴇʟᴀɴɢɢᴀʀᴀɴ ʟɪᴍɪᴛ ɪᴘ ꜱꜱʜ",
                    badge="🚨",
                    items={
                        "👤 <b>ᴜꜱᴇʀɴᴀᴍᴇ</b>  ": f"<code>{uname}</code>",
                        "🌐 <b>ʙᴀᴛᴀꜱ ʟɪᴍɪᴛ</b>": f"<b>{limit} IP Device</b>",
                        "⚠️ <b>ᴛᴇʀᴅᴇᴛᴇᴋꜱɪ</b> ": f"<b>{len(pids)} Koneksi Aktif</b>",
                        "🛡️ <b>ᴛɪɴᴅᴀᴋᴀɴ</b>  ": "<code>Koneksi Berlebih Telah Diputus</code>",
                        "🆔 <b>ᴜꜱᴇʀ ɪᴅ</b>   ": f"<code>{uid}</code>"
                    },
                    footer="Peringatan: Multi-login melebihi kuota perangkat yang diizinkan."
                )
    except Exception as e:
        print(f"SSH IP limit check error: {e}")

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
                        subprocess.run(["userdel", "-r", "-f", uname], capture_output=True)
                    elif proto in ["vless", "vmess", "trojan"]:
                        remove_from_xray(uname)
                    c.execute("DELETE FROM accounts WHERE id=?", (aid,))
                    conn.commit()

                    send_alert_box(
                        title="ᴋᴜᴏᴛᴀ ᴅᴀᴛᴀ ʜᴀʙɪꜱ",
                        badge="📦",
                        items={
                            "👤 <b>ᴜꜱᴇʀɴᴀᴍᴇ</b>": f"<code>{uname}</code>",
                            "🔌 <b>ᴘʀᴏᴛᴏᴋᴏʟ</b>": f"<b>{proto.upper()}</b>",
                            "📦 <b>ʙᴀᴛᴀꜱ ᴋᴜᴏᴛᴀ</b>": f"<code>{quota_str}</code>",
                            "🛡️ <b>ᴀᴋꜱɪ</b>    ": "<code>AUTO PURGED (QUOTA EXHAUSTED)</code>",
                            "🆔 <b>ᴜꜱᴇʀ ɪᴅ</b> ": f"<code>{uid}</code>"
                        },
                        footer="Akun dinonaktifkan otomatis karena telah mencapai batas kuota data."
                    )
        conn.close()
    except Exception as e:
        print(f"Quota enforcement error: {e}")

def main():
    print("Shiro Real-time Guard Daemon Active...")
    while True:
        check_expired_accounts()
        enforce_ssh_ip_limit()
        enforce_quota_limits()
        time.sleep(5)

if __name__ == "__main__":
    main()
