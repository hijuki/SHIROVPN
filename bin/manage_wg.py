#!/usr/bin/env python3
"""WireGuard peer manager: add (with unique IP allocation) / del / list.

Usage:
  manage_wg.py add <username>          -> prints client .conf text
  manage_wg.py del  <username>
  manage_wg.py list
"""
import os
import re
import subprocess
import sys

WG_CONF = "/etc/wireguard/wg0.conf"
CLIENTS_DIR = "/etc/wireguard/clients"
SERVER_PUBKEY_FILE = "/etc/wireguard/public.key"
SUBNET = "10.66.66."

def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)

def load_conf():
    with open(WG_CONF) as f:
        return f.read()

def used_ips(conf_text):
    """All client IPs currently allocated in wg0.conf."""
    ips = set()
    for m in re.finditer(r"^AllowedIPs\s*=\s*" + re.escape(SUBNET) + r"(\d+)/32", conf_text, re.M):
        ips.add(int(m.group(1)))
    return ips

def next_ip(conf_text):
    """Lowest free IP in 10.66.66.0/24 (skip .1 = server, .2 reserved for tests)."""
    used = used_ips(conf_text)
    for n in range(2, 255):
        if n not in used:
            return n
    raise RuntimeError("WireGuard subnet full (10.66.66.0/24)")

def peer_block_exists(conf_text, username):
    return f"# PEER_{username}\n" in conf_text

def wg_sync():
    """Apply wg0.conf to the running interface without dropping other peers."""
    run(["bash", "-c", "wg syncconf wg0 <(wg-quick strip wg0)"])

def add_peer(username):
    if not re.match(r"^[a-z0-9_-]+$", username or ""):
        return "ERR: invalid username"
    conf_text = load_conf()
    if peer_block_exists(conf_text, username):
        # Already exists -> return stored client conf
        path = f"{CLIENTS_DIR}/{username}.conf"
        if os.path.exists(path):
            return open(path).read()
        return "ERR: peer exists but client conf missing"

    priv = run(["wg", "genkey"]).stdout.strip()
    pub = run(["wg", "pubkey"], input=priv).stdout.strip()
    server_pub = open(SERVER_PUBKEY_FILE).read().strip()

    ip_num = next_ip(conf_text)
    client_ip = f"{SUBNET}{ip_num}/32"

    # Get real server endpoint (domain or IP) from env or default file
    domain = os.environ.get("WG_ENDPOINT", "")
    if not domain and os.path.exists("/etc/wireguard/endpoint.conf"):
        domain = open("/etc/wireguard/endpoint.conf").read().strip()
    if not domain:
        domain = "sg1-shiro.my.id"

    block = f"\n# PEER_{username}\n[Peer]\nPublicKey = {pub}\nAllowedIPs = {client_ip}\n"
    with open(WG_CONF, "a") as f:
        f.write(block)
    wg_sync()

    client_conf = f"""[Interface]
PrivateKey = {priv}
Address = {client_ip}
DNS = 1.1.1.1, 8.8.8.8

[Peer]
PublicKey = {server_pub}
Endpoint = {domain}:51820
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
"""
    os.makedirs(CLIENTS_DIR, exist_ok=True)
    with open(f"{CLIENTS_DIR}/{username}.conf", "w") as f:
        f.write(client_conf)
    return client_conf

def del_peer(username):
    if not re.match(r"^[a-z0-9_-]+$", username or ""):
        return "ERR: invalid username"
    conf_text = load_conf()
    if not peer_block_exists(conf_text, username):
        return "OK: no such peer"

    # Remove the block: "# PEER_user\n[Peer]\n...AllowedIPs...\n" up to next # or EOF
    pattern = rf"\n?# PEER_{re.escape(username)}\n\[Peer\]\nPublicKey = [^\n]+\nAllowedIPs = [^\n]+\n"
    new_text = re.sub(pattern, "", conf_text)
    with open(WG_CONF, "w") as f:
        f.write(new_text)
    wg_sync()

    for path in (f"{CLIENTS_DIR}/{username}.conf",):
        if os.path.exists(path):
            os.remove(path)
    return "OK: deleted"

def list_peers():
    conf_text = load_conf()
    out = []
    for m in re.finditer(r"^# PEER_([a-z0-9_-]+)\n\[Peer\]\nPublicKey = (\S+)\nAllowedIPs = (\S+)", conf_text, re.M):
        out.append(f"{m.group(1)}\t{m.group(3)}")
    return "\n".join(out) or "(no peers)"

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    arg = sys.argv[2] if len(sys.argv) > 2 else ""
    if cmd == "add":
        print(add_peer(arg))
    elif cmd == "del":
        print(del_peer(arg))
    elif cmd == "list":
        print(list_peers())
    else:
        print(__doc__)
