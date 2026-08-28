#!/usr/bin/env python3
import sqlite3
import re

def format_bytes(b):
    if b < 1024:
        return f"{b} B"
    elif b < 1024**2:
        return f"{b/1024:.1f} KB"
    elif b < 1024**3:
        return f"{b/(1024**2):.1f} MB"
    else:
        return f"{b/(1024**3):.2f} GB"

def get_account_quota_info(username):
    conn = sqlite3.connect('/var/lib/shirobot.db')
    c = conn.cursor()
    c.execute("SELECT quota_gb, used_bytes FROM accounts WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    if not row:
        return "Unlimited", "0 B", "0 B / Unlimited", 100
    
    quota_str, used_bytes = row[0], row[1] or 0
    used_fmt = format_bytes(used_bytes)
    
    if not quota_str or "unlimited" in str(quota_str).lower():
        return "Unlimited", used_fmt, f"{used_fmt} / Unlimited", 100
    
    m = re.search(r'(\d+)', str(quota_str))
    if m:
        total_gb = float(m.group(1))
        total_bytes = total_gb * (1024**3)
        used = float(used_bytes)
        ratio_str = f"{used_fmt} / {total_gb:.0f} GB"
        left_bytes = max(0.0, total_bytes - used)
        pct = max(0, min(100, int((left_bytes / total_bytes) * 100)))
        return f"{total_gb:.0f} GB", used_fmt, ratio_str, pct
    
    return str(quota_str), used_fmt, f"{used_fmt} / {quota_str}", 100

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(get_account_quota_info(sys.argv[1]))
