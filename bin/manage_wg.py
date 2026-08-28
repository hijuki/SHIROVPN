#!/usr/bin/env python3
import sys
import subprocess
import os

def add_peer(username, ip_num=2):
    try:
        priv = subprocess.run(["wg", "genkey"], capture_output=True, text=True).stdout.strip()
        pub = subprocess.run(["wg", "pubkey"], input=priv, capture_output=True, text=True).stdout.strip()
        
        # Server pubkey
        server_pub = open("/etc/wireguard/public.key").read().strip()
        
        client_ip = f"10.66.66.{ip_num}/32"
        
        # Append peer to wg0.conf
        peer_block = f"""
# PEER_{username}
[Peer]
PublicKey = {pub}
AllowedIPs = {client_ip}
"""
        with open("/etc/wireguard/wg0.conf", "a") as f:
            f.write(peer_block)
            
        subprocess.run("wg addconf wg0 <(wg-quick strip wg0)", shell=True, executable="/bin/bash")
        
        # Client Config
        client_conf = f"""[Interface]
PrivateKey = {priv}
Address = {client_ip}
DNS = 1.1.1.1, 8.8.8.8

[Peer]
PublicKey = {server_pub}
Endpoint = your-domain.com:51820
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
"""
        os.makedirs(f"/etc/wireguard/clients", exist_ok=True)
        with open(f"/etc/wireguard/clients/{username}.conf", "w") as f:
            f.write(client_conf)
            
        return client_conf
    except Exception as e:
        return str(e)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(add_peer(sys.argv[1]))
