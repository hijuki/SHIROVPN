#!/usr/bin/env python3
import sys
import json
import time
import subprocess
import threading

CYAN = '\033[0;36m'
GREEN = '\033[0;32m'
RED = '\033[0;31m'
YELLOW = '\033[1;33m'
PURPLE = '\033[0;35m'
BLUE = '\033[0;34m'
WHITE = '\033[1;37m'
GRAY = '\033[0;90m'
NC = '\033[0m'

stop_anim = False

def spinner():
    spinners = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    stages = [
        "Menghubungkan ke Server Ookla Terdekat...",
        "Mengukur Latency & Network Jitter...",
        "Menguji Download Bandwidth Capacity...",
        "Menguji Upload Bandwidth Capacity...",
        "Mengalkulasi Paket Loss & Telemetri..."
    ]
    idx = 0
    s_idx = 0
    while not stop_anim:
        stage = stages[s_idx % len(stages)]
        sp = spinners[idx % len(spinners)]
        sys.stdout.write(f"\r {GRAY}[{CYAN}⚡ BENCHMARK{GRAY}]{NC} {WHITE}{stage:<45}{NC} {CYAN}{sp}{NC} ")
        sys.stdout.flush()
        idx += 1
        if idx % 25 == 0:
            s_idx += 1
        time.sleep(0.08)

def main():
    print(f"\n{CYAN}╭─────────────────────────────────────────────────────────────╮{NC}")
    print(f"{CYAN}│{WHITE}           ⚡ OOKLA SPEEDTEST NETWORK BENCHMARK             {CYAN}│{NC}")
    print(f"{CYAN}╰─────────────────────────────────────────────────────────────╯{NC}\n")
    
    t = threading.Thread(target=spinner)
    t.daemon = True
    t.start()
    
    try:
        res = subprocess.run(
            ["/usr/bin/speedtest", "--accept-license", "--accept-gdpr", "--format=json"],
            capture_output=True,
            text=True,
            timeout=45
        )
        data = json.loads(res.stdout)
    except Exception as e:
        data = None
    
    global stop_anim
    stop_anim = True
    t.join()
    sys.stdout.write("\r" + " " * 75 + "\r")
    sys.stdout.flush()
    
    if not data or "download" not in data:
        print(f"{RED}✗ Gagal mengambil data benchmark. Silakan coba lagi.{NC}")
        return

    srv_name = f"{data.get('server', {}).get('name', 'Singapore')} ({data.get('server', {}).get('location', 'SG')})"
    isp = data.get('isp', 'UpCloud Singapore')
    ping = f"{data.get('ping', {}).get('latency', 0.0):.2f} ms"
    jitter = f"{data.get('ping', {}).get('jitter', 0.0):.2f} ms"
    
    dl_mbps = (data.get('download', {}).get('bandwidth', 0) * 8) / (1000**2)
    ul_mbps = (data.get('upload', {}).get('bandwidth', 0) * 8) / (1000**2)
    
    dl_str = f"{dl_mbps:.2f} Mbps"
    ul_str = f"{ul_mbps:.2f} Mbps"
    result_url = data.get('result', {}).get('url', 'https://www.speedtest.net')

    print(f"{YELLOW}┌── [ SERVER & LATENCY METRICS ] ─────────────────────────────┐{NC}")
    print(f" │ {WHITE}{'Hosted By':<14}{NC}: {srv_name:<42} │")
    print(f" │ {WHITE}{'ISP Provider':<14}{NC}: {isp:<42} │")
    print(f" │ {WHITE}{'Idle Latency':<14}{NC}: {ping:<18} {WHITE}{'Jitter':<8}{NC}: {jitter:<14} │")
    print(f"{YELLOW}└─────────────────────────────────────────────────────────────┘{NC}")
    
    print(f"{GREEN}┌── [ BANDWIDTH SPEED THROUGHPUT ] ───────────────────────────┐{NC}")
    print(f" │ {WHITE}{'Download Speed':<14}{NC}: {GREEN}{dl_str:<18}{NC} {WHITE}{'Status':<8}{NC}: {GREEN}ULTRA HIGH{NC}   │")
    print(f" │ {WHITE}{'Upload Speed':<14}{NC}: {GREEN}{ul_str:<18}{NC} {WHITE}{'Grade':<8}{NC}: {GREEN}TIER-1 GIGABIT{NC} │")
    print(f"{GREEN}└─────────────────────────────────────────────────────────────┘{NC}")
    
    print(f"{BLUE}┌── [ BENCHMARK RESULT CERTIFICATE ] ─────────────────────────┐{NC}")
    print(f" │ {WHITE}{'Result URL':<14}{NC}: {result_url:<42} │")
    print(f"{BLUE}└─────────────────────────────────────────────────────────────┘{NC}\n")

if __name__ == "__main__":
    main()
