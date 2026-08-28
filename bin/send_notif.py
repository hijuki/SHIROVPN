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
    except Exception:
        return default

def send_notif(message, direct_user_id=None, reply_markup=None):
    token = get_setting("bot_token", "")
    chat_id = get_setting("notif_chat_id", "")
    thread_id = get_setting("notif_thread_id", "")
    
    if not token:
        return
    
    # 1. Send to notification group / forum
    if chat_id:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        if thread_id:
            data["message_thread_id"] = int(thread_id)
        if reply_markup:
            data["reply_markup"] = reply_markup
        
        try:
            payload = json.dumps(data).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                pass
        except Exception as e:
            print(f"Error sending group notification: {e}")

    # 2. Send directly to user DM if direct_user_id provided
    if direct_user_id:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = {
            "chat_id": direct_user_id,
            "text": message,
            "parse_mode": "HTML"
        }
        if reply_markup:
            data["reply_markup"] = reply_markup
        
        try:
            payload = json.dumps(data).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                pass
        except Exception:
            pass

if __name__ == "__main__":
    if len(sys.argv) > 1:
        send_notif(sys.argv[1])
    else:
        print("Usage: send_notif.py \"<message>\"")
