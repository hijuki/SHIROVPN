#!/bin/bash
# ==============================================================================
# SHIROVPN - Quick Recovery & Core Restorer Script
# ==============================================================================
set -e

echo "🔧 Memulihkan konfigurasi Xray Core & Service..."

# 1. Restore Clean Working Xray Config
cat << 'EOF' > /usr/local/etc/xray/config.json
{
  "log": {
    "access": "/var/log/xray/access.log",
    "error": "/var/log/xray/error.log",
    "loglevel": "warning"
  },
  "inbounds": [
    {
      "tag": "main-tls-fallback",
      "port": 443,
      "protocol": "vless",
      "settings": {
        "clients": [
          {
            "id": "08e40df8-f8fb-4748-991c-99b67cd31c19",
            "flow": "xtls-rprx-vision",
            "email": "u79eaf3"
          }
        ],
        "decryption": "none",
        "fallbacks": [
          {
            "path": "/vless",
            "dest": 10001,
            "xver": 1
          },
          {
            "path": "/vmess",
            "dest": 10002,
            "xver": 1
          },
          {
            "path": "/trojan-ws",
            "dest": 10003,
            "xver": 1
          },
          {
            "path": "/ss-ws",
            "dest": 10004,
            "xver": 1
          },
          {
            "path": "/ssh-ws",
            "dest": 1445,
            "xver": 0
          },
          {
            "alpn": "h2",
            "dest": 10005,
            "xver": 0
          },
          {
            "dest": 109,
            "xver": 0
          }
        ]
      },
      "streamSettings": {
        "network": "tcp",
        "security": "tls",
        "tlsSettings": {
          "alpn": [
            "h2",
            "http/1.1"
          ],
          "certificates": [
            {
              "certificateFile": "/usr/local/etc/xray/xray.crt",
              "keyFile": "/usr/local/etc/xray/xray.key"
            }
          ]
        }
      }
    },
    {
      "tag": "vless-ws-inbound",
      "port": 10001,
      "listen": "127.0.0.1",
      "protocol": "vless",
      "settings": {
        "clients": [
          {
            "id": "08e40df8-f8fb-4748-991c-99b67cd31c19",
            "email": "u79eaf3"
          },
          {
            "id": "5509996c-baeb-4015-a4f9-245888c5a356",
            "email": "admin",
            "alterId": 0
          }
        ],
        "decryption": "none"
      },
      "streamSettings": {
        "network": "ws",
        "security": "none",
        "wsSettings": {
          "acceptProxyProtocol": true,
          "path": "/vless"
        }
      }
    },
    {
      "tag": "vmess-ws-inbound",
      "port": 10002,
      "listen": "127.0.0.1",
      "protocol": "vmess",
      "settings": {
        "clients": [
          {
            "id": "61de23f6-4eb7-43f4-88fb-7a8f749828d9"
          }
        ]
      },
      "streamSettings": {
        "network": "ws",
        "security": "none",
        "wsSettings": {
          "acceptProxyProtocol": true,
          "path": "/vmess"
        }
      }
    },
    {
      "tag": "trojan-ws-inbound",
      "port": 10003,
      "listen": "127.0.0.1",
      "protocol": "trojan",
      "settings": {
        "clients": [
          {
            "password": "alok",
            "email": "hillz"
          }
        ]
      },
      "streamSettings": {
        "network": "ws",
        "security": "none",
        "wsSettings": {
          "acceptProxyProtocol": true,
          "path": "/trojan-ws"
        }
      }
    },
    {
      "tag": "ss-ws-inbound",
      "port": 10004,
      "listen": "127.0.0.1",
      "protocol": "shadowsocks",
      "settings": {
        "method": "aes-128-gcm",
        "password": "61de23f6-4eb7-43f4-88fb-7a8f749828d9",
        "clients": [
          {
            "method": "aes-128-gcm",
            "password": "61de23f6-4eb7-43f4-88fb-7a8f749828d9"
          }
        ]
      },
      "streamSettings": {
        "network": "ws",
        "security": "none",
        "wsSettings": {
          "acceptProxyProtocol": true,
          "path": "/ss-ws"
        }
      }
    },
    {
      "tag": "vless-grpc-inbound",
      "port": 10005,
      "listen": "127.0.0.1",
      "protocol": "vless",
      "settings": {
        "clients": [
          {
            "id": "08e40df8-f8fb-4748-991c-99b67cd31c19",
            "email": "u79eaf3"
          }
        ],
        "decryption": "none"
      },
      "streamSettings": {
        "network": "grpc",
        "grpcSettings": {
          "serviceName": "vless-grpc"
        }
      }
    }
  ],
  "outbounds": [
    {
      "protocol": "freedom",
      "tag": "direct"
    },
    {
      "protocol": "blackhole",
      "tag": "blocked"
    }
  ]
}
EOF

# 2. Stop conflicting shiro-traffic service
systemctl stop shiro-traffic 2>/dev/null || true
systemctl disable shiro-traffic 2>/dev/null || true

# 3. Clean IPTables OUTPUT Chains
iptables -F OUTPUT 2>/dev/null || true
iptables -P OUTPUT ACCEPT 2>/dev/null || true

# 4. Restart All Core VPN Services
systemctl restart xray dropbear ws-dropbear zivpn wg-quick@wg0 ssh shirobot shiro-guard

echo "✅ SELURUH SERVICE BERHASIL DIPULIHKAN!"
