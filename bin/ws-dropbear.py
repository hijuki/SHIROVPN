#!/usr/bin/env python3
import socket
import select
import sys
import threading

LISTEN_PORT = 1445
TARGET_PORT = 109
BUFFER_SIZE = 8192

def handle_client(client_socket):
    try:
        # Read the initial HTTP Request (e.g. GET /ssh-ws HTTP/1.1 ...)
        client_socket.settimeout(30)
        req_data = client_socket.recv(BUFFER_SIZE)
        if not req_data:
            client_socket.close()
            return
        
        # Connect to local Dropbear SSH
        target_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        target_socket.connect(('127.0.0.1', TARGET_PORT))
        
        # Respond with HTTP 101 Switching Protocols
        resp = b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n\r\n"
        client_socket.sendall(resp)
        
        # Read Dropbear banner and forward
        sockets = [client_socket, target_socket]
        while True:
            r, _, _ = select.select(sockets, [], [], 60)
            if not r:
                break
            for s in r:
                data = s.recv(BUFFER_SIZE)
                if not data:
                    return
                if s is client_socket:
                    target_socket.sendall(data)
                else:
                    client_socket.sendall(data)
    except Exception as e:
        pass
    finally:
        try:
            client_socket.close()
        except Exception:
            pass
        try:
            target_socket.close()
        except Exception:
            pass

def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', LISTEN_PORT))
    server.listen(100)
    print(f"WS-SSH Proxy listening on port {LISTEN_PORT} -> {TARGET_PORT}")
    while True:
        client_socket, _ = server.accept()
        t = threading.Thread(target=handle_client, args=(client_socket,))
        t.daemon = True
        t.start()

if __name__ == '__main__':
    main()
