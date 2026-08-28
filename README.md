# ⚡ SHIRO VPN - Ultimate VPN Core & Telegram Store Bot Ecosystem

Ekosistem server VPN otomatis modern berbasis Linux dengan **16-Option Terminal HUD Menu**, **Multi-Protocol Provisioning Core (SSH, VLESS, VMESS, TROJAN, UDP ZiVPN, WireGuard)**, serta **Interactive Telegram Bot Store (@YourBotUsername)** yang dilengkapi auto-guard, multi-IP limiter, bandwidth quota tracking, auto-purge expired, dan full database backup/restore.

---

## 🌟 Fitur Utama

- 🚀 **Multi-Protocol Support (6 Protokol)**:
  - OpenSSH Direct & WebSocket SSL / TLS 1.3
  - Dropbear WS SSL (Port 109 & 110)
  - VLESS WS TLS & gRPC TLS
  - VMESS WS TLS
  - TROJAN WS TLS & gRPC TLS
  - UDP ZiVPN Gaming (Port 5667)
  - WireGuard Modern VPN (Port 51820)
- 🤖 **Interactive Telegram Store Bot**:
  - Menu berbasis Small-Caps Box Unicode
  - Isolasi akun user (Member hanya melihat akun miliknya sendiri)
  - Fitur **🔄 RENEW AKUN** langsung dari bot
  - Katalog server dynamic dengan **Auto-Detect ISP & Lokasi Geografis**
  - Instant response dashboard tanpa loading lag
  - Admin Master Panel dengan input manual / custom text untuk Harga, Quota (GB), & IP Limit
  - Notifikasi otomatis ke Telegram Supergroup / Forum Topics
- 🛡️ **Shiro Guard Daemon (`shiro-guard.service`)**:
  - Auto-purge akun trial (30 menit) & regular expired setiap 5 detik
  - Multi-IP monitoring & limiter real-time (auto-kill koneksi melebihi batas)
  - Quota limiter enforcement
- 🖥️ **Cyber Terminal HUD Menu (`/usr/bin/menu`)**:
  - 16 menu fungsional lengkap
  - Real-time CPU usage, RAM usage, & Disk Usage (`terpakai / ∞`)
  - Ookla Official Speedtest Benchmark dengan visual box
  - **Full Database & Config Backup/Restore (Format ZIP)** untuk migrasi antar VPS
- 🎨 **Symmetric HTML & Unicode Banners**:
  - SSH Terminal Login Banner (`/etc/issue.net`)
  - Dropbear HTML Server Message untuk client HTTP Custom, NetMod, dsb. (`/etc/dropbear_banner`)

---

## 🚀 Panduan Instalasi Awal (Fresh VPS Setup)

### 1. Persyaratan Sistem
- **OS**: Ubuntu 20.04 / 22.04 LTS (x86_64)
- **Port Akses**: Pastikan port `80`, `443`, `109`, `110`, `5667/udp`, `51820/udp` terbuka di firewall provider (Security Groups).
- **Domain**: Sudah dipointing (DNS A Record) ke IP Server VPS Anda.

---

### 2. Quick One-Line Automated Installer

Jalankan perintah berikut pada terminal VPS (sebagai user `root`):

```bash
apt-get update -y && apt-get install -y git curl
git clone https://github.com/hijuki/SHIROVPN.git /tmp/SHIROVPN
chmod +x /tmp/SHIROVPN/setup.sh
/tmp/SHIROVPN/setup.sh
```

Installer akan meminta Anda memasukkan:
1. **Domain VPS** (contoh: `your-domain.com`)
2. **Telegram Bot Token** (dari `@BotFather`)
3. **Telegram Admin Master User ID** (contoh: `1234567890`)
4. **Username Telegram Admin** (contoh: `@YourTelegramUsername`)

Semua dependensi sistem, binary, service daemon, konfigurasi, dan SQLite DB akan dipasang otomatis.

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

- **Owner / Creator**: [@YourTelegramUsername](https://t.me/Hillz126)
- **Repository**: [hijuki/SHIROVPN](https://github.com/hijuki/SHIROVPN)
- **Release Edition**: `SHIRO-ZNANDEV-PRO-2026`
