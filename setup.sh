#!/usr/bin/env bash
# ==============================================================================
# ⚡ SHIRO VPN AUTOMATED ALL-IN-ONE PROVISIONING INSTALLER ⚡
# Author: Shiro VPN Network (@YourTelegramUsername)
# Target OS: Ubuntu 20.04 / 22.04 LTS (x86_64)
# ==============================================================================

set -e

# ANSI Color Definition
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m'

clear
echo -e "${CYAN}┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓${NC}"
echo -e "${CYAN}┃${WHITE}         ⚡ SHIRO VPN ALL-IN-ONE MASTER INSTALLER ⚡          ${CYAN}┃${NC}"
echo -e "${CYAN}┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛${NC}"
echo ""

# 1. Root check
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}[ERROR] Installer ini harus dijalankan sebagai user ROOT.${NC}" 
   exit 1
fi

# 2. Input Initial Configuration
echo -e "${YELLOW}┌── [ KONFIGURASI AWAL SISTEM ] ──────────────────────────────┐${NC}"
read -rp " │ Masukkan Domain VPS (e.g. sg1.domain.com): " DOMAIN_INPUT
read -rp " │ Masukkan Telegram Bot Token (dari @BotFather): " BOT_TOKEN_INPUT
read -rp " │ Masukkan Admin Master Telegram User ID (e.g. 1234567890): " ADMIN_ID_INPUT
read -rp " │ Masukkan Username Admin Telegram (e.g. @YourTelegramUsername): " ADMIN_USER_INPUT
echo -e "${YELLOW}└─────────────────────────────────────────────────────────────┘${NC}"

if [[ -z "$DOMAIN_INPUT" || -z "$BOT_TOKEN_INPUT" || -z "$ADMIN_ID_INPUT" ]]; then
    echo -e "${RED}[ERROR] Semua kolom input wajib diisi! Instalasi dibatalkan.${NC}"
    exit 1
fi

echo ""
echo -e "${CYAN}[1/7] Memperbarui Package & Menginstall Dependencies...${NC}"
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    curl wget zip unzip tar jq git cron vnstat dropbear net-tools \
    iptables iptables-persistent sqlite3 python3 python3-pip python3-venv wireguard

pip3 install --upgrade pip
pip3 install python-telegram-bot[job-queue] requests urllib3 pyfiglet

echo -e "${CYAN}[2/7] Menginstall Ookla Speedtest CLI Resmi...${NC}"
if ! command -v speedtest &>/dev/null; then
    curl -s https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | bash
    apt-get install -y speedtest
fi

echo -e "${CYAN}[3/7] Menginstall Core Xray & BadVPN UDP-Gateway...${NC}"
# Install Xray if missing
if ! command -v xray &>/dev/null; then
    bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install
fi

# Install BadVPN udpgw if missing
if ! command -v badvpn-udpgw &>/dev/null; then
    wget -q -O /usr/local/bin/badvpn-udpgw "https://github.com/ambrop72/badvpn/raw/master/badvpn-udpgw" || true
    chmod +x /usr/local/bin/badvpn-udpgw 2>/dev/null || true
fi

echo -e "${CYAN}[4/7] Menyalin Script Engine & Service Daemon...${NC}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Deploy scripts
cp -r "${SCRIPT_DIR}/bin/"*.py /usr/local/bin/
cp "${SCRIPT_DIR}/bin/menu" /usr/bin/menu
chmod +x /usr/local/bin/*.py
chmod +x /usr/bin/menu

# Deploy banners & dropbear config
cp "${SCRIPT_DIR}/etc/issue.net" /etc/issue.net
cp "${SCRIPT_DIR}/etc/dropbear_banner" /etc/dropbear_banner
cp "${SCRIPT_DIR}/etc/dropbear.default" /etc/default/dropbear

# Deploy systemd unit files
cp "${SCRIPT_DIR}/systemd/"*.service /etc/systemd/system/

# Deploy Xray config template only on a fresh install (never clobber a live config)
mkdir -p /usr/local/etc/xray /var/log/xray /var/lib/shiro_traffic
if [ -f "${SCRIPT_DIR}/etc/xray_config.json" ] && [ ! -f /usr/local/etc/xray/config.json ]; then
    cp "${SCRIPT_DIR}/etc/xray_config.json" /usr/local/etc/xray/config.json
fi

echo -e "${CYAN}[5/7] Menyimpan Konfigurasi ke SQLite Database Master...${NC}"
mkdir -p /var/lib
BOT_TOKEN_INPUT="$BOT_TOKEN_INPUT" ADMIN_ID_INPUT="$ADMIN_ID_INPUT" \
ADMIN_USER_INPUT="$ADMIN_USER_INPUT" DOMAIN_INPUT="$DOMAIN_INPUT" \
python3 - <<'PYEOF'
import os, sqlite3
conn = sqlite3.connect('/var/lib/shirobot.db')
c = conn.cursor()
c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
defaults = {
    'bot_token': os.environ['BOT_TOKEN_INPUT'],
    'admin_id': os.environ['ADMIN_ID_INPUT'],
    'admin_user': os.environ['ADMIN_USER_INPUT'],
    'domain': os.environ['DOMAIN_INPUT'],
    'price_per_day': '100',
    'default_ip_limit': '2',
    'default_quota': '100 GB',
}
for k, v in defaults.items():
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, v))
conn.commit()
conn.close()
print("Settings tersimpan di /var/lib/shirobot.db")
PYEOF

# SSH config banner check
if ! grep -q "Banner /etc/issue.net" /etc/ssh/sshd_config; then
    echo "Banner /etc/issue.net" >> /etc/ssh/sshd_config
fi

echo -e "${CYAN}[6/7] Mengaktifkan dan Merestart Seluruh Daemon Service...${NC}"
systemctl daemon-reload
systemctl unmask dropbear 2>/dev/null || true
systemctl enable dropbear ws-dropbear shirobot shiro-guard shiro-traffic
systemctl restart ssh dropbear ws-dropbear shirobot shiro-guard shiro-traffic

echo -e "${CYAN}[7/7] Verifikasi Port Layanan...${NC}"
ss -tulpn 2>/dev/null | grep -E ':(22|80|109|110|443|1445) ' || true

echo ""
echo -e "${GREEN}┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓${NC}"
echo -e "${GREEN}┃${WHITE}      ⚡ INSTALASI SHIRO VPN TELAH BERHASIL DILAKUKAN ⚡     ${GREEN}┃${NC}"
echo -e "${GREEN}┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛${NC}"
echo -e " 🌐 Domain Server  : ${WHITE}${DOMAIN_INPUT}${NC}"
echo -e " 🤖 Bot Telegram   : ${WHITE}Aktif & Terhubung${NC}"
echo -e " 👑 Admin Master   : ${WHITE}${ADMIN_USER_INPUT} (${ADMIN_ID_INPUT})${NC}"
echo -e " 📱 Akses Menu VPS : Ketik ${YELLOW}menu${NC} di terminal Anda"
echo -e "${GREEN}───────────────────────────────────────────────────────────────${NC}"
