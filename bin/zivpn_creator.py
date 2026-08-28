#!/usr/bin/env python3
import sys
import os

USERS_DB = "/etc/zivpn/users.db"

def list_users():
    if not os.path.exists(USERS_DB):
        return []
    with open(USERS_DB, "r") as f:
        return [line.strip().split(":") for line in f if ":" in line.strip()]

def add_user(username, password):
    os.makedirs(os.path.dirname(USERS_DB), exist_ok=True)
    users = list_users()
    users = [u for u in users if u[0] != username]
    users.append([username, password])
    with open(USERS_DB, "w") as f:
        for u in users:
            f.write(f"{u[0]}:{u[1]}\n")
    os.system("systemctl restart zivpn 2>/dev/null")
    print(f"ZiVPN user {username} created.")

def del_user(username):
    if not os.path.exists(USERS_DB):
        return
    users = list_users()
    users = [u for u in users if u[0] != username]
    with open(USERS_DB, "w") as f:
        for u in users:
            f.write(f"{u[0]}:{u[1]}\n")
    os.system("systemctl restart zivpn 2>/dev/null")
    print(f"ZiVPN user {username} deleted.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: zivpn_creator.py [add <user> <pass> | del <user> | list]")
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "add" and len(sys.argv) >= 4:
        add_user(sys.argv[2], sys.argv[3])
    elif cmd == "del" and len(sys.argv) >= 3:
        del_user(sys.argv[2])
    elif cmd == "list":
        for u in list_users():
            print(f"{u[0]}:{u[1]}")
