# ⚡ SHIRO VPN - Ultimate VPN Core & Telegram Store Bot Ecosystem

Ekosistem server VPN otomatis modern berbasis Linux dengan **16-Option Terminal HUD Menu**, **Multi-Protocol Provisioning Core (SSH, VLESS, VMESS, TROJAN, UDP ZiVPN, WireGuard)**, serta **Interactive Telegram Bot Store (@YourBotUsername)** yang dilengkapi auto-guard, multi-IP limiter, bandwidth quota tracking, auto-purge expired, dan full database backup/restore.

---

## 🌟 Fitur Utama

- 🚀 **Multi-Protocol Support (6 Protokol)**:
  - OpenSSH Direct & WebSocket SSL / TLS 1.3 (Port 22, 80, 443)
  - Dropbear WS SSL (Port 109 & 110)
  - BadVPN UDPGW Gaming & Voice (Port 7100-7900 / 7300)
  - VLESS WS TLS & gRPC TLS
  - VMESS WS TLS
  - TROJAN WS TLS & gRPC TLS
  - UDP ZiVPN Gaming (Port 5667)
  - WireGuard Modern VPN (Port 51820)
- 🤖 **Interactive Telegram Store Bot**:
  - Auto Create All-in-One VIP Card (SSH, VLESS, VMESS, TROJAN simultan)
  - Anti-Spam Clean Share Card dengan Deep-Link Auto-Deliver
  - 1-Click Total Account Purge dari panel admin
  - Notifikasi instan khusus saat Pengguna Baru menekan `/start`
  - Auto-Renew Saldo otomatis & tombol pengingat masa aktif H-1
  - Panic / Maintenance Mode switcher
  - Segmented Broadcast (Semua User vs Khusus User Aktif)
  - Isolasi akun user (Member hanya melihat akun miliknya)
  - Auto-detect ISP & Lokasi Geografis server
  - Admin Master Panel dengan input custom Text/Interactive Wizard
- 🛡️ **Shiro Guard Daemon (`shiro-guard.service`)**:
  - Auto-Heal Sentinel: memonitor dan me-restart otomatis semua service core jika crash
  - Multi-IP Limiter 2-Strike akurat dengan Grace Period 30 detik (menghitung unique client inbound IP)
  - H-1 Expiration Checker & Auto-Deduct Balance Renew
  - Auto-Purge expired & quota tracking
  - Log rotation & auto-truncation file log > 50MB
- 🖥️ **Cyber Terminal HUD Menu (`/usr/bin/menu`)**:
  - 16 menu fungsional lengkap
  - Real-time CPU, RAM, & Disk Usage
  - Ookla Official Speedtest Benchmark resmi
  - 1-Click Backup & Auto-Detect Restore dari file ZIP terbaru
- 🎨 **HTML Symmetric Banners**:
  - Dropbear & OpenSSH HTML Centered Multi-Color Banner (`/etc/issue.net`, `/etc/dropbear_banner`)

---

## 🚀 Panduan Instalasi Awal (Fresh VPS Setup)

### 1. Persyaratan Sistem
- **OS**: Ubuntu 20.04 / 22.04 / 24.04 / 26.04 LTS (x86_64)
- **Port Akses**: Pastikan port `80`, `443`, `109`, `110`, `7300/udp`, `5667/udp`, `51820/udp` terbuka di firewall VPS.
- **Domain**: Sudah dipointing (DNS A Record) ke IP Server VPS Anda.

---

### 2. Quick One-Line Automated Installer

Jalankan perintah berikut pada terminal VPS baru (sebagai user `root`):

```bash
apt-get update -y && apt-get install -y git curl
git clone https://github.com/hijuki/SHIROVPN.git /tmp/SHIROVPN
chmod +x /tmp/SHIROVPN/setup.sh
/tmp/SHIROVPN/setup.sh
```

Installer akan memandu konfigurasi:
1. **Domain VPS** (contoh: `sg1-shiro.my.id`)
2. **Telegram Bot Token** (dari `@BotFather`)
3. **Telegram Admin Master User ID** (contoh: `6343065438`)
4. **Username Telegram Admin** (contoh: `@Hillz126`)

Semua dependensi sistem, binary BadVPN UDPGW, sertifikat SSL Let's Encrypt, cron/logrotate, service daemon, konfigurasi, dan SQLite DB akan dipasang otomatis.

---

## 💻 Cara Menggunakan Terminal Menu VPS

Cukup ketik perintah berikut pada terminal SSH Anda:

```bash
menu
```

### Daftar Menu:
```
┌────────────────────── MAIN MENU ────────────────────────────┐
 [1]  SSH & WS SSL          [9]  BOT MANAGER
 [2]  VLESS TLS / gRPC      [10] CONNECT TOPIC FORUM
 [3]  VMESS TLS             [11] CHANGE BOT TOKEN
 [4]  TROJAN TLS / gRPC     [12] TEST NOTIF FORUM
 [5]  UDP ZIVPN GAMING      [13] BACKUP & RESTORE
 [6]  WIREGUARD VPN         [14] SPEEDTEST NETWORK
 [7]  REVOKE USER           [15] RESTART ALL SERVICES
 [8]  LIST ALL ACCOUNTS     [16] RENEW USER ACCOUNT
 [x]  EXIT MENU
└─────────────────────────────────────────────────────────────┘
```

---

## 📦 Cara Migrasi / Backup & Restore Data

1. **Membuat Backup di VPS Lama**:
   - Ketik `menu` -> Pilih menu `[13] BACKUP & RESTORE` -> Pilih opsi `[1]`.
   - File zip backup lengkap akan tersimpan di `/root/backup_shiro_YYYYMMDD_HHMMSS.zip`.
   - Unduh file zip tersebut ke komputer Anda.

2. **Restore di VPS Baru**:
   - Setup fresh VPS menggunakan `setup.sh`.
   - Upload file zip backup ke VPS baru (misal di `/root/backup.zip`).
   - Ketik `menu` -> Pilih menu `[13] BACKUP & RESTORE` -> Pilih opsi `[2]` -> Masukkan path `/root/backup.zip`.
   - Seluruh data user, database akun, token bot, dan konfigurasi lama akan otomatis aktif seketika tanpa kehilangan data.

---

## 👑 Lisensi & Pengembang

- **Owner / Creator**: [@YourTelegramUsername](https://t.me/YourTelegramUsername)
- **Repository**: [hijuki/SHIROVPN](https://github.com/hijuki/SHIROVPN)
- **Release Edition**: `SHIRO-ZNANDEV-PRO-2026`
