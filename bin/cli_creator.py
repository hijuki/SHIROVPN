#!/usr/bin/env python3
import os
import sys
import json
import uuid
import time
import datetime
import subprocess
import sqlite3

DB_PATH = "/var/lib/shirobot.db"
XRAY_CONFIG = "/usr/local/etc/xray/config.json"
def get_domain():
    import sqlite3
    try:
        conn = sqlite3.connect("/var/lib/shirobot.db")
        c = conn.cursor()
        c.execute('SELECT value FROM settings WHERE key="domain"')
        r = c.fetchone()
        conn.close()
        return r[0] if r else "your-domain.com"
    except Exception:
        return "your-domain.com"

DOMAIN = get_domain()

# ANSI Terminal Colors
CYAN = '\033[0;36m'
GREEN = '\033[0;32m'
RED = '\033[0;31m'
YELLOW='\033[1;33m'
PURPLE='\033[0;35m'
BLUE = '\033[0;34m'
WHITE= '\033[1;37m'
GRAY = '\033[0;90m'
BOLD = '\033[1m'
NC   = '\033[0m'

def get_setting(key, default=None):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = c.fetchone()
        conn.close()
        return row[0] if row else default
    except:
        return default

def admin_loading_bar(proto, user):
    stages = [
        ("VERIFY", f"Memverifikasi modul engine {proto.upper()} & dependensi kernel..."),
        ("CIPHER", f"Mengenerate handshake keys, TLS SAN, & UUID identifier..."),
        ("ROUTING", f"Mendaftarkan multiplexer inbound & sinkronisasi port listener..."),
        ("DB_SYNC", f"Menyimpan record provisioning ke SQLite (/var/lib/shirobot.db)..."),
        ("NOTIF", f"Mengirim telemetry broadcast ke Supergroup Thread Topic...")
    ]
    print()
    for tag, desc in stages:
        sys.stdout.write(f" {GRAY}[{CYAN}⚡ {tag:<7}{GRAY}]{NC} {WHITE}{desc}{NC}\n")
        time.sleep(0.22)
    print(f"\n {GREEN}✓ {proto.upper()} SERVICE PROVISIONING COMPLETE.{NC}\n")
    time.sleep(0.4)

def format_admin_ssh(user, password, exp_str, ip_limit, quota):
    return f"""{CYAN}╔══════════════════════════════════════════════════════════════════════╗{NC}
{CYAN}║{WHITE}              ⚡ SSH & WEBSOCKET PROVISIONING REPORT                  {CYAN}║{NC}
{CYAN}╚══════════════════════════════════════════════════════════════════════╝{NC}

{YELLOW}┌── [ CREDENTIALS & METRICS ] ─────────────────────────────────────────┐{NC}
 │ {WHITE}Username     {NC}: {GREEN}{user:<20}{NC} {WHITE}Engine Protocol{NC}: SSH WS / OpenSSH  │
 │ {WHITE}Password     {NC}: {GREEN}{password:<20}{NC} {WHITE}Multi-IP Limit {NC}: {ip_limit:<18} │
 │ {WHITE}Expired Date {NC}: {GREEN}{exp_str:<20}{NC} {WHITE}Data Quota     {NC}: {quota:<18} │
 │ {WHITE}Status       {NC}: {GREEN}ACTIVE (PROVISIONED){NC}                                 │
{YELLOW}└──────────────────────────────────────────────────────────────────────┘{NC}

{PURPLE}┌── [ CONNECTION ENDPOINTS ] ──────────────────────────────────────────┐{NC}
 │ {WHITE}Domain Server{NC}: {DOMAIN:<20} {WHITE}Dropbear Port  {NC}: 109, 110          │
 │ {WHITE}TLS Multiplex{NC}: 443 (Path: /ssh-ws) {WHITE}OpenSSH Port   {NC}: 80, 22            │
 │ {WHITE}Stunnel SSL  {NC}: 222, 333, 444, 777  {WHITE}BadVPN UDPGW   {NC}: 7100 - 7900       │
{PURPLE}└──────────────────────────────────────────────────────────────────────┘{NC}

{BLUE}┌── [ CLIENT RAW CONFIGURATION ] ──────────────────────────────────────┐{NC}
 │ {WHITE}HTTP Custom String{NC}:                                                  │
 │ {GREEN}{DOMAIN}:80@{user}:{password}{NC}
 │                                                                      │
 │ {WHITE}WebSocket Payload {NC}:                                                  │
 │ {GRAY}GET /ssh-ws HTTP/1.1[crlf]Host: {DOMAIN}[crlf]Upgrade: websocket[crlf]Connection: Upgrade[crlf][crlf]{NC}
{BLUE}└──────────────────────────────────────────────────────────────────────┘{NC}"""

def format_admin_xray(proto, user, key_or_uuid, exp_str, ip_limit, quota):
    p_upper = proto.upper()
    ws_link = ""
    grpc_link = ""
    
    if proto == "vless":
        ws_link = f"vless://{key_or_uuid}@{DOMAIN}:443?path=%2Fvless&security=tls&encryption=none&host={DOMAIN}&type=ws&sni={DOMAIN}#{user}"
        grpc_link = f"vless://{key_or_uuid}@{DOMAIN}:443?mode=gun&security=tls&encryption=none&type=grpc&serviceName=vless-grpc&sni={DOMAIN}#{user}"
    elif proto == "vmess":
        import base64
        raw_ws = {"v": "2", "ps": user, "add": DOMAIN, "port": "443", "id": key_or_uuid, "aid": "0", "scy": "auto", "net": "ws", "type": "none", "host": DOMAIN, "path": "/vmess", "tls": "tls", "sni": DOMAIN}
        ws_link = f"vmess://{base64.b64encode(json.dumps(raw_ws).encode()).decode()}"
    elif proto == "trojan":
        ws_link = f"trojan://{key_or_uuid}@{DOMAIN}:443?path=%2Ftrojan-ws&security=tls&host={DOMAIN}&type=ws&sni={DOMAIN}#{user}"

    key_label = "UUID Key    " if proto in ["vless", "vmess"] else "Auth Secret "
    grpc_section = f""" │ {WHITE}gRPC Direct URL{NC}:                                                  │\n │ {GREEN}{grpc_link}{NC}\n │                                                                      │\n""" if grpc_link else ""

    return f"""{CYAN}╔══════════════════════════════════════════════════════════════════════╗{NC}
{CYAN}║{WHITE}              ⚡ XRAY {p_upper:<6} ENGINE PROVISIONING REPORT              {CYAN}║{NC}
{CYAN}╚══════════════════════════════════════════════════════════════════════╝{NC}

{YELLOW}┌── [ CLIENT ACCOUNT DATA ] ───────────────────────────────────────────┐{NC}
 │ {WHITE}Username     {NC}: {GREEN}{user:<20}{NC} {WHITE}Core Engine    {NC}: Xray v1.8.24 Direct│
 │ {WHITE}{key_label}{NC}: {GREEN}{key_or_uuid:<36}{NC} │
 │ {WHITE}Expired Date {NC}: {GREEN}{exp_str:<20}{NC} {WHITE}Multi-IP Limit {NC}: {ip_limit:<18} │
 │ {WHITE}Data Quota   {NC}: {GREEN}{quota:<20}{NC} {WHITE}Service Status {NC}: ACTIVE (BOUND)     │
{YELLOW}└──────────────────────────────────────────────────────────────────────┘{NC}

{PURPLE}┌── [ SERVER INBOUND PARAMETERS ] ─────────────────────────────────────┐{NC}
 │ {WHITE}Server Domain{NC}: {DOMAIN:<20} {WHITE}TLS Port       {NC}: 443                 │
 │ {WHITE}Network Type {NC}: WebSocket (Path: /{proto}) {WHITE}TLS Security   {NC}: Enabled (ALPN h2)  │
{PURPLE}└──────────────────────────────────────────────────────────────────────┘{NC}

{BLUE}┌── [ CLIENT ROUTING URL ] ────────────────────────────────────────────┐{NC}
 │ {WHITE}WebSocket TLS URL{NC}:                                                  │
 │ {GREEN}{ws_link}{NC}
 │                                                                      │
{grpc_section}{BLUE}└──────────────────────────────────────────────────────────────────────┘{NC}"""

def format_admin_zivpn(user, password, exp_str, ip_limit, quota):
    return f"""{CYAN}╔══════════════════════════════════════════════════════════════════════╗{NC}
{CYAN}║{WHITE}              ⚡ UDP ZIVPN ENGINE PROVISIONING REPORT                 {CYAN}║{NC}
{CYAN}╚══════════════════════════════════════════════════════════════════════╝{NC}

{YELLOW}┌── [ CLIENT CREDENTIALS ] ────────────────────────────────────────────┐{NC}
 │ {WHITE}Username     {NC}: {GREEN}{user:<20}{NC} {WHITE}Protocol Engine{NC}: UDP ZiVPN Daemon │
 │ {WHITE}Password     {NC}: {GREEN}{password:<20}{NC} {WHITE}Multi-IP Limit {NC}: {ip_limit:<18} │
 │ {WHITE}Expired Date {NC}: {GREEN}{exp_str:<20}{NC} {WHITE}Data Quota     {NC}: {quota:<18} │
{YELLOW}└──────────────────────────────────────────────────────────────────────┘{NC}

{PURPLE}┌── [ UDP NETWORKING PARAMETERS ] ─────────────────────────────────────┐{NC}
 │ {WHITE}Server Domain{NC}: {DOMAIN:<20} {WHITE}UDP Listen Port{NC}: 5667 (6000-19999)  │
 │ {WHITE}Obfuscation  {NC}: zivpn                {WHITE}Auth Mode      {NC}: Password Direct   │
{PURPLE}└──────────────────────────────────────────────────────────────────────┘{NC}"""

def format_admin_wg(user, exp_str, client_conf, ip_limit, quota):
    return f"""{CYAN}╔══════════════════════════════════════════════════════════════════════╗{NC}
{CYAN}║{WHITE}              ⚡ WIREGUARD PEER PROVISIONING REPORT                   {CYAN}║{NC}
{CYAN}╚══════════════════════════════════════════════════════════════════════╝{NC}

{YELLOW}┌── [ PEER CONFIGURATION DATA ] ───────────────────────────────────────┐{NC}
 │ {WHITE}Peer Name    {NC}: {GREEN}{user:<20}{NC} {WHITE}Kernel Module  {NC}: wireguard.ko (wg0)│
 │ {WHITE}Expired Date {NC}: {GREEN}{exp_str:<20}{NC} {WHITE}Listen Port    {NC}: 51820 (UDP)        │
 │ {WHITE}IP Limit     {NC}: {ip_limit:<20} {WHITE}Quota          {NC}: {quota:<18} │
{YELLOW}└──────────────────────────────────────────────────────────────────────┘{NC}

{BLUE}┌── [ CLIENT RAW CONFIG (.conf) ] ─────────────────────────────────────┐{NC}
{WHITE}{client_conf}{NC}
{BLUE}└──────────────────────────────────────────────────────────────────────┘{NC}"""

def cli_create_account(proto):
    os.system("clear")
    title_map = {
        "ssh": "SSH & WEBSOCKET DAEMON",
        "vless": "XRAY VLESS TLS MULTIPLEXER",
        "vmess": "XRAY VMESS TLS MULTIPLEXER",
        "trojan": "XRAY TROJAN TLS MULTIPLEXER",
        "zivpn": "UDP ZIVPN LOW-LATENCY ENGINE",
        "wg": "WIREGUARD KERNEL PEER"
    }
    
    def_limit = get_setting('default_ip_limit', '2')
    def_quota = get_setting('default_quota', '100 GB')

    title = title_map.get(proto, proto.upper())
    print(f"{CYAN}╔══════════════════════════════════════════════════════════╗{NC}")
    print(f"{CYAN}║{WHITE}       ⚡ PROVISIONING CONSOLE: {title:<25} {CYAN}║{NC}")
    print(f"{CYAN}╚══════════════════════════════════════════════════════════╝{NC}")
    print(f"{YELLOW}┌── [ TARGET PARAMETERS ] ─────────────────────────────────┐{NC}")
    username = input(f" │ {WHITE}Target Username   {NC}: ").strip()
    if not username:
        print(f"{RED} │ [ABORT] Username parameter cannot be null!{NC}")
        print(f"{YELLOW}└──────────────────────────────────────────────────────────┘{NC}")
        return

    password = ""
    if proto not in ["vless", "vmess", "wg"]:
        password = input(f" │ {WHITE}Target Password   {NC}: ").strip()
        if not password:
            print(f"{RED} │ [ABORT] Password parameter cannot be null!{NC}")
            print(f"{YELLOW}└──────────────────────────────────────────────────────────┘{NC}")
            return
    else:
        password = str(uuid.uuid4())

    days_raw = input(f" │ {WHITE}Duration Days     {NC}[Default 30]: ").strip()
    days = int(days_raw) if days_raw.isdigit() and int(days_raw) > 0 else 30

    limit_raw = input(f" │ {WHITE}IP Limit          {NC}[Default {def_limit} IP]: ").strip()
    ip_limit_val = int(limit_raw) if limit_raw.isdigit() and int(limit_raw) > 0 else int(def_limit)
    ip_limit_str = f"{ip_limit_val} IP"

    quota_raw = input(f" │ {WHITE}Quota Limit (GB)  {NC}[Default {def_quota}]: ").strip()
    if quota_raw:
        quota_str = f"{quota_raw} GB" if not quota_raw.lower().endswith("gb") and quota_raw.lower() != "unlimited" else quota_raw
    else:
        quota_str = def_quota

    print(f"{YELLOW}└──────────────────────────────────────────────────────────┘{NC}")

    # Sysadmin high-tech progress loading
    admin_loading_bar(proto, username)

    exp_dt = datetime.datetime.now() + datetime.timedelta(days=days)
    exp_str = exp_dt.strftime("%d/%m/%Y %H:%M WIB")
    u_uuid = str(uuid.uuid4())

    # Build format
    if proto == "ssh":
        import datetime as _dt
        exp_date = (_dt.datetime.now() + _dt.timedelta(days=365)).strftime("%Y-%m-%d")
        subprocess.run(["useradd", "-e", exp_date, "-s", "/bin/false", "-M", username], stderr=subprocess.DEVNULL)
        subprocess.run(["chpasswd"], input=f"{username}:{password}\n", text=True)
        card = format_admin_ssh(username, password, exp_str, ip_limit_str, quota_str)
    elif proto == "vless":
        with open(XRAY_CONFIG) as _f: _cfg = json.load(_f)
        _cfg['inbounds'][0]['settings']['clients'].append({'id': u_uuid, 'email': username})
        with open(XRAY_CONFIG, 'w') as _f: json.dump(_cfg, _f, indent=2)
        subprocess.run("systemctl restart xray", shell=True)
        card = format_admin_xray("vless", username, u_uuid, exp_str, ip_limit_str, quota_str)
    elif proto == "vmess":
        with open(XRAY_CONFIG) as _f: _cfg = json.load(_f)
        _cfg['inbounds'][2]['settings']['clients'].append({'id': u_uuid, 'email': username})
        with open(XRAY_CONFIG, 'w') as _f: json.dump(_cfg, _f, indent=2)
        subprocess.run("systemctl restart xray", shell=True)
        card = format_admin_xray("vmess", username, u_uuid, exp_str, ip_limit_str, quota_str)
    elif proto == "trojan":
        with open(XRAY_CONFIG) as _f: _cfg = json.load(_f)
        _cfg['inbounds'][3]['settings']['clients'].append({'password': password, 'email': username})
        with open(XRAY_CONFIG, 'w') as _f: json.dump(_cfg, _f, indent=2)
        subprocess.run("systemctl restart xray", shell=True)
        card = format_admin_xray("trojan", username, password, exp_str, ip_limit_str, quota_str)
    elif proto == "zivpn":
        subprocess.run(["python3", "/usr/local/bin/manage_zivpn.py", username])
        card = format_admin_zivpn(username, password, exp_str, ip_limit_str, quota_str)
    elif proto == "wg":
        conf_raw = subprocess.getoutput(f"python3 /usr/local/bin/manage_wg.py {username}")
        card = format_admin_wg(username, exp_str, conf_raw, ip_limit_str, quota_str)

    # Save to SQLite
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""INSERT INTO accounts (user_id, username, password, uuid, protocol, exp_date, ip_limit, quota_gb, config_link)
                     VALUES (0, ?, ?, ?, ?, ?, ?, ?, ?)""",
                  (username, password, u_uuid, proto, exp_str, ip_limit_val, quota_str, card))
        conn.commit()
        conn.close()
    except Exception as e:
        pass

    # Trigger Luxury Telegram Notification to Topic
    cli_card = f"""╭━━━━━━━━━━━━━━━━━━━━━━╮
      ⚡ <b>ꜱʏꜱᴀᴅᴍɪɴ ᴘʀᴏᴠɪꜱɪᴏɴɪɴɢ</b>
╰━━━━━━━━━━━━━━━━━━━━━━╯

┌〔 📄 <b>ᴀᴄᴄᴏᴜɴᴛ ᴅᴇᴛᴀɪʟꜱ</b> 〕
├ 👤 <b>ᴜꜱᴇʀɴᴀᴍᴇ</b> : <code>{username}</code>
├ 🔌 <b>ᴘʀᴏᴛᴏᴋᴏʟ</b> : <b>{proto.upper()}</b>
├ ⏳ <b>ᴅᴜʀᴀꜱɪ</b>   : {days} Hari
├ 🌐 <b>ʟɪᴍɪᴛ ɪᴘ</b> : {ip_limit_str}
├ 📦 <b>ǫᴜᴏᴛᴀ</b>    : {quota_str}
├ 📅 <b>ᴇxᴘɪʀᴇᴅ</b>  : <code>{exp_str}</code>
└ 👑 <b>ᴏᴘᴇʀᴀᴛᴏʀ</b> : <code>ROOT CONSOLE</code>

━━━━━━━━━━━━━━━━━━━━━━
🛡 <i>Diprovisioning langsung via Terminal SSH VPS</i>"""
    try:
        subprocess.Popen(["python3", "/usr/local/bin/send_notif.py", cli_card])
    except:
        pass

    os.system("clear")
    print(card)
    print()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        cli_create_account(sys.argv[1].lower())
