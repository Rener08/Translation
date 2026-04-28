#!/usr/bin/env python3
import socket
import sys

COMMON_PORTS = [7890, 1080, 10809, 8080, 9090, 7897, 6152, 6153]

def is_port_open(port, host="127.0.0.1", timeout=1):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False

def main():
    print("Scanning common proxy ports on 127.0.0.1...")
    print("=" * 50)
    open_ports = []
    for port in COMMON_PORTS:
        if is_port_open(port):
            print(f"  Port {port:5d}: OPEN")
            open_ports.append(port)
        else:
            print(f"  Port {port:5d}: closed")
    
    print()
    if open_ports:
        print(f"Open ports found: {open_ports}")
        print("\nMost likely proxy port:", open_ports[0])
        print(f"\nAdd this to your .env file:")
        print(f"  YTDLP_PROXY=http://127.0.0.1:{open_ports[0]}")
        print("\nOr run this in terminal before testing:")
        print(f"  export YTDLP_PROXY=http://127.0.0.1:{open_ports[0]}")
    else:
        print("No proxy ports detected on common ports.")
        print("Please check if your proxy software is running.")
        print("\nIf you know your proxy port, add it to .env:")
        print("  YTDLP_PROXY=http://127.0.0.1:YOUR_PORT")
        sys.exit(1)

if __name__ == "__main__":
    main()
