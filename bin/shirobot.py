import os
import sys
import json
import uuid
import time
import random
import string
import sqlite3
import datetime
import asyncio
import subprocess
import re

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)


def valid_username(u):
    """Validate username: only lowercase letters, digits, underscore, hyphen."""
    return bool(re.match(r'^[a-z0-9_-]+$', u))

# ================= CONFIGURATION =================
# Dynamic settings loader from SQLite DB
def _db_boot(key, fallback=""):
    try:
        import sqlite3
        conn = sqlite3.connect("/var/lib/shirobot.db")
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = c.fetchone()
        conn.close()
        return row[0] if row and row[0] else fallback
    except Exception:
        return fallback

BOT_TOKEN = _db_boot("bot_token", "YOUR_BOT_TOKEN_HERE")
ADMIN_ID = int(_db_boot("admin_id", "1234567890"))
ADMIN_USER = _db_boot("admin_user", "@YourTelegramUsername")
DOMAIN = _db_boot("domain", "your-domain.com")
DB_PATH = "/var/lib/shirobot.db"

# Auto Detect Server Info
SERVER_INFO = {
    "isp": "UpCloud Singapore Pte Ltd",
    "city": "Singapore",
    "country": "SG",
    "country_name": "Singapore 🇸🇬"
}

def detect_server_info():
    global SERVER_INFO
    try:
        req = urllib.request.Request("https://ipinfo.io/json", headers={"User-Agent": "curl/7.68.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            org = data.get("org", "UpCloud Ltd")
            # strip AS number if present
            if " " in org and org.startswith("AS"):
                org = " ".join(org.split(" ")[1:])
            city = data.get("city", "Singapore")
            country = data.get("country", "SG")
            flag = "🇸🇬" if country == "SG" else "🌐"
            SERVER_INFO["isp"] = org
            SERVER_INFO["city"] = city
            SERVER_INFO["country"] = country
            SERVER_INFO["country_name"] = f"{city} {flag}"
    except Exception as e:
        pass

detect_server_info()


# State Constants for Buy Flow
(
    BUY_PROTO,
    BUY_SERVER,
    BUY_USER,
    BUY_PASS,
    BUY_DAYS,
    BUY_LIMIT,
    BUY_QUOTA,
) = range(7)

# State Constants for Admin Flows
(ADMIN_INPUT_PRICE,) = range(1)
(ADMIN_INPUT_LIMIT,) = range(1)
(ADMIN_INPUT_QUOTA,) = range(1)
(ADMIN_INPUT_TOPUP_USER, ADMIN_INPUT_TOPUP_AMT) = range(2)
(ADMIN_INPUT_BROADCAST,) = range(1)

# State Constants for Renew Flow
(RENEW_INPUT_DAYS,) = range(1)

# ================= DATABASE INITIALIZER =================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        user_id INTEGER UNIQUE,
        username TEXT,
        balance INTEGER DEFAULT 0,
        role TEXT DEFAULT 'member',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT UNIQUE,
        protocol TEXT,
        uuid_or_pass TEXT,
        exp_date TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        password TEXT DEFAULT '',
        days INTEGER DEFAULT 30,
        quota_gb TEXT DEFAULT '100 GB',
        ip_limit INTEGER DEFAULT 2,
        uuid TEXT DEFAULT '',
        config_link TEXT DEFAULT '',
        used_bytes INTEGER DEFAULT 0,
        used_gb REAL DEFAULT 0.0,
        auto_renew INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        type TEXT,
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS trial_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        protocol TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    # Seed default settings
    defaults = {
        "price_per_day": "100",
        "default_ip_limit": "2",
        "default_quota": "100 GB",
        "notif_chat_id": "-1000000000000",
        "notif_thread_id": "3"
    }
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

    conn.commit()
    conn.close()

def get_setting(key, default=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else default

def set_setting(key, value):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def get_user(user_id, username=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    role = "owner" if user_id == ADMIN_ID else "member"
    c.execute("SELECT user_id, username, balance, role FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row:
        c.execute("INSERT INTO users (user_id, username, balance, role) VALUES (?, ?, 0, ?)", (user_id, username or f"user_{user_id}", role))
        conn.commit()
        c.execute("SELECT user_id, username, balance, role FROM users WHERE user_id=?", (user_id,))
        row = c.fetchone()
    conn.close()
    return {"user_id": row[0], "username": row[1], "balance": row[2], "role": row[3]}

def update_user_balance(user_id, amount):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()

def get_account_quota_info(username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT quota_gb, used_bytes FROM accounts WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    if not row:
        return "100 GB", "0 B", "0 B / 100 GB (0%)", "▱▱▱▱▱▱▱▱▱▱ 100 GB sisa", 0.0
    
    quota_str, used_bytes = row[0], row[1] or 0
    
    def fmt_b(b):
        if b < 1024: return f"{b:.0f} B"
        elif b < 1024**2: return f"{b/1024:.2f} KB"
        elif b < 1024**3: return f"{b/(1024**2):.2f} MB"
        else: return f"{b/(1024**3):.2f} GB"

    used_fmt = fmt_b(used_bytes)
    if not quota_str or "unlimited" in str(quota_str).lower():
        return "Unlimited", used_fmt, f"{used_fmt} / Unlimited", "▰▰▰▰▰▰▰▰▰▰ Unlimited", 0.0
    
    m = re.search(r'(\d+)', str(quota_str))
    if m:
        total_gb = float(m.group(1))
        total_bytes = total_gb * (1024**3)
        used = float(used_bytes)
        pct = min(100.0, (used / total_bytes) * 100) if total_bytes > 0 else 0.0
        left_bytes = max(0.0, total_bytes - used)
        left_fmt = fmt_b(left_bytes)
        
        filled = min(10, max(0, int(round((pct / 100.0) * 10))))
        empty = 10 - filled
        bar = "▰" * filled + "▱" * empty
        
        ratio_str = f"{used_fmt} / {total_gb:.0f} GB ({pct:.1f}%)"
        bar_str = f"{bar} (Sisa: {left_fmt})"
        return f"{total_gb:.0f} GB", used_fmt, ratio_str, bar_str, pct
    
    return str(quota_str), used_fmt, f"{used_fmt} / {quota_str}", "▱▱▱▱▱▱▱▱▱▱", 0.0

def get_server_stats():
    try:
        uptime = subprocess.check_output(["uptime", "-p"], text=True).strip().replace("up ", "")
    except Exception:
        uptime = "Active"
    
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM accounts")
        total_acc = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users")
        total_users = c.fetchone()[0]
        conn.close()
    except Exception:
        total_acc, total_users = 0, 0
    
    return {"uptime": uptime, "total_acc": total_acc, "total_users": total_users}

# ================= NOTIFICATION HELPER =================
def send_telegram_notif(text):
    try:
        subprocess.Popen(["python3", "/usr/local/bin/send_notif.py", text])
    except Exception as e:
        print("Error sending notif:", e)

# ================= FORMATTERS =================
def format_ssh_account(user, password, exp_str, ip_limit=2, quota="100 GB"):
    _, _, q_ratio, q_bar, _ = get_account_quota_info(user)
    domain_val = get_setting("domain", DOMAIN)
    return f"""╭━━━━━━━━━━━━━━━━━━━━━━╮
      🚀 <b>ꜱꜱʜ ᴡꜱ ꜱꜱʟ ᴀᴄᴄᴏᴜɴᴛ</b>
╰━━━━━━━━━━━━━━━━━━━━━━╯

┌〔 📄 <b>ᴀᴄᴄᴏᴜɴᴛ ɪɴꜰᴏ</b> 〕
├ 👤 <b>ᴜꜱᴇʀɴᴀᴍᴇ</b> : <code>{user}</code>
├ 🔑 <b>ᴘᴀꜱꜱᴡᴏʀᴅ</b> : <code>{password}</code>
├ 📅 <b>ᴇxᴘɪʀᴇᴅ</b>  : <code>{exp_str}</code>
├ 🌐 <b>ɪᴘ ʟɪᴍɪᴛ</b> : {ip_limit} IP
├ 📦 <b>ǫᴜᴏᴛᴀ</b>    : {q_ratio}
├ 📊 <b>ᴘʀᴏɢʀᴇꜱꜱ</b>  : <code>{q_bar}</code>
└ 🟢 <b>ꜱᴛᴀᴛᴜꜱ</b>   : <code>ACTIVE</code>

━━━━━━━━━━━━━━━━━━━━━━

┌〔 🌍 <b>ꜱᴇʀᴠᴇʀ</b> 〕
├ 🌐 <b>ᴅᴏᴍᴀɪɴ</b>      : <code>{DOMAIN}</code>
├ 🌍 <b>ɪꜱᴘ</b>         : UpCloud Singapore 🇸🇬
└ 🧭 <b>ɪᴘ ꜱᴇʀᴠᴇʀ</b>   : <code>{DOMAIN}</code>

━━━━━━━━━━━━━━━━━━━━━━

┌〔 🔌 <b>ᴘᴏʀᴛ</b> 〕
├ 🔐 <b>ᴛʟꜱ / ᴡꜱ ꜱꜱʟ</b> : 443 (Path: /ssh-ws)
├ 🌐 <b>ᴏᴘᴇɴꜱꜱʜ</b>     : 80, 22
├ 📡 <b>ᴅʀᴏᴘʙᴇᴀʀ</b>    : 109, 110
├ 🛡 <b>ꜱᴛᴜɴɴᴇʟ</b>     : 222, 333, 444, 777
└ 🎮 <b>ʙᴀᴅᴠᴘɴ ᴜᴅᴘ</b>  : 7100-7900

━━━━━━━━━━━━━━━━━━━━━━

📡 <b>ʜᴛᴛᴘ ᴄᴜꜱᴛᴏᴍ</b>
<code>{DOMAIN}:80@{user}:{password}</code>

━━━━━━━━━━━━━━━━━━━━━━

📄 <b>ᴘᴀʏʟᴏᴀᴅ ᴡꜱ ꜱꜱʟ</b>
<code>GET /ssh-ws HTTP/1.1[crlf]Host: {DOMAIN}[crlf]Upgrade: websocket[crlf][crlf]</code>

━━━━━━━━━━━━━━━━━━━━━━

🎉 <b>ᴀᴄᴄᴏᴜɴᴛ ʙᴇʀʜᴀꜱɪʟ ᴅɪʙᴜᴀᴛ</b>
🤝 <i>Terima kasih telah menggunakan layanan kami.</i>"""

def format_xray_account(proto, user, u_id, exp_str, ip_limit=2, quota="100 GB"):
    p_name = proto.upper()
    _, _, q_ratio, q_bar, _ = get_account_quota_info(user)
    domain_val = get_setting("domain", DOMAIN)
    
    if proto == "vless":
        link = f"vless://{u_id}@{DOMAIN}:443?path=%2Fvless&security=tls&encryption=none&type=ws&sni={DOMAIN}#{user}"
        grpc_link = f"vless://{u_id}@{DOMAIN}:443?mode=gun&security=tls&encryption=none&type=grpc&serviceName=vless-grpc&sni={DOMAIN}#{user}-gRPC"
    elif proto == "trojan":
        link = f"trojan://{u_id}@{DOMAIN}:443?path=%2Ftrojan-ws&security=tls&type=ws&sni={DOMAIN}#{user}"
        grpc_link = f"trojan://{u_id}@{DOMAIN}:443?mode=gun&security=tls&type=grpc&serviceName=trojan-grpc&sni={DOMAIN}#{user}-gRPC"
    else: # vmess
        vm_dict = {
            "v": "2", "ps": user, "add": DOMAIN, "port": "443", "id": u_id,
            "aid": "0", "net": "ws", "path": "/vmess", "type": "none",
            "host": DOMAIN, "tls": "tls", "sni": DOMAIN
        }
        import base64
        link = "vmess://" + base64.b64encode(json.dumps(vm_dict).encode()).decode()
        grpc_link = link

    return f"""╭━━━━━━━━━━━━━━━━━━━━━━╮
      ⚡ <b>{p_name} ᴛʟꜱ ᴀᴄᴄᴏᴜɴᴛ</b>
╰━━━━━━━━━━━━━━━━━━━━━━╯

┌〔 📄 <b>ᴀᴄᴄᴏᴜɴᴛ ɪɴꜰᴏ</b> 〕
├ 👤 <b>ᴜꜱᴇʀɴᴀᴍᴇ</b> : <code>{user}</code>
├ 🔑 <b>ᴜᴜɪᴅ / ᴋᴇʏ</b>: <code>{u_id}</code>
├ 📅 <b>ᴇxᴘɪʀᴇᴅ</b>  : <code>{exp_str}</code>
├ 🌐 <b>ɪᴘ ʟɪᴍɪᴛ</b> : {ip_limit} IP
├ 📦 <b>ǫᴜᴏᴛᴀ</b>    : {q_ratio}
├ 📊 <b>ᴘʀᴏɢʀᴇꜱꜱ</b>  : <code>{q_bar}</code>
└ 🟢 <b>ꜱᴛᴀᴛᴜꜱ</b>   : <code>ACTIVE</code>

━━━━━━━━━━━━━━━━━━━━━━

┌〔 🌍 <b>ꜱᴇʀᴠᴇʀ</b> 〕
├ 🌐 <b>ᴅᴏᴍᴀɪɴ</b>      : <code>{DOMAIN}</code>
├ 🌍 <b>ɪꜱᴘ</b>         : UpCloud Singapore 🇸🇬
└ 🧭 <b>ɪᴘ ꜱᴇʀᴠᴇʀ</b>   : <code>{DOMAIN}</code>

━━━━━━━━━━━━━━━━━━━━━━

┌〔 🔌 <b>ᴘᴏʀᴛ</b> 〕
├ 🔐 <b>ᴛʟꜱ / ᴡꜱ ꜱꜱʟ</b> : 443 (Path: /{proto})
├ 🚀 <b>ɢʀᴘᴄ ꜱᴇʀᴠɪᴄᴇ</b>: {proto}-grpc (ALPN h2)
└ 🎮 <b>ʙᴀᴅᴠᴘɴ ᴜᴅᴘ</b>  : 7100-7900

━━━━━━━━━━━━━━━━━━━━━━

🔗 <b>ᴄᴏɴꜰɪɢ ᴜʀʟ (ᴡꜱ ᴛʟꜱ)</b>
<code>{link}</code>

━━━━━━━━━━━━━━━━━━━━━━

🔗 <b>ᴄᴏɴꜰɪɢ ᴜʀʟ (ɢʀᴘᴄ ᴛʟꜱ)</b>
<code>{grpc_link}</code>

━━━━━━━━━━━━━━━━━━━━━━

🎉 <b>ᴀᴄᴄᴏᴜɴᴛ ʙᴇʀʜᴀꜱɪʟ ᴅɪʙᴜᴀᴛ</b>
🤝 <i>Terima kasih telah menggunakan layanan kami.</i>"""

def format_zivpn_account(user, password, exp_str, ip_limit=2, quota="100 GB"):
    _, _, q_ratio, q_bar, _ = get_account_quota_info(user)
    domain_val = get_setting("domain", DOMAIN)
    return f"""╭━━━━━━━━━━━━━━━━━━━━━━╮
      🎮 <b>ᴜᴅᴘ ᴢɪᴠᴘɴ ɢᴀᴍɪɴɢ</b>
╰━━━━━━━━━━━━━━━━━━━━━━╯

┌〔 📄 <b>ᴀᴄᴄᴏᴜɴᴛ ɪɴꜰᴏ</b> 〕
├ 👤 <b>ᴜꜱᴇʀɴᴀᴍᴇ</b> : <code>{user}</code>
├ 🔑 <b>ᴘᴀꜱꜱᴡᴏʀᴅ</b> : <code>{password}</code>
├ 📅 <b>ᴇxᴘɪʀᴇᴅ</b>  : <code>{exp_str}</code>
├ 🌐 <b>ɪᴘ ʟɪᴍɪᴛ</b> : {ip_limit} IP
├ 📦 <b>ǫᴜᴏᴛᴀ</b>    : {q_ratio}
├ 📊 <b>ᴘʀᴏɢʀᴇꜱꜱ</b>  : <code>{q_bar}</code>
└ 🟢 <b>ꜱᴛᴀᴛᴜꜱ</b>   : <code>ACTIVE</code>

━━━━━━━━━━━━━━━━━━━━━━

┌〔 🌍 <b>ꜱᴇʀᴠᴇʀ ᴅᴇᴛᴀɪʟꜱ</b> 〕
├ 🌐 <b>ᴅᴏᴍᴀɪɴ</b>      : <code>{DOMAIN}</code>
├ 🌍 <b>ɪꜱᴘ</b>         : UpCloud Singapore 🇸🇬
├ 🎮 <b>ᴜᴅᴘ ᴘᴏʀᴛ</b>    : 5667 / 6000-19999
└ 🛡 <b>ᴏʙꜰꜱ</b>        : zivpn

━━━━━━━━━━━━━━━━━━━━━━

🎉 <b>ᴀᴄᴄᴏᴜɴᴛ ʙᴇʀʜᴀꜱɪʟ ᴅɪʙᴜᴀᴛ</b>
🤝 <i>Terima kasih telah menggunakan layanan kami.</i>"""

def format_wg_account(user, exp_str, client_conf="", ip_limit=2, quota="100 GB"):
    _, _, q_ratio, q_bar, _ = get_account_quota_info(user)
    domain_val = get_setting("domain", DOMAIN)
    return f"""╭━━━━━━━━━━━━━━━━━━━━━━╮
      🛡️ <b>ᴡɪʀᴇɢᴜᴀʀᴅ ᴠᴘɴ ᴀᴄᴄᴏᴜɴᴛ</b>
╰━━━━━━━━━━━━━━━━━━━━━━╯

┌〔 📄 <b>ᴀᴄᴄᴏᴜɴᴛ ɪɴꜰᴏ</b> 〕
├ 👤 <b>ᴜꜱᴇʀɴᴀᴍᴇ</b> : <code>{user}</code>
├ 📅 <b>ᴇxᴘɪʀᴇᴅ</b>  : <code>{exp_str}</code>
├ 🌐 <b>ɪᴘ ʟɪᴍɪᴛ</b> : {ip_limit} IP
├ 📦 <b>ǫᴜᴏᴛᴀ</b>    : {q_ratio}
├ 📊 <b>ᴘʀᴏɢʀᴇꜱꜱ</b>  : <code>{q_bar}</code>
└ 🟢 <b>ꜱᴛᴀᴛᴜꜱ</b>   : <code>ACTIVE</code>

┌〔 🌍 <b>ꜱᴇʀᴠᴇʀ ᴅᴇᴛᴀɪʟꜱ</b> 〕
├ 🌐 <b>ᴅᴏᴍᴀɪɴ</b>      : <code>{DOMAIN}</code>
├ 🖥️ <b>ʟᴏᴋᴀꜱɪ</b>      : Singapore 🇸🇬
├ 📡 <b>ɪꜱᴘ</b>         : UpCloud Ltd
└ 🔒 <b>ᴇɴᴋʀɪᴘꜱɪ</b>   : Curve25519 + ChaCha20

┌〔 🔌 <b>ᴋᴏɴᴇᴋꜱɪ</b> 〕
└ 🛡 <b>ᴜᴅᴘ ᴘᴏʀᴛ</b>    : 51820

┌〔 📄 <b>ᴄʟɪᴇɴᴛ ᴄᴏɴꜰɪɢ (.ᴄᴏɴꜰ)</b> 〕
<pre>{client_conf}</pre>

━━━━━━━━━━━━━━━━━━━━━━

🎉 <b>ᴀᴄᴄᴏᴜɴᴛ ʙᴇʀʜᴀꜱɪʟ ᴅɪʙᴜᴀᴛ</b>
🤝 <i>Terima kasih telah menggunakan layanan kami.</i>"""

# ================= PROVISIONING ENGINE =================
def execute_system_create(proto, user, password, days=30, ip_limit=2, quota="100 GB", user_id=0, exp_override=None, user_name=""):
    now = datetime.datetime.now()
    if exp_override:
        exp_str = exp_override
    else:
        exp_dt = now + datetime.timedelta(days=int(days))
        exp_str = exp_dt.strftime("%d/%m/%Y %H:%M WIB")
    
    uid_str = str(uuid.uuid4())
    config_link = ""

    # Validate username before any system command
    if not valid_username(user):
        print(f"Invalid username rejected: {user}")
        return "", exp_str, ""

    if proto == "ssh":
        try:
            exp_date = (datetime.datetime.now() + datetime.timedelta(days=int(days))).strftime("%Y-%m-%d")
            subprocess.run(["useradd", "-e", exp_date, "-s", "/bin/false", "-M", user], check=True)
            subprocess.run(["chpasswd"], input=f"{user}:{password}\n", text=True, check=True)
        except Exception as e:
            print("SSH useradd error:", e)
        uid_str = password

    elif proto in ["vless", "vmess", "trojan"]:
        try:
            with open("/usr/local/etc/xray/config.json", "r") as f:
                cfg = json.load(f)
            
            tag_map = {"vless": "vless-ws-inbound", "vmess": "vmess-ws-inbound", "trojan": "trojan-ws-inbound"}
            inbound_tag = tag_map.get(proto)
            
            for inb in cfg.get("inbounds", []):
                if inb.get("tag") == inbound_tag:
                    clients = inb.get("settings", {}).get("clients", [])
                    if proto == "trojan":
                        clients.append({"password": uid_str, "email": user})
                    else:
                        clients.append({"id": uid_str, "email": user, "alterId": 0})
            
            with open("/usr/local/etc/xray/config.json", "w") as f:
                json.dump(cfg, f, indent=2)
            subprocess.run(["systemctl", "restart", "xray"])
        except Exception as e:
            print("Xray add error:", e)

    elif proto == "zivpn":
        try:
            os.makedirs("/etc/zivpn", exist_ok=True)
            with open("/etc/zivpn/users.db", "a") as f:
                f.write(f"{user}:{password}\n")
            subprocess.run(["systemctl", "restart", "zivpn"])
        except Exception as e:
            print("ZiVPN add error:", e)
        uid_str = password

    elif proto == "wg":
        try:
            res = subprocess.run(["python3", "/usr/local/bin/manage_wg.py", "add", user], capture_output=True, text=True)
            config_link = res.stdout.strip()
        except Exception as e:
            print("Wireguard add error:", e)
        uid_str = user

    # Save to SQLite
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""INSERT OR REPLACE INTO accounts 
        (user_id, username, protocol, uuid_or_pass, exp_date, password, days, quota_gb, ip_limit, uuid, config_link, used_bytes, used_gb)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0.0)""",
        (user_id, user, proto, uid_str, exp_str, password, days, quota, ip_limit, uid_str, config_link))
    conn.commit()
    conn.close()

    # Natural Telegram Notification
    buyer_tag = f"@{user_name}" if user_name else f"ID {user_id}"
    notif_card = (
        f"⚡ <b>AKUN BARU BERHASIL DIBUAT</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Pembeli</b>  : {buyer_tag} (<code>{user_id}</code>)\n"
        f"🔑 <b>Akun</b>     : <code>{user}</code>\n"
        f"🔌 <b>Protokol</b> : <b>{proto.upper()}</b>\n"
        f"⏳ <b>Durasi</b>   : {days} Hari\n"
        f"📦 <b>Kuota</b>    : {quota}\n"
        f"🌐 <b>Limit IP</b> : {ip_limit} IP\n"
        f"📅 <b>Expired</b>  : <code>{exp_str}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )
    send_telegram_notif(notif_card)

    return uid_str, exp_str, config_link

# ================= UI HANDLERS =================

def format_all_in_one_account(user, ssh_password, xray_uuid, exp_str, ip_limit="2 IP", quota="100 GB"):
    domain_val = get_setting("domain", DOMAIN)
    admin_tag = get_setting("admin_user", ADMIN_USER)

    vless_ws = f"vless://{xray_uuid}@{domain_val}:443?path=%2Fvless&security=tls&encryption=none&type=ws&sni={domain_val}#{user}-VLESS"
    vless_grpc = f"vless://{xray_uuid}@{domain_val}:443?mode=gun&security=tls&encryption=none&type=grpc&serviceName=vless-grpc&sni={domain_val}#{user}-gRPC"
    
    import base64
    raw_vmess = {"v": "2", "ps": f"{user}-VMESS", "add": domain_val, "port": "443", "id": xray_uuid, "aid": "0", "scy": "auto", "net": "ws", "type": "none", "host": domain_val, "path": "/vmess", "tls": "tls", "sni": domain_val}
    vmess_ws = f"vmess://{base64.b64encode(json.dumps(raw_vmess).encode()).decode()}"
    
    trojan_ws = f"trojan://{xray_uuid}@{domain_val}:443?path=%2Ftrojan-ws&security=tls&type=ws&sni={domain_val}#{user}-TROJAN"
    trojan_grpc = f"trojan://{xray_uuid}@{domain_val}:443?mode=gun&security=tls&type=grpc&serviceName=trojan-grpc&sni={domain_val}#{user}-Trojan-gRPC"

    return f"""╭━━━━━━━━━━━━━━━━━━━━━━━━━━━━╮
  🌟 <b>ᴀʟʟ-ɪɴ-ᴏɴᴇ ᴠɪᴘ ᴀᴄᴄᴏᴜɴᴛ</b> 🌟
╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯

┌〔 👤 <b>ɪɴꜰᴏʀᴍᴀꜱɪ ᴀᴋᴜɴ ᴍᴀꜱᴛᴇʀ</b> 〕
├ 👤 <b>ᴜꜱᴇʀɴᴀᴍᴇ</b>  : <code>{user}</code>
├ 🔑 <b>ꜱꜱʜ ᴘᴀꜱꜱ</b>  : <code>{ssh_password}</code>
├ 🔐 <b>xʀᴀʏ ᴜᴜɪᴅ</b> : <code>{xray_uuid}</code>
├ 📅 <b>ᴇxᴘɪʀᴇᴅ</b>   : <code>{exp_str}</code>
├ 🌐 <b>ɪᴘ ʟɪᴍɪᴛ</b>  : {ip_limit}
├ 📦 <b>ǫᴜᴏᴛᴀ</b>     : {quota}
└ 🟢 <b>ꜱᴛᴀᴛᴜꜱ</b>    : <code>ACTIVE (ALL PROTOCOLS)</code>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🌍 <b>ꜱᴇʀᴠᴇʀ:</b> <code>{domain_val}</code> (UpCloud Singapore 🇸🇬)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🚀 <b>1. ꜱꜱʜ ᴡꜱ & ᴏᴘᴇɴꜱꜱʜ</b>
├ 🔌 <b>Port TLS/WS</b>: <code>443</code> (/ssh-ws) | <b>OpenSSH</b>: <code>80, 22</code> | <b>Dropbear</b>: <code>109, 110</code>
├ 🎮 <b>BadVPN UDP</b>: <code>7100-7900</code>
├ 📱 <b>HTTP Custom:</b>
<code>{domain_val}:80@{user}:{ssh_password}</code>
└ 📄 <b>Payload WS SSL:</b>
<code>GET /ssh-ws HTTP/1.1[crlf]Host: {domain_val}[crlf]Upgrade: websocket[crlf][crlf]</code>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚡ <b>2. ᴠʟᴇꜱꜱ ᴛʟꜱ (ᴡꜱ & ɢʀᴘᴄ)</b>
├ 📡 <b>VLESS WS:</b>
<code>{vless_ws}</code>
└ ⚡ <b>VLESS gRPC:</b>
<code>{vless_grpc}</code>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🛡️ <b>3. ᴠᴍᴇꜱꜱ ᴛʟꜱ (ᴡꜱ)</b>
└ 📡 <b>VMESS WS:</b>
<code>{vmess_ws}</code>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔮 <b>4. ᴛʀᴏᴊᴀɴ ᴛʟꜱ (ᴡꜱ & ɢʀᴘᴄ)</b>
├ 📡 <b>Trojan WS:</b>
<code>{trojan_ws}</code>
└ ⚡ <b>Trojan gRPC:</b>
<code>{trojan_grpc}</code>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
👑 <b>Admin:</b> {admin_tag} | 🛒 <b>Bot:</b> @vpnshirobot"""

def get_maintenance_card():
    domain_val = get_setting("domain", DOMAIN)
    admin_tag = get_setting("admin_user", ADMIN_USER)
    return f"""╭━━━━━━━━━━━━━━━━━━━━━━╮
  ⛔ <b>ꜱᴇʀᴠᴇʀ ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ</b> ⛔
╰━━━━━━━━━━━━━━━━━━━━━━╯

┌〔 ⚠️ <b>ᴘᴇᴍᴇʟɪʜᴀʀᴀᴀɴ ꜱɪꜱᴛᴇᴍ</b> 〕
├ 🛠️ <b>ꜱᴛᴀᴛᴜꜱ</b>   : Sedang Dalam Pemeliharaan
├ 🌐 <b>ꜱᴇʀᴠᴇʀ</b>   : <code>{domain_val}</code>
├ ⏱️ <b>ᴇꜱᴛɪᴍᴀꜱɪ</b> : Segera Kembali Normal
└────────────────────────

💡 <b>Informasi Penting:</b>
• Layanan pembuatan & trial akun baru sementara dinonaktifkan.
• Akun VPN yang sudah aktif tetap dapat digunakan seperti biasa.
• Hubungi Admin untuk info lebih lanjut: {admin_tag}

🤝 <i>Mohon maaf atas ketidaknyamanan ini.</i>"""

# /start Dashboard with Slot Machine Reveal Loader
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["admin_typing_mode"] = ""
    context.user_data.pop("renew_acc_id", None)
    u = update.effective_user
    user_data = get_user(u.id, u.username)
    st = get_server_stats()

    # Send Notification to Telegram Forum/Group on user /start (first-time or restart)
    if not update.callback_query and not (context.args and len(context.args) > 0):
        u_name_tag = f"@{u.username}" if u.username else f"ID {u.id}"
        send_telegram_notif(
            f"🚀 <b>PENGGUNA MEMBUKA BOT (/start)</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Pengguna</b> : {u_name_tag} (<code>{u.id}</code>)\n"
            f"🏷️ <b>Nama</b>     : <b>{u.first_name or 'User'}</b>\n"
            f"💰 <b>Saldo</b>    : Rp {user_data['balance']:,}\n"
            f"🕒 <b>Waktu</b>    : {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S WIB')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )

    # Handle deep-link arguments (e.g. /start renew_12 or /start acc_12)
    if context.args and len(context.args) > 0:
        arg = context.args[0]
        if arg.startswith("renew_") or arg.startswith("acc_"):
            try:
                aid = int(arg.replace("renew_", "").replace("acc_", ""))
                context.user_data["temp_acc_id"] = aid
                if update.message:
                    conn = sqlite3.connect(DB_PATH)
                    c = conn.cursor()
                    c.execute("SELECT username, protocol, uuid_or_pass, exp_date, password, ip_limit, quota_gb, config_link, auto_renew FROM accounts WHERE id=?", (aid,))
                    row = c.fetchone()
                    conn.close()
                    if row:
                        uname, proto, uid_p, exp_s, pwd, ip_l, q_gb, cfg_l, auto_rn = row
                        if proto == "ssh": card = format_ssh_account(uname, pwd or uid_p, exp_s, ip_limit=ip_l, quota=q_gb)
                        elif proto == "zivpn": card = format_zivpn_account(uname, pwd or uid_p, exp_s, ip_limit=ip_l, quota=q_gb)
                        elif proto == "wg": card = format_wg_account(uname, exp_s, cfg_l, ip_limit=ip_l, quota=q_gb)
                        else: card = format_xray_account(proto, uname, uid_p, exp_s, ip_limit=ip_l, quota=q_gb)
                        ar_btn_text = "⚙️ AUTO-RENEW: ON (🟢 AKTIF)" if auto_rn == 1 else "⚙️ AUTO-RENEW: OFF (⚪ NONAKTIF)"
                        kb = [
                            [InlineKeyboardButton("🔄 REFRESH STATUS / KUOTA", callback_data=f"acc_view_{aid}")],
                            [InlineKeyboardButton(ar_btn_text, callback_data=f"toggle_ar_{aid}")],
                            [InlineKeyboardButton("🔄 PERPANJANG MANUAL", callback_data=f"renew_acc_{aid}")],
                            [InlineKeyboardButton("« KEMBALI KE DAFTAR AKUN", callback_data="menu_my_accounts")]
                        ]
                        await update.message.reply_text(card, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
                        return
            except Exception: pass

    now_wib = datetime.datetime.now().strftime("%H:%M:%S WIB")
    date_wib = datetime.datetime.now().strftime("%A, %d %B %Y")
    role_label = "👑 Owner / Admin" if user_data["role"] == "owner" else "👤 Member"

    dashboard_msg = f"""╭━━━━━━━━━━━━━━━━━━━━━━╮
  ⚡ <b>ꜱʜɪʀᴏ ᴠᴘɴ ꜱᴛᴏʀᴇ ᴏꜰꜰɪᴄɪᴀʟ</b>
╰━━━━━━━━━━━━━━━━━━━━━━╯

┌〔 👤 <b>ɪɴꜰᴏʀᴍᴀꜱɪ ᴀᴋᴜɴ</b> 〕
├ 💰 <b>ꜱᴀʟᴅᴏ</b>      : <b>Rp {user_data['balance']:,}</b>
├ 👤 <b>ꜱᴛᴀᴛᴜꜱ</b>     : {role_label}
├ 🌐 <b>ᴜꜱᴇʀɴᴀᴍᴇ</b>   : @{u.username or 'User'}
└ 🆔 <b>ɪᴅ ᴜꜱᴇʀ</b>    : <code>{u.id}</code>

┌〔 🌐 <b>ɪɴꜰᴏʀᴍᴀꜱɪ ꜱᴇʀᴠᴇʀ</b> 〕
├ 🕒 <b>ᴡᴀᴋᴛᴜ</b>      : {now_wib}
├ 📅 <b>ᴛᴀɴɢɢᴀʟ</b>    : {date_wib}
├ 🖥️ <b>ꜱᴇʀᴠᴇʀ</b>     : 1 (Singapore 🇸🇬)
├ 👥 <b>ᴛᴏᴛᴀʟ ᴜꜱᴇʀ</b> : {st['total_users']} User
└ ⏱️ <b>ʙᴏᴛ ᴀᴋᴛɪꜰ</b>  : {st['uptime']}

┌〔 ☎️ <b>ʜᴜʙᴜɴɢɪ ᴀᴅᴍɪɴ</b> 〕
└ 📨 {get_setting('admin_user', ADMIN_USER)}

━━━━━━━━━━━━━━━━━━━━━━
🤖 <i>Dikelola oleh Shiro VPN Network</i>"""

    # Balanced, Clean Button Layout
    kb = [
        [InlineKeyboardButton("⚡ BELI AKUN", callback_data="menu_buy"), InlineKeyboardButton("🎁 TRIAL GRATIS", callback_data="menu_trial")],
        [InlineKeyboardButton("📦 AKUN SAYA", callback_data="menu_my_accounts"), InlineKeyboardButton("💳 TOP UP SALDO", callback_data="menu_topup")],
        [InlineKeyboardButton("📖 BANTUAN & TUTORIAL", callback_data="menu_help")]
    ]
    if u.id == ADMIN_ID:
        kb.append([InlineKeyboardButton("⚙️ PANEL ADMIN", callback_data="menu_admin"), InlineKeyboardButton("🌐 STATUS SERVER", callback_data="menu_server_status")])

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(dashboard_msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    else:
        await update.message.reply_text(dashboard_msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def buy_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    u = update.effective_user
    admin_id_val = int(get_setting("admin_id", str(ADMIN_ID)))

    # Check Maintenance Mode
    if get_setting("maintenance_mode", "0") == "1" and u.id != admin_id_val:
        kb = [[InlineKeyboardButton("« KEMBALI KE MENU", callback_data="menu_start")]]
        await query.edit_message_text(get_maintenance_card(), reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        return ConversationHandler.END

    p_price = get_setting("price_per_day", "100")
    
    msg = f"""┌〔 🛒 <b>PILIH PROTOKOL VPN</b> 〕
├ 💰 <b>Tarif</b> : Rp {p_price} / hari
├ 🌍 <b>Server</b>: Singapore 🇸🇬
└────────────────────────

Pilih protokol VPN yang ingin Anda buat:"""

    kb = [
        [InlineKeyboardButton("🚀 SSH", callback_data="proto_ssh"), InlineKeyboardButton("⚡ VLESS", callback_data="proto_vless")],
        [InlineKeyboardButton("🛡️ VMESS", callback_data="proto_vmess"), InlineKeyboardButton("🔮 TROJAN", callback_data="proto_trojan")],
        [InlineKeyboardButton("🎮 ZIVPN", callback_data="proto_zivpn"), InlineKeyboardButton("🛡️ WIREGUARD", callback_data="proto_wg")],
        [InlineKeyboardButton("« KEMBALI", callback_data="menu_start")]
    ]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    return BUY_PROTO

async def buy_select_proto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    proto = query.data.replace("proto_", "")
    context.user_data["buy_proto"] = proto

    p_price = int(get_setting("price_per_day", "100"))
    ip_limit = int(get_setting("default_ip_limit", "2"))
    quota = get_setting("default_quota", "100 GB")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM accounts WHERE protocol=?", (proto,))
    active_count = c.fetchone()[0]
    conn.close()

    p_name = proto.upper()
    msg = f"""🛒 <b>BUAT AKUN {p_name}</b>

╭━━━━━━━━━━━━━━━━━━━━━━╮
  🌐 <b>ꜱɢ1 ꜱʜɪʀᴏ — {SERVER_INFO['country_name'].upper()}</b>
╰━━━━━━━━━━━━━━━━━━━━━━╯
├ 🌐 <b>ᴅᴏᴍᴀɪɴ</b>     : <code>{DOMAIN}</code>
├ 📡 <b>ɪꜱᴘ</b>        : {SERVER_INFO['isp']}
├ 💳 <b>ᴛᴀʀɪꜰ</b>      : Rp {p_price:,} / hari
├ 🔐 <b>ʟɪᴍɪᴛ ɪᴘ</b>   : {ip_limit} Device
├ 📦 <b>ǫᴜᴏᴛᴀ</b>      : {quota}
├ 👥 <b>ᴀᴋᴛɪꜰ</b>      : {active_count} User
└ 📌 <b>ꜱᴛᴀᴛᴜꜱ</b>     : 🟢 <code>TERSEDIA</code>

━━━━━━━━━━━━━━━━━━━━━━
<i>Pilih server {p_name}:</i>"""

    kb = [
        [InlineKeyboardButton("🇸🇬 SG1 SHIRO", callback_data="srv_sg1")],
        [InlineKeyboardButton("« KEMBALI", callback_data="menu_buy")]
    ]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    return BUY_SERVER

async def buy_select_server(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    proto = context.user_data.get("buy_proto", "ssh")

    msg = f"""┌〔 👤 <b>INPUT USERNAME AKUN</b> 〕
├ 🔌 <b>Protokol</b> : <b>{proto.upper()}</b>
├ 🖥️ <b>Server</b>   : SG1 SHIRO 🇸🇬
└────────────────────────

Silakan ketik <b>Username</b> yang Anda inginkan (huruf/angka tanpa spasi):"""

    kb = [[InlineKeyboardButton("❌ BATAL", callback_data="cancel_conv")]]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    return BUY_USER

async def buy_input_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.text.strip().replace(" ", "").lower()
    if not valid_username(user) or len(user) > 32:
        await update.message.reply_text(
            "⚠️ <b>Username tidak valid!</b>\n\nGunakan huruf kecil, angka, underscore, atau dash saja (maks 32 karakter).",
            parse_mode="HTML"
        )
        return BUY_USER
    context.user_data["buy_user"] = user
    proto = context.user_data.get("buy_proto", "ssh")

    if proto in ["vless", "vmess", "trojan", "wg"]:
        # Auto generate key
        context.user_data["buy_pass"] = str(uuid.uuid4())
        msg = f"""┌〔 📅 <b>MASA AKTIF AKUN</b> 〕
├ 👤 <b>Username</b> : <code>{user}</code>
├ 🔌 <b>Protokol</b> : <b>{proto.upper()}</b>
└────────────────────────

Ketik <b>Jumlah Hari</b> aktif yang diinginkan (Contoh: <code>30</code>):"""
        kb = [[InlineKeyboardButton("❌ BATAL", callback_data="cancel_conv")]]
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        return BUY_DAYS
    else:
        msg = f"""┌〔 🔑 <b>INPUT PASSWORD AKUN</b> 〕
├ 👤 <b>Username</b> : <code>{user}</code>
├ 🔌 <b>Protokol</b> : <b>{proto.upper()}</b>
└────────────────────────

Silakan ketik <b>Password</b> untuk akun Anda:"""
        kb = [[InlineKeyboardButton("❌ BATAL", callback_data="cancel_conv")]]
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        return BUY_PASS

async def buy_input_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["buy_pass"] = update.message.text.strip()
    user = context.user_data.get("buy_user", "")
    proto = context.user_data.get("buy_proto", "")

    msg = f"""┌〔 📅 <b>MASA AKTIF AKUN</b> 〕
├ 👤 <b>Username</b> : <code>{user}</code>
├ 🔌 <b>Protokol</b> : <b>{proto.upper()}</b>
└────────────────────────

Ketik <b>Jumlah Hari</b> aktif yang diinginkan (Contoh: <code>30</code>):"""
    kb = [[InlineKeyboardButton("❌ BATAL", callback_data="cancel_conv")]]
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    return BUY_DAYS

async def buy_input_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        days = int(re.search(r'\d+', text).group(0))
    except Exception:
        days = 30
    
    context.user_data["buy_days"] = days
    u_id = update.effective_user.id
    
    # If Admin, allow custom IP & Quota override
    if u_id == ADMIN_ID:
        msg = f"""┌〔 👑 <b>[ADMIN] ATUR LIMIT MULTI-IP</b> 〕
├ 📅 <b>Durasi</b> : {days} Hari
└────────────────────────

Ketik batas <b>Jumlah IP</b> (Contoh: <code>2</code> atau <code>5</code>):"""
        kb = [[InlineKeyboardButton("❌ BATAL", callback_data="cancel_conv")]]
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        return BUY_LIMIT
    
    # Regular Member Checkout - use admin-set defaults
    ip_limit = int(get_setting("default_ip_limit", "2"))
    quota = get_setting("default_quota", "100 GB")
    return await finish_buy_flow(update, context, ip_limit=ip_limit, quota=quota)

async def buy_admin_input_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        ip_limit = int(re.search(r'\d+', update.message.text.strip()).group(0))
    except Exception:
        ip_limit = 2
    context.user_data["buy_limit"] = ip_limit

    msg = f"""┌〔 👑 <b>[ADMIN] ATUR BATAS DATA QUOTA</b> 〕
├ 🌐 <b>Limit IP</b> : {ip_limit} IP
└────────────────────────

Ketik batas <b>Quota Data</b> (Contoh: <code>100 GB</code>, <code>200 GB</code>, <code>Unlimited</code>):"""
    kb = [[InlineKeyboardButton("❌ BATAL", callback_data="cancel_conv")]]
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    return BUY_QUOTA

async def buy_admin_input_quota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    quota_str = update.message.text.strip()
    if not quota_str: quota_str = "100 GB"
    context.user_data["buy_quota"] = quota_str
    
    ip_limit = context.user_data.get("buy_limit", 2)
    return await finish_buy_flow(update, context, ip_limit=ip_limit, quota=quota_str)

async def finish_buy_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, ip_limit=2, quota="100 GB"):
    u = update.effective_user
    proto = context.user_data.get("buy_proto", "ssh")
    user = context.user_data.get("buy_user", f"user_{int(time.time())}")
    password = context.user_data.get("buy_pass", "pass123")
    days = context.user_data.get("buy_days", 30)

    # Balance check for members
    price_per_day = int(get_setting("price_per_day", "100"))
    total_cost = days * price_per_day
    
    if u.id != ADMIN_ID:
        user_info = get_user(u.id, u.username)
        if user_info["balance"] < total_cost:
            await update.message.reply_text(
                f"❌ <b>Saldo Tidak Mencukupi!</b>\n\n"
                f"Total Biaya: <b>Rp {total_cost:,}</b>\n"
                f"Saldo Anda : <b>Rp {user_info['balance']:,}</b>\n\n"
                f"Silakan Top Up saldo terlebih dahulu melalui menu <b>[TOP UP SALDO]</b>.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« KEMBALI KE MENU", callback_data="menu_start")]]),
                parse_mode="HTML"
            )
            return ConversationHandler.END
        # Deduct balance
        update_user_balance(u.id, -total_cost)

    # Progress Animation in Chat
    load_msg = await update.message.reply_text("⏳ <code>[■□□□□□□□□□] 10% Menghubungkan ke Core Engine...</code>", parse_mode="HTML")
    await asyncio.sleep(0.4)
    await load_msg.edit_text("⚡ <code>[■■■■□□□□□□] 40% Mendaftarkan Kredensial & Kunci Enkripsi...</code>", parse_mode="HTML")
    await asyncio.sleep(0.4)
    await load_msg.edit_text("🛡 <code>[■■■■■■■□□□] 70% Menerapkan Limit IP, Quota & Multiplexer...</code>", parse_mode="HTML")
    await asyncio.sleep(0.4)
    await load_msg.edit_text("✨ <code>[■■■■■■■■■■] 100% Mengenerate Format Konfigurasi...</code>", parse_mode="HTML")
    await asyncio.sleep(0.3)

    # Execute system provisioning
    uid_res, exp_str, conf_link = execute_system_create(proto, user, password, days=days, ip_limit=ip_limit, quota=quota, user_id=u.id, user_name=u.username or u.first_name)

    # Format result
    if proto == "ssh":
        card = format_ssh_account(user, password, exp_str, ip_limit=ip_limit, quota=quota)
    elif proto in ["vless", "vmess", "trojan"]:
        card = format_xray_account(proto, user, uid_res, exp_str, ip_limit=ip_limit, quota=quota)
    elif proto == "zivpn":
        card = format_zivpn_account(user, password, exp_str, ip_limit=ip_limit, quota=quota)
    elif proto == "wg":
        card = format_wg_account(user, exp_str, client_conf=conf_link, ip_limit=ip_limit, quota=quota)

    kb = [[InlineKeyboardButton("« KEMBALI KE MENU", callback_data="menu_start")]]
    await load_msg.edit_text(card, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    return ConversationHandler.END

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("❌ <b>Operasi Dibatalkan.</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« KEMBALI KE MENU", callback_data="menu_start")]]), parse_mode="HTML")
    else:
        await update.message.reply_text("❌ <b>Operasi Dibatalkan.</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« KEMBALI KE MENU", callback_data="menu_start")]]), parse_mode="HTML")
    return ConversationHandler.END

# Free Trial Flow
async def trial_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    u = update.effective_user
    admin_id_val = int(get_setting("admin_id", str(ADMIN_ID)))

    # Check Maintenance Mode
    if get_setting("maintenance_mode", "0") == "1" and u.id != admin_id_val:
        kb = [[InlineKeyboardButton("« KEMBALI KE MENU", callback_data="menu_start")]]
        await query.edit_message_text(get_maintenance_card(), reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        return
    
    msg = """┌〔 🎁 <b>COBA GRATIS / TRIAL (30 MENIT)</b> 〕
├ ⏱️ <b>Durasi</b>   : 30 Menit (Auto-Purge)
├ 📦 <b>Kuota</b>    : 1 GB
├ 🌐 <b>Multi-IP</b> : 1 Device
└────────────────────────

Pilih protokol trial yang ingin dicoba:"""

    kb = [
        [InlineKeyboardButton("🚀 SSH", callback_data="trial_ssh"), InlineKeyboardButton("⚡ VLESS", callback_data="trial_vless")],
        [InlineKeyboardButton("🛡️ VMESS", callback_data="trial_vmess"), InlineKeyboardButton("🔮 TROJAN", callback_data="trial_trojan")],
        [InlineKeyboardButton("🎮 ZIVPN", callback_data="trial_zivpn"), InlineKeyboardButton("🛡️ WIREGUARD", callback_data="trial_wg")],
        [InlineKeyboardButton("« KEMBALI", callback_data="menu_start")]
    ]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def execute_trial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    proto = query.data.replace("trial_", "")
    u = update.effective_user

    # Cek apakah user sudah pernah mengambil trial hari ini (1x per hari)
    today_start = datetime.datetime.now().strftime("%Y-%m-%d 00:00:00")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM trial_logs WHERE user_id=? AND created_at >= ?", (u.id, today_start))
    trial_count = c.fetchone()[0]
    conn.close()

    admin_id_val = int(get_setting("admin_id", str(ADMIN_ID)))
    if trial_count > 0 and u.id != admin_id_val:
        await query.edit_message_text(
            "⚠️ <b>JATAH TRIAL HARI INI HABIS</b>\n\n"
            "Anda sudah menggunakan kuota trial gratis untuk hari ini (Maksimal 1x per hari).\n"
            "Silakan coba lagi besok, atau beli akun resmi melalui menu <b>[BELI AKUN]</b>.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚡ BELI AKUN RESMI", callback_data="menu_buy")],
                [InlineKeyboardButton("« KEMBALI KE MENU", callback_data="menu_start")]
            ]),
            parse_mode="HTML"
        )
        return

    # Generate nama akun trial bersih (hanya huruf kecil, tanpa underscore)
    clean_code = "".join(random.choices(string.ascii_lowercase, k=6))
    clean_pass = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    t_id = f"tr{clean_code}"
    t_pass = f"p{clean_pass}"

    load_msg = await query.edit_message_text("⏳ <code>[▱▱▱▱▱▱▱▱▱▱] 10% Menghubungkan ke Core Engine...</code>", parse_mode="HTML")
    await asyncio.sleep(0.3)
    await load_msg.edit_text("⚡ <code>[▰▰▰▰▰▰▱▱▱▱] 60% Menyiapkan Akun Trial 30 Menit...</code>", parse_mode="HTML")
    await asyncio.sleep(0.3)
    await load_msg.edit_text("✨ <code>[▰▰▰▰▰▰▰▰▰▰] 100% Selesai!</code>", parse_mode="HTML")

    # 30 mins expiry
    now = datetime.datetime.now()
    exp_dt = now + datetime.timedelta(minutes=30)
    exp_str = f"30 Menit ({exp_dt.strftime('%H:%M')} WIB)"
    
    uid_res, exp_s, conf_link = execute_system_create(proto, t_id, t_pass, days=1, ip_limit=1, quota="1 GB", user_id=u.id, exp_override=exp_str, user_name=u.username or u.first_name)

    # Catat log trial
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO trial_logs (user_id, protocol) VALUES (?, ?)", (u.id, proto))
        conn.commit()
        conn.close()
    except Exception:
        pass

    if proto == "ssh":
        card = format_ssh_account(t_id, t_pass, exp_str, ip_limit=1, quota="1 GB")
    elif proto in ["vless", "vmess", "trojan"]:
        card = format_xray_account(proto, t_id, uid_res, exp_str, ip_limit=1, quota="1 GB")
    elif proto == "zivpn":
        card = format_zivpn_account(t_id, t_pass, exp_str, ip_limit=1, quota="1 GB")
    elif proto == "wg":
        card = format_wg_account(t_id, exp_str, client_conf=conf_link, ip_limit=1, quota="1 GB")

    kb = [[InlineKeyboardButton("« KEMBALI KE MENU", callback_data="menu_start")]]
    await load_msg.edit_text(card, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

# My Accounts List
async def my_accounts_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    u = update.effective_user

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username, protocol, exp_date, ip_limit, quota_gb FROM accounts WHERE user_id=? ORDER BY id DESC LIMIT 10", (u.id,))
    rows = c.fetchall()
    conn.close()

    if not rows:
        msg = "📦 <b>Anda belum memiliki akun VPN aktif.</b>"
        kb = [
            [InlineKeyboardButton("⚡ BUAT AKUN SEKARANG", callback_data="menu_buy")],
            [InlineKeyboardButton("« KEMBALI", callback_data="menu_start")]
        ]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        return

    msg = "📦 <b>DAFTAR AKUN VPN TERDAFTAR:</b>\n<i>Klik salah satu akun untuk melihat detail atau sisa kuota:</i>\n\n"
    kb = []
    for r in rows:
        aid, uname, proto, exp, ip_l, q_gb = r
        q_ratio = get_account_quota_info(uname)[2]
        btn_text = f"• {uname} ({proto.upper()}) | Quota: {q_ratio}"
        kb.append([InlineKeyboardButton(btn_text, callback_data=f"acc_view_{aid}")])

    kb.append([InlineKeyboardButton("« KEMBALI", callback_data="menu_start")])
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def toggle_auto_renew_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        acc_id = int(query.data.replace("toggle_ar_", ""))
    except (ValueError, AttributeError):
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT auto_renew, username FROM accounts WHERE id=?", (acc_id,))
    row = c.fetchone()
    if row:
        new_val = 0 if row[0] == 1 else 1
        c.execute("UPDATE accounts SET auto_renew=? WHERE id=?", (new_val, acc_id))
        conn.commit()
    conn.close()

    # Refresh the account detail view directly
    context.user_data["temp_acc_id"] = acc_id
    query.data = f"acc_view_{acc_id}"
    await account_detail_menu(update, context)

# View Account Detail
async def account_detail_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        acc_id = int(query.data.replace("acc_view_", ""))
    except (ValueError, AttributeError):
        await query.edit_message_text("❌ Data tidak valid.", parse_mode="HTML")
        return
    u_id = update.effective_user.id
    admin_id_val = int(get_setting("admin_id", str(ADMIN_ID)))

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if u_id == admin_id_val:
        c.execute("SELECT username, protocol, uuid_or_pass, exp_date, password, ip_limit, quota_gb, config_link, auto_renew FROM accounts WHERE id=?", (acc_id,))
    else:
        c.execute("SELECT username, protocol, uuid_or_pass, exp_date, password, ip_limit, quota_gb, config_link, auto_renew FROM accounts WHERE id=? AND user_id=?", (acc_id, u_id))
    row = c.fetchone()
    conn.close()

    if not row:
        await query.edit_message_text("❌ Akun tidak ditemukan.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« KEMBALI", callback_data="menu_my_accounts")]]), parse_mode="HTML")
        return

    uname, proto, uid_p, exp_s, pwd, ip_l, q_gb, conf_link, auto_rn = row
    
    if proto == "ssh":
        card = format_ssh_account(uname, pwd or uid_p, exp_s, ip_limit=ip_l, quota=q_gb)
    elif proto in ["vless", "vmess", "trojan"]:
        card = format_xray_account(proto, uname, uid_p, exp_s, ip_limit=ip_l, quota=q_gb)
    elif proto == "zivpn":
        card = format_zivpn_account(uname, pwd or uid_p, exp_s, ip_limit=ip_l, quota=q_gb)
    elif proto == "wg":
        card = format_wg_account(uname, exp_s, client_conf=conf_link, ip_limit=ip_l, quota=q_gb)

    ar_badge = "🟢 AKTIF" if auto_rn else "⚪ NONAKTIF"
    ar_toggle_text = "⚙️ AUTO-RENEW: ON" if auto_rn else "⚙️ AUTO-RENEW: OFF"

    kb = [
        [InlineKeyboardButton("🔄 REFRESH STATUS / KUOTA", callback_data=f"acc_view_{acc_id}")],
        [InlineKeyboardButton(f"{ar_toggle_text} ({ar_badge})", callback_data=f"toggle_ar_{acc_id}")],
        [InlineKeyboardButton("🔄 PERPANJANG MANUAL", callback_data=f"renew_acc_{acc_id}")],
        [InlineKeyboardButton("« KEMBALI KE DAFTAR AKUN", callback_data="menu_my_accounts")]
    ]
    await query.edit_message_text(card, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

# Top Up Info
async def topup_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    msg = f"""┌〔 💳 <b>TOP UP SALDO OTOMATIS / MANUAL</b> 〕
├ 👑 <b>Admin Deposit</b> : {get_setting('admin_user', ADMIN_USER)}
├ 🆔 <b>ID Anda</b>        : <code>{update.effective_user.id}</code>
└────────────────────────

Untuk melakukan pengisian saldo (Top Up), silakan hubungi Admin Master melalui tautan di bawah:

👉 Hubungi: {get_setting('admin_user', ADMIN_USER)}
Sertakan ID Pengguna Anda saat konfirmasi pembayaran."""

    kb = [
        [InlineKeyboardButton("💬 CHAT ADMIN SEKARANG", url=f"https://t.me/{get_setting('admin_user', ADMIN_USER).replace('@', '')}")],
        [InlineKeyboardButton("« KEMBALI", callback_data="menu_start")]
    ]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

# Help & Tutorial
async def help_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    msg = f"""┌〔 📖 <b>PANDUAN & CARA PENGGUNAAN</b> 〕
├ 🌐 <b>Domain Server</b> : <code>{DOMAIN}</code>
├ 🔐 <b>TLS Port</b>      : 443
└────────────────────────

📱 <b>Aplikasi yang Didukung:</b>
• <b>Android:</b> HTTP Custom, v2rayNG, NetMod, OpenTunnel, ZiVPN, WireGuard
• <b>iOS:</b> Streisand, V2Box, Shadowrocket, WireGuard
• <b>Windows:</b> NetMod Syna, v2rayN, WireGuard Client

💡 <b>Cara Import Akun:</b>
1. Buat akun di menu <b>[BUAT AKUN]</b>.
2. Salin config / URL link (VLESS / VMESS / TROJAN / WIREGUARD).
3. Buka aplikasi VPN Anda -> <b>Import Config from Clipboard</b>.
4. Klik tombol <b>Connect</b>.

Hubungi admin jika mengalami kendala: {get_setting('admin_user', ADMIN_USER)}"""
    kb = [[InlineKeyboardButton("« KEMBALI", callback_data="menu_start")]]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

# Server Status (Admin Only)
async def server_status_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    u = update.effective_user
    if u.id != ADMIN_ID:
        await query.answer("🔒 AKSES KHUSUS ADMIN MASTER!", show_alert=True)
        return

    st = get_server_stats()
    now_time = datetime.datetime.now().strftime("%H:%M:%S")
    msg = f"""┌〔 🌐 <b>STATUS TELEMETRI SERVER</b> 〕
├ 🌍 <b>Domain</b>   : {DOMAIN}
├ ⏱️ <b>Uptime</b>   : {st['uptime']}
├ 🕒 <b>Waktu</b>    : {now_time} WIB
└────────────────────────

┌〔 ⚙️ <b>ENGINE TUNNELING DAEMONS</b> 〕
├ ⚡ <b>Xray Core TLS (443)</b> : 🟢 RUNNING
├ 🌐 <b>OpenSSH Server (80)</b> : 🟢 RUNNING
├ 📡 <b>Dropbear SSH (109)</b>  : 🟢 RUNNING
├ 🔄 <b>WS-SSH Proxy SSL</b>    : 🟢 RUNNING
├ 🎮 <b>UDP ZiVPN Engine</b>    : 🟢 RUNNING
├ 🛡️ <b>WireGuard Kernel</b>     : 🟢 RUNNING
├ 🤖 <b>Shiro Bot Daemon</b>    : 🟢 RUNNING
└ 🛡️ <b>Auto Guard Service</b>  : 🟢 RUNNING

┌〔 📊 <b>DATABASE METRICS</b> 〕
├ 👥 <b>Total Member Bot</b>    : {st['total_users']} User
└ 📦 <b>Total Akun Aktif</b>    : {st['total_acc']} Akun"""

    kb = [[InlineKeyboardButton("« KEMBALI", callback_data="menu_start")]]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

# Admin Master Panel
async def admin_topup_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != int(get_setting("admin_id", str(ADMIN_ID))): return
    context.user_data["admin_typing_mode"] = "topup_user"
    msg = """┌〔 💳 <b>TOP UP SALDO USER</b> 〕
├ 👑 Mode: Sysadmin Top-up
└────────────────────────

Ketik <b>ID Telegram User</b> yang ingin diisi saldo:"""
    kb = [[InlineKeyboardButton("« BATAL", callback_data="menu_admin")]]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def admin_broadcast_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != int(get_setting("admin_id", str(ADMIN_ID))): return

    msg = """┌〔 📢 <b>BROADCAST TELEGRAM</b> 〕
├ 👑 Pilih Target Penerima Broadcast:
└────────────────────────"""
    kb = [
        [InlineKeyboardButton("👥 SEMUA USER TERDAFTAR", callback_data="bc_target_all")],
        [InlineKeyboardButton("🟢 KHUSUS USER AKTIF (PUNYA AKUN)", callback_data="bc_target_active")],
        [InlineKeyboardButton("« KEMBALI KE ADMIN", callback_data="menu_admin")]
    ]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def admin_broadcast_set_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != int(get_setting("admin_id", str(ADMIN_ID))): return
    target_mode = query.data.replace("bc_target_", "") # all or active
    context.user_data["admin_typing_mode"] = f"broadcast_{target_mode}"
    
    label = "Semua User Terdaftar" if target_mode == "all" else "Khusus User yang Memiliki Akun Aktif"
    msg = f"""┌〔 📢 <b>BROADCAST TELEGRAM</b> 〕
├ 🎯 <b>Target</b> : {label}
└────────────────────────

Ketik <b>Pesan Pengumuman</b> (teks HTML didukung):"""
    kb = [[InlineKeyboardButton("« BATAL", callback_data="admin_broadcast")]]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def admin_panel_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    u = update.effective_user
    admin_id_val = int(get_setting("admin_id", str(ADMIN_ID)))
    if u.id != admin_id_val:
        await query.answer("🔒 AKSES KHUSUS ADMIN MASTER!", show_alert=True)
        return

    price = get_setting("price_per_day", "100")
    limit = get_setting("default_ip_limit", "2")
    quota = get_setting("default_quota", "100 GB")
    maint_status = get_setting("maintenance_mode", "0")
    maint_btn_text = "⛔ MAINTENANCE: ON (🔴 AKTIF)" if maint_status == "1" else "🟢 MAINTENANCE: OFF (NORMAL)"

    msg = f"""┌〔 ⚙️ <b>PANEL ADMIN MASTER PRO</b> 〕
├ 💰 <b>Tarif Harian</b>   : Rp {price} / hari
├ 👥 <b>Default Limit</b>  : {limit} IP
├ 📦 <b>Default Quota</b>  : {quota}
├ 🛠️ <b>Maintenance</b>    : {"🔴 AKTIF (Order Ditutup)" if maint_status == '1' else '🟢 NORMAL (Order Buka)'}
└────────────────────────

Pilih aksi manajemen server & bot:"""

    kb = [
        [InlineKeyboardButton("⚡ AUTO CREATE ALL-IN-ONE (VIP)", callback_data="admin_create_all_prompt")],
        [InlineKeyboardButton("🤖 BOT & SYSTEM WIZARD", callback_data="admin_wizard")],
        [InlineKeyboardButton("💰 UBAH HARGA", callback_data="admin_price"), InlineKeyboardButton("👥 SET LIMIT IP", callback_data="admin_limit")],
        [InlineKeyboardButton("📦 SET QUOTA", callback_data="admin_quota"), InlineKeyboardButton("💳 TOP UP USER", callback_data="admin_topup")],
        [InlineKeyboardButton("📜 DAFTAR SEMUA AKUN", callback_data="admin_list_accounts"), InlineKeyboardButton("📢 BROADCAST", callback_data="admin_broadcast")],
        [InlineKeyboardButton(maint_btn_text, callback_data="admin_toggle_maintenance")],
        [InlineKeyboardButton("🔄 RESTART SERVICE CORE", callback_data="admin_restart_core")],
        [InlineKeyboardButton("« KEMBALI KE MENU", callback_data="menu_start")]
    ]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def admin_create_all_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != int(get_setting("admin_id", str(ADMIN_ID))): return

    context.user_data["admin_typing_mode"] = "create_all_in_one"
    msg = """┌〔 ⚡ <b>AUTO-CREATE ALL-IN-ONE ACCOUNT</b> 〕
├ 🌟 Otomatis membuat 4 Protokol Sekaligus:
├ 🚀 <b>SSH & OpenSSH Direct</b>
├ ⚡ <b>VLESS WS & gRPC TLS</b>
├ 🛡️ <b>VMESS WS TLS</b>
├ 🔮 <b>TROJAN WS & gRPC TLS</b>
└────────────────────────

Silakan ketik <b>Username</b> untuk akun All-in-One:"""
    kb = [[InlineKeyboardButton("« BATAL", callback_data="menu_admin")]]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def admin_toggle_maintenance_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != int(get_setting("admin_id", str(ADMIN_ID))): return

    current = get_setting("maintenance_mode", "0")
    new_val = "0" if current == "1" else "1"
    set_setting("maintenance_mode", new_val)

    # Re-render admin panel
    await admin_panel_menu(update, context)

# Admin List Accounts Handler
async def admin_list_accounts_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID: return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username, protocol, exp_date, ip_limit, quota_gb FROM accounts ORDER BY id DESC LIMIT 15")
    rows = c.fetchall()
    conn.close()

    if not rows:
        await query.edit_message_text("📦 <b>Belum ada akun terdaftar di sistem.</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« KEMBALI", callback_data="menu_admin")]]), parse_mode="HTML")
        return

    msg = "📜 <b>DAFTAR SELURUH AKUN SISTEM:</b>\n\n"
    kb = []
    for r in rows:
        aid, uname, proto, exp, ip_l, q_gb = r
        q_ratio = get_account_quota_info(uname)[2]
        btn_text = f"• {uname} ({proto.upper()}) | {q_ratio}"
        kb.append([InlineKeyboardButton(btn_text, callback_data=f"acc_view_{aid}")])

    kb.append([InlineKeyboardButton("« KEMBALI KE PANEL ADMIN", callback_data="menu_admin")])
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

# Admin Restart Core
async def admin_restart_core(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID: return
    
    await query.edit_message_text("⏳ <i>Merestart seluruh engine service tunneling...</i>", parse_mode="HTML")
    subprocess.run(["systemctl", "restart", "xray", "ssh", "dropbear", "ws-dropbear", "zivpn", "wg-quick@wg0", "shiro-guard"])
    await query.edit_message_text("✅ <b>Seluruh service core tunneling berhasil direstart!</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« KEMBALI", callback_data="menu_admin")]]), parse_mode="HTML")



async def admin_bot_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID: return

    curr_token = get_setting("bot_token", BOT_TOKEN)[:15] + "..." if len(get_setting("bot_token", BOT_TOKEN)) > 15 else get_setting("bot_token", BOT_TOKEN)
    curr_owner = get_setting("admin_user", ADMIN_USER)
    curr_owner_id = get_setting("admin_id", str(ADMIN_ID))
    curr_bot_user = get_setting("bot_username", BOT_USERNAME)
    curr_domain = get_setting("domain", DOMAIN)
    curr_notif = get_setting("notif_chat_id", "-")
    curr_thread = get_setting("notif_thread_id", "-")

    msg = f"""┌〔 🤖 <b>TELEGRAM BOT & SYSTEM WIZARD</b> 〕
├────────────────────────
├ 🔑 <b>Bot Token</b>    : <code>{curr_token}</code>
├ 🤖 <b>Bot Username</b> : {curr_bot_user}
├ 👑 <b>Owner</b>        : {curr_owner} (<code>{curr_owner_id}</code>)
├ 🌐 <b>Domain</b>       : <code>{curr_domain}</code>
├ 📢 <b>Notif Chat</b>   : <code>{curr_notif}</code>
├ 💬 <b>Notif Thread</b> : <code>{curr_thread}</code>
└────────────────────────

<i>Pilih yang ingin diubah:</i>"""

    kb = [
        [InlineKeyboardButton("🔑 SET BOT TOKEN", callback_data="wiz_token")],
        [InlineKeyboardButton("👑 SET OWNER ID & USERNAME", callback_data="wiz_owner")],
        [InlineKeyboardButton("🌐 SET DOMAIN", callback_data="wiz_domain")],
        [InlineKeyboardButton("📢 SET NOTIF FORUM", callback_data="wiz_notif")],
        [InlineKeyboardButton("« KEMBALI", callback_data="menu_admin")]
    ]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def wiz_token_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID: return
    context.user_data["admin_typing_mode"] = "wiz_token"
    msg = """┌〔 🔑 <b>SET BOT TOKEN</b> 〕
└────────────────────────

Kirim <b>Bot Token</b> baru dari @BotFather:
<i>(Format: <code>123456789:ABCdef...</code>)</i>"""
    kb = [[InlineKeyboardButton("❌ BATAL", callback_data="admin_wizard")]]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def wiz_owner_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID: return
    context.user_data["admin_typing_mode"] = "wiz_owner"
    msg = """┌〔 👑 <b>SET OWNER ID & USERNAME</b> 〕
└────────────────────────

Kirim dalam format:
<code>ID_ANGKA @username</code>

Contoh: <code>1234567890 @YourTelegramUsername</code>"""
    kb = [[InlineKeyboardButton("❌ BATAL", callback_data="admin_wizard")]]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def wiz_domain_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID: return
    context.user_data["admin_typing_mode"] = "wiz_domain"
    msg = """┌〔 🌐 <b>SET DOMAIN SERVER</b> 〕
└────────────────────────

Kirim domain baru (tanpa http):
<i>Contoh: <code>your-domain.com</code></i>"""
    kb = [[InlineKeyboardButton("❌ BATAL", callback_data="admin_wizard")]]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def wiz_notif_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID: return
    context.user_data["admin_typing_mode"] = "wiz_notif"
    msg = """┌〔 📢 <b>SET FORUM NOTIFIKASI</b> 〕
└────────────────────────

Kirim link topik forum Telegram:
<i>Contoh: <code>https://t.me/c/4339591538/3</code></i>

Atau kirim Chat ID langsung:
<i>Contoh: <code>-1000000000000</code></i>"""
    kb = [[InlineKeyboardButton("❌ BATAL", callback_data="admin_wizard")]]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def admin_price_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID: return
    
    curr = get_setting("price_per_day", "100")
    msg = f"""┌〔 💰 <b>UBAH TARIF HARGA HARIAN</b> 〕
├ 💰 <b>Harga Saat Ini</b>: Rp {curr} / hari
└────────────────────────

Pilih preset atau ketik nominal manual (contoh: <code>250</code>):"""
    kb = [
        [InlineKeyboardButton("Rp 100", callback_data="set_p_100"), InlineKeyboardButton("Rp 150", callback_data="set_p_150"), InlineKeyboardButton("Rp 200", callback_data="set_p_200")],
        [InlineKeyboardButton("« KEMBALI", callback_data="menu_admin")]
    ]
    context.user_data["admin_typing_mode"] = "price"
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def admin_set_price_preset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID: return
    p_val = query.data.replace("set_p_", "")
    set_setting("price_per_day", p_val)
    await query.edit_message_text(f"✅ <b>Tarif harian berhasil diubah menjadi Rp {p_val} / hari.</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« KEMBALI", callback_data="menu_admin")]]), parse_mode="HTML")

async def admin_limit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID: return
    
    curr = get_setting("default_ip_limit", "2")
    msg = f"""┌〔 👥 <b>UBAH DEFAULT LIMIT IP</b> 〕
├ 🌐 <b>Limit Saat Ini</b>: {curr} IP
└────────────────────────

Pilih preset atau ketik angka manual (contoh: <code>5</code>):"""
    kb = [
        [InlineKeyboardButton("1 IP", callback_data="set_l_1"), InlineKeyboardButton("2 IP", callback_data="set_l_2"), InlineKeyboardButton("3 IP", callback_data="set_l_3")],
        [InlineKeyboardButton("« KEMBALI", callback_data="menu_admin")]
    ]
    context.user_data["admin_typing_mode"] = "limit"
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def admin_set_limit_preset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID: return
    l_val = query.data.replace("set_l_", "")
    set_setting("default_ip_limit", l_val)
    await query.edit_message_text(f"✅ <b>Default limit IP diubah menjadi {l_val} IP.</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« KEMBALI", callback_data="menu_admin")]]), parse_mode="HTML")

async def admin_quota_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID: return
    
    curr = get_setting("default_quota", "100 GB")
    msg = f"""┌〔 📦 <b>UBAH DEFAULT DATA QUOTA</b> 〕
├ 📦 <b>Quota Saat Ini</b>: {curr}
└────────────────────────

Pilih preset atau ketik manual (contoh: <code>200</code> untuk 200 GB):"""
    kb = [
        [InlineKeyboardButton("50 GB", callback_data="set_q_50 GB"), InlineKeyboardButton("100 GB", callback_data="set_q_100 GB"), InlineKeyboardButton("Unlimited", callback_data="set_q_Unlimited")],
        [InlineKeyboardButton("« KEMBALI", callback_data="menu_admin")]
    ]
    context.user_data["admin_typing_mode"] = "quota"
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def admin_set_quota_preset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID: return
    q_val = query.data.replace("set_q_", "")
    set_setting("default_quota", q_val)
    await query.edit_message_text(f"✅ <b>Default quota berhasil diubah menjadi {q_val}.</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« KEMBALI", callback_data="menu_admin")]]), parse_mode="HTML")




async def admin_custom_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    admin_id_val = int(get_setting("admin_id", str(ADMIN_ID)))
    if u.id != admin_id_val: return
    # If in active renew or buy conversation, DO NOT intercept!
    if context.user_data.get("renew_acc_id") or context.user_data.get("buy_proto"):
        return
    mode = context.user_data.get("admin_typing_mode", "")
    if not mode: return
    
    raw = update.message.text.strip()
    context.user_data["admin_typing_mode"] = ""
    
    if mode == "price":
        val = re.sub(r"[^0-9]", "", raw)
        if val:
            set_setting("price_per_day", val)
            await update.message.reply_text(f"✅ <b>Tarif harian diubah menjadi Rp {int(val):,} / hari.</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« KEMBALI", callback_data="menu_admin")]]), parse_mode="HTML")
    elif mode == "limit":
        val = re.sub(r"[^0-9]", "", raw)
        if val:
            set_setting("default_ip_limit", val)
            await update.message.reply_text(f"✅ <b>Default limit IP diubah menjadi {val} IP.</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« KEMBALI", callback_data="menu_admin")]]), parse_mode="HTML")
    elif mode == "quota":
        if "unlim" in raw.lower():
            set_setting("default_quota", "Unlimited")
            await update.message.reply_text("✅ <b>Default quota diubah menjadi Unlimited.</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« KEMBALI", callback_data="menu_admin")]]), parse_mode="HTML")
        else:
            val = re.sub(r"[^0-9]", "", raw)
            if val:
                set_setting("default_quota", f"{val} GB")
                await update.message.reply_text(f"✅ <b>Default quota diubah menjadi {val} GB.</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« KEMBALI", callback_data="menu_admin")]]), parse_mode="HTML")
    elif mode == "create_all_in_one":
        clean_user = re.sub(r'[^a-zA-Z0-9_-]', '', raw).lower()
        if not clean_user or len(clean_user) < 3:
            await update.message.reply_text("❌ <b>Username minimal 3 karakter alfabet/angka!</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« KEMBALI", callback_data="menu_admin")]]), parse_mode="HTML")
            return
        
        context.user_data["vip_user"] = clean_user
        context.user_data["admin_typing_mode"] = "create_all_pass"
        msg = f"""┌〔 🔑 <b>CUSTOM PASSWORD SSH & VIP</b> 〕
├ 👤 <b>Username</b> : <code>{clean_user}</code>
└────────────────────────

Ketik <b>Password SSH Custom</b> yang diinginkan (Contoh: <code>pass123</code>):"""
        kb = [[InlineKeyboardButton("« BATAL", callback_data="menu_admin")]]
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        return
    elif mode == "create_all_pass":
        clean_user = context.user_data.get("vip_user", "vipuser")
        ssh_pass = raw.strip()
        if not ssh_pass:
            ssh_pass = str(uuid.uuid4())[:8]
        
        # UUID key for Xray
        xray_uuid = str(uuid.uuid4())
        days = 30
        now = datetime.datetime.now()
        exp_dt = now + datetime.timedelta(days=days)
        exp_str = exp_dt.strftime("%d/%m/%Y %H:%M WIB")
        quota = get_setting("default_quota", "100 GB")
        ip_limit = int(get_setting("default_ip_limit", "2"))
        u_id = update.effective_user.id

        # 1. Linux SSH with custom password
        try:
            chage_exp = exp_dt.strftime("%Y-%m-%d")
            subprocess.run(["useradd", "-M", "-s", "/bin/false", "-e", chage_exp, clean_user], capture_output=True)
            p = subprocess.Popen(["chpasswd"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            p.communicate(input=f"{clean_user}:{ssh_pass}\n".encode())
        except Exception as e:
            print("SSH VIP creation error:", e)

        # 2. Xray Core (VLESS, VMESS, TROJAN) with xray_uuid
        try:
            with open("/usr/local/etc/xray/config.json", "r") as f:
                cfg = json.load(f)
            for inb in cfg.get("inbounds", []):
                t = inb.get("tag", "")
                clients = inb.get("settings", {}).get("clients", [])
                if t == "vless-ws-inbound":
                    clients.append({"id": xray_uuid, "email": clean_user, "alterId": 0})
                elif t == "vmess-ws-inbound":
                    clients.append({"id": xray_uuid, "email": clean_user, "alterId": 0})
                elif t == "trojan-ws-inbound":
                    clients.append({"password": xray_uuid, "email": clean_user})
            with open("/usr/local/etc/xray/config.json", "w") as f:
                json.dump(cfg, f, indent=2)
            subprocess.run(["systemctl", "restart", "xray"])
        except Exception as e:
            print("Xray VIP creation error:", e)

        # 3. Save 4 accounts to SQLite DB
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        for p_type in ["ssh", "vless", "vmess", "trojan"]:
            secret_val = ssh_pass if p_type == "ssh" else xray_uuid
            c.execute("""INSERT OR REPLACE INTO accounts 
                (user_id, username, protocol, uuid_or_pass, exp_date, password, days, quota_gb, ip_limit, uuid, config_link, used_bytes, used_gb)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0.0)""",
                (u_id, f"{clean_user}-{p_type}" if p_type != "ssh" else clean_user, p_type, secret_val, exp_str, secret_val, days, quota, ip_limit, secret_val, ""))
        conn.commit()
        conn.close()

        vip_card = format_all_in_one_account(clean_user, ssh_pass, xray_uuid, exp_str, ip_limit=f"{ip_limit} Device", quota=quota)
        
        # Send card to admin
        await update.message.reply_text(
            vip_card,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« KEMBALI KE PANEL ADMIN", callback_data="menu_admin")]]),
            parse_mode="HTML"
        )
        return
    elif mode == "topup_user":
        target_id = re.sub(r"[^0-9]", "", raw)
        if target_id:
            context.user_data["topup_target_id"] = int(target_id)
            context.user_data["admin_typing_mode"] = "topup_amt"
            await update.message.reply_text(
                f"✅ Target User ID: <code>{target_id}</code>\n\nKetik <b>Jumlah Saldo</b> (Rp) yang ingin ditambahkan:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« BATAL", callback_data="menu_admin")]]),
                parse_mode="HTML"
            )
            return
    elif mode == "topup_amt":
        amt = re.sub(r"[^0-9]", "", raw)
        target_id = context.user_data.get("topup_target_id")
        if amt and target_id:
            amt_int = int(amt)
            update_user_balance(target_id, amt_int)
            u_info = get_user(target_id, "")
            await update.message.reply_text(
                f"✅ <b>TOP UP BERHASIL!</b>\n\n"
                f"• Target ID : <code>{target_id}</code>\n"
                f"• Nominal   : <b>Rp {amt_int:,}</b>\n"
                f"• Saldo Baru: <b>Rp {u_info['balance']:,}</b>",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« KEMBALI KE ADMIN", callback_data="menu_admin")]]),
                parse_mode="HTML"
            )
            # Send natural telegram notif to forum/group
            admin_u = update.effective_user
            admin_name = f"@{admin_u.username}" if admin_u.username else f"ID {admin_u.id}"
            target_name = f"@{u_info['username']}" if u_info.get('username') else f"ID {target_id}"
            send_telegram_notif(
                f"💳 <b>TOP UP SALDO SUKSES</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>Pengguna</b>   : {target_name} (<code>{target_id}</code>)\n"
                f"💰 <b>Nominal</b>    : Rp {amt_int:,}\n"
                f"💳 <b>Saldo Baru</b> : Rp {u_info['balance']:,}\n"
                f"👑 <b>Oleh Admin</b> : {admin_name}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━"
            )

            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=f"💳 <b>TOP UP SALDO DITERIMA!</b>\n\nSaldo Anda telah ditambahkan sebesar <b>Rp {amt_int:,}</b> oleh Admin.\nSaldo Anda sekarang: <b>Rp {u_info['balance']:,}</b>",
                    parse_mode="HTML"
                )
            except Exception: pass
            return
    elif mode and mode.startswith("broadcast"):
        target_mode = mode.replace("broadcast_", "") if "_" in mode else "all"
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        if target_mode == "active":
            c.execute("SELECT DISTINCT user_id FROM accounts")
        else:
            c.execute("SELECT user_id FROM users")
        user_list = [row[0] for row in c.fetchall() if row[0]]
        conn.close()
        
        sent_count = 0
        bc_header = "📢 <b>PENGUMUMAN RESMI SHIRO VPN NETWORK</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        for uid in user_list:
            try:
                await context.bot.send_message(chat_id=uid, text=bc_header + raw, parse_mode="HTML")
                sent_count += 1
            except Exception: pass
        
        target_label = "Pengguna dengan Akun Aktif" if target_mode == "active" else "Semua Pengguna Terdaftar"
        await update.message.reply_text(
            f"✅ <b>BROADCAST SELESAI!</b>\n\n🎯 <b>Target:</b> {target_label}\n📊 <b>Terkirim:</b> <b>{sent_count} / {len(user_list)}</b> user.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« KEMBALI KE ADMIN", callback_data="menu_admin")]]),
            parse_mode="HTML"
        )
        return
    elif mode == "wiz_token":
        if re.match(r"^\d{8,12}:.{30,}$", raw):
            set_setting("bot_token", raw)
            await update.message.reply_text(f"✅ <b>Bot Token diperbarui di database!</b>\n\nSilakan restart bot via terminal VPS.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« KEMBALI", callback_data="admin_wizard")]]), parse_mode="HTML")
        else:
            await update.message.reply_text("❌ <b>Format Bot Token tidak valid!</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« KEMBALI", callback_data="admin_wizard")]]), parse_mode="HTML")
    elif mode == "wiz_owner_id":
        val = re.sub(r"[^0-9]", "", raw)
        if val:
            set_setting("admin_id", val)
            await update.message.reply_text(f"✅ <b>Admin ID diperbarui:</b> <code>{val}</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« KEMBALI", callback_data="admin_wizard")]]), parse_mode="HTML")
    elif mode == "wiz_owner_user":
        u_tag = raw if raw.startswith("@") else f"@{raw}"
        set_setting("admin_user", u_tag)
        await update.message.reply_text(f"✅ <b>Admin Username diperbarui:</b> <code>{u_tag}</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« KEMBALI", callback_data="admin_wizard")]]), parse_mode="HTML")
    elif mode == "wiz_domain":
        dom = raw.replace("https://", "").replace("http://", "").strip("/")
        set_setting("domain", dom)
        await update.message.reply_text(f"✅ <b>Domain diperbarui:</b> <code>{dom}</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« KEMBALI", callback_data="admin_wizard")]]), parse_mode="HTML")
    elif mode == "wiz_notif":
        chat_id = ""
        thread_id = None
        m = re.search(r"t\.me/c/(\d+)/(\d+)", raw)
        if m:
            chat_id = "-100" + m.group(1)
            thread_id = int(m.group(2))
        else:
            m2 = re.search(r"(-?\d+)", raw)
            if m2: chat_id = m2.group(1)
        if chat_id:
            set_setting("notif_chat_id", str(chat_id))
            if thread_id is not None:
                set_setting("notif_thread_id", str(thread_id))
            await update.message.reply_text(f"✅ <b>Notifikasi Terhubung!</b>\nChat: <code>{chat_id}</code> | Topic: <code>{thread_id}</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« KEMBALI", callback_data="admin_wizard")]]), parse_mode="HTML")
        else:
            await update.message.reply_text("❌ <b>Format Link Topic tidak valid!</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« KEMBALI", callback_data="admin_wizard")]]), parse_mode="HTML")


# ================= RENEW CONVERSATION =================
async def renew_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # Clear any lingering typing mode
    context.user_data["admin_typing_mode"] = ""
    try:
        acc_id = int(query.data.replace("renew_acc_", ""))
    except (ValueError, AttributeError):
        await query.edit_message_text("❌ Data tidak valid.", parse_mode="HTML")
        return ConversationHandler.END
    u = update.effective_user
    admin_id_val = int(get_setting("admin_id", str(ADMIN_ID)))

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if u.id == admin_id_val:
        c.execute("SELECT id, username, protocol, exp_date, ip_limit, quota_gb FROM accounts WHERE id=?", (acc_id,))
    else:
        c.execute("SELECT id, username, protocol, exp_date, ip_limit, quota_gb FROM accounts WHERE id=? AND user_id=?", (acc_id, u.id))
    row = c.fetchone()
    conn.close()

    if not row:
        await query.edit_message_text("❌ <b>Akun tidak ditemukan atau bukan milik Anda.</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« KEMBALI", callback_data="menu_my_accounts")]]), parse_mode="HTML")
        return ConversationHandler.END

    aid, uname, proto, exp_s, ip_l, q_gb = row
    context.user_data["renew_acc_id"] = aid
    context.user_data["renew_uname"] = uname
    context.user_data["renew_proto"] = proto
    context.user_data["renew_exp"] = exp_s

    price_per_day = int(get_setting("price_per_day", "100"))

    msg = f"""┌〔 🔄 <b>RENEW PERPANJANG AKUN</b> 〕
├ 👤 <b>Username</b>   : <code>{uname}</code>
├ 🔌 <b>Protokol</b>   : {proto.upper()}
├ 📅 <b>Expired Saat Ini</b> : <code>{exp_s}</code>
├ 💰 <b>Tarif</b>      : Rp {price_per_day:,} / hari
└────────────────────────

Berapa <b>hari</b> masa aktif yang ingin Anda tambahkan?
<i>(Ketik angka saja, contoh: <code>30</code>)</i>"""

    kb = [[InlineKeyboardButton("❌ BATAL", callback_data="cancel_renew")]]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    return RENEW_INPUT_DAYS

async def renew_input_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_text = update.message.text.strip()
    u = update.effective_user
    acc_id = context.user_data.get("renew_acc_id")
    uname = context.user_data.get("renew_uname")
    proto = context.user_data.get("renew_proto")
    exp_s = context.user_data.get("renew_exp")

    if not raw_text.isdigit() or int(raw_text) <= 0:
        await update.message.reply_text("⚠️ <i>Jumlah hari harus berupa angka bulat positif (contoh: 30). Silakan ketik ulang:</i>", parse_mode="HTML")
        return RENEW_INPUT_DAYS

    days = int(raw_text)
    price_per_day = int(get_setting("price_per_day", "100"))
    total_cost = days * price_per_day

    user_data = get_user(u.id, u.username)
    balance = user_data["balance"]

    if balance < total_cost:
        msg = f"""❌ <b>SALDO TIDAK MENCUKUPI!</b>

├ 💳 <b>Total Biaya</b> : Rp {total_cost:,} ({days} Hari)
├ 💰 <b>Saldo Anda</b>  : Rp {balance:,}
└ ⚠️ <i>Silakan top up saldo terlebih dahulu untuk melanjutkan renew.</i>"""
        kb = [
            [InlineKeyboardButton("💳 TOP UP SALDO", callback_data="menu_topup")],
            [InlineKeyboardButton("« KEMBALI KE DAFTAR AKUN", callback_data="menu_my_accounts")]
        ]
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        return ConversationHandler.END

    # Deduct balance
    update_user_balance(u.id, -total_cost)

    # Calculate new expiry
    now = datetime.datetime.now()
    base_dt = now
    # Try parsing current expiry
    try:
        clean_exp = exp_s.replace(" WIB", "").strip()
        if "(" in clean_exp:
            # e.g. 30 Menit (12:00)
            base_dt = now
        elif "/" in clean_exp:
            # e.g. 26/09/2026 19:58
            parts = clean_exp.split(" ")
            d_p = parts[0].split("/")
            t_p = parts[1].split(":") if len(parts) > 1 else [0, 0]
            parsed = datetime.datetime(int(d_p[2]), int(d_p[1]), int(d_p[0]), int(t_p[0]), int(t_p[1]))
            if parsed > now:
                base_dt = parsed
        elif "-" in clean_exp:
            # e.g. 2026-09-26
            d_p = clean_exp.split("-")
            parsed = datetime.datetime(int(d_p[0]), int(d_p[1]), int(d_p[2]), 23, 59, 59)
            if parsed > now:
                base_dt = parsed
    except Exception:
        base_dt = now

    new_exp_dt = base_dt + datetime.timedelta(days=days)
    new_exp_str = new_exp_dt.strftime("%d/%m/%Y %H:%M WIB")

    # Update in DB
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE accounts SET exp_date=? WHERE id=?", (new_exp_str, acc_id))
    conn.commit()
    conn.close()

    # System Linux User update for SSH if applicable
    if proto == "ssh":
        try:
            # chage -E YYYY-MM-DD
            chage_exp = new_exp_dt.strftime("%Y-%m-%d")
            subprocess.run(['chage', '-E', chage_exp, uname])
        except Exception:
            pass

    # Send natural notif
    send_telegram_notif(
        f"🔄 <b>PERPANJANG AKUN BERHASIL</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Pengguna</b>   : @{u.username or u.first_name} (<code>{u.id}</code>)\n"
        f"🔑 <b>Akun</b>       : <code>{uname}</code>\n"
        f"🔌 <b>Protokol</b>   : <b>{proto.upper()}</b>\n"
        f"⏱️ <b>Tambahan</b>   : +{days} Hari\n"
        f"📅 <b>Expired Baru</b>: <code>{new_exp_str}</code>\n"
        f"💰 <b>Biaya</b>      : Rp {total_cost:,}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

    msg = f"""┌〔 ✅ <b>RENEW AKUN BERHASIL!</b> 〕
├ 👤 <b>Username</b>   : <code>{uname}</code>
├ 🔌 <b>Protokol</b>   : {proto.upper()}
├ ⏱️ <b>Perpanjangan</b>: +{days} Hari
├ 📅 <b>Expired Baru</b> : <code>{new_exp_str}</code>
├ 💰 <b>Biaya Terpotong</b> : Rp {total_cost:,}
└────────────────────────

<i>Masa aktif akun Anda telah berhasil diperpanjang.</i>"""

    kb = [
        [InlineKeyboardButton("📦 LIHAT AKUN SAYA", callback_data="menu_my_accounts")],
        [InlineKeyboardButton("« MENU UTAMA", callback_data="menu_start")]
    ]
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    context.user_data.pop("renew_acc_id", None)
    return ConversationHandler.END

async def cancel_renew(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("renew_acc_id", None)
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ <b>Perpanjangan akun dibatalkan.</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« KEMBALI", callback_data="menu_my_accounts")]]), parse_mode="HTML")
    return ConversationHandler.END

# ================= MAIN APPLICATION =================
def main():
    init_db()
    token_to_use = _db_boot("bot_token", BOT_TOKEN)
    if not token_to_use or token_to_use == "YOUR_BOT_TOKEN_HERE":
        logger.error("FATAL: Bot token is not configured in DB or fallback! Please set via menu [10].")
        sys.exit(1)
    app = ApplicationBuilder().token(token_to_use).build()

    # Buy Conversation Flow
    buy_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(buy_menu, pattern="^menu_buy$"),
            CallbackQueryHandler(buy_select_proto, pattern="^proto_")
        ],
        states={
            BUY_PROTO: [CallbackQueryHandler(buy_select_proto, pattern="^proto_")],
            BUY_SERVER: [CallbackQueryHandler(buy_select_server, pattern="^srv_"), CallbackQueryHandler(buy_menu, pattern="^menu_buy$")],
            BUY_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, buy_input_user)],
            BUY_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, buy_input_pass)],
            BUY_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, buy_input_days)],
            BUY_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, buy_admin_input_limit)],
            BUY_QUOTA: [MessageHandler(filters.TEXT & ~filters.COMMAND, buy_admin_input_quota)],
        },
        fallbacks=[
            CallbackQueryHandler(cancel_conversation, pattern="^cancel_conv$"),
            CallbackQueryHandler(start_cmd, pattern="^menu_start$")
        ],
        per_message=False,
        allow_reentry=True
    )

    # Register Handlers
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("menu", start_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_custom_input), group=1)
    
    renew_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(renew_start, pattern="^renew_acc_")
        ],
        states={
            RENEW_INPUT_DAYS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, renew_input_days)
            ]
        },
        fallbacks=[
            CallbackQueryHandler(cancel_renew, pattern="^cancel_renew$"),
            CommandHandler("cancel", cancel_renew)
        ],
        per_chat=True,
        per_user=True
    )
    app.add_handler(renew_conv)

    app.add_handler(buy_conv)

    # Menu Callbacks
    app.add_handler(CallbackQueryHandler(start_cmd, pattern="^menu_start$"))
    app.add_handler(CallbackQueryHandler(trial_menu, pattern="^menu_trial$"))
    app.add_handler(CallbackQueryHandler(execute_trial, pattern="^trial_"))
    app.add_handler(CallbackQueryHandler(my_accounts_menu, pattern="^menu_my_accounts$"))
    app.add_handler(CallbackQueryHandler(toggle_auto_renew_callback, pattern="^toggle_ar_"))
    app.add_handler(CallbackQueryHandler(account_detail_menu, pattern="^acc_view_"))
    app.add_handler(CallbackQueryHandler(topup_menu, pattern="^menu_topup$"))
    app.add_handler(CallbackQueryHandler(help_menu, pattern="^menu_help$"))
    app.add_handler(CallbackQueryHandler(server_status_menu, pattern="^menu_server_status$"))
    app.add_handler(CallbackQueryHandler(admin_topup_prompt, pattern="^admin_topup$"))
    app.add_handler(CallbackQueryHandler(admin_create_all_prompt, pattern="^admin_create_all_prompt$"))
    app.add_handler(CallbackQueryHandler(admin_broadcast_prompt, pattern="^admin_broadcast$"))
    app.add_handler(CallbackQueryHandler(admin_broadcast_set_target, pattern="^bc_target_"))
    app.add_handler(CallbackQueryHandler(admin_toggle_maintenance_callback, pattern="^admin_toggle_maintenance$"))
    app.add_handler(CallbackQueryHandler(admin_panel_menu, pattern="^menu_admin$"))
    app.add_handler(CallbackQueryHandler(admin_list_accounts_menu, pattern="^admin_list_accounts$"))

    app.add_handler(CallbackQueryHandler(admin_bot_wizard, pattern="^admin_wizard$"))
    app.add_handler(CallbackQueryHandler(wiz_token_prompt, pattern="^wiz_token$"))
    app.add_handler(CallbackQueryHandler(wiz_owner_prompt, pattern="^wiz_owner$"))
    app.add_handler(CallbackQueryHandler(wiz_domain_prompt, pattern="^wiz_domain$"))
    app.add_handler(CallbackQueryHandler(wiz_notif_prompt, pattern="^wiz_notif$"))
    app.add_handler(CallbackQueryHandler(admin_price_menu, pattern="^admin_price$"))
    app.add_handler(CallbackQueryHandler(admin_set_price_preset, pattern="^set_p_"))
    app.add_handler(CallbackQueryHandler(admin_limit_menu, pattern="^admin_limit$"))
    app.add_handler(CallbackQueryHandler(admin_set_limit_preset, pattern="^set_l_"))
    app.add_handler(CallbackQueryHandler(admin_quota_menu, pattern="^admin_quota$"))
    app.add_handler(CallbackQueryHandler(admin_set_quota_preset, pattern="^set_q_"))

    app.add_handler(CallbackQueryHandler(admin_restart_core, pattern="^admin_restart_core$"))

    print("Shiro Telegram Bot is running smoothly...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()