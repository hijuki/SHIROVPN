#!/usr/bin/env python3
import sys
import sqlite3
import urllib.request
import json

DB_PATH = "/var/lib/shirobot.db"

def get_setting(key, default=""):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = c.fetchone()
        conn.close()
        return row[0] if row else default
    except:
        return default

def send_notif(message):
    token = get_setting("bot_token", "")
    chat_id = get_setting("notif_chat_id", "")
    thread_id = get_setting("notif_thread_id", "")
    
    if not token or not chat_id:
        print("ERROR: bot_token or notif_chat_id not set in DB settings.")
        return
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    if thread_id:
        data["message_thread_id"] = int(thread_id)
    
    payload = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
            if result.get("ok"):
                print("Notification sent successfully.")
            else:
                print(f"Telegram API error: {result}")
    except Exception as e:
        print(f"Error sending notification: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        send_notif(sys.argv[1])
    else:
        print("Usage: send_notif.py \"<message>\"")
