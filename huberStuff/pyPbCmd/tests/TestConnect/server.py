import socket
import subprocess
import os
import sys
import platform

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 5050
HOST = "0.0.0.0"

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(1)

    local_ip = get_local_ip()
    hostname = platform.node()
    username = os.getenv("USERNAME", "unknown")

    print("=" * 70)
    print("REMOTE SERVER")
    print("=" * 70)
    print(f"Machine: {username}@{hostname}")
    print(f"Listening on {local_ip}:{PORT}")
    print()
    print(f"Connection: python client.py {local_ip} {PORT}")
    print("=" * 70)
    print("Waiting for connection... (Ctrl+C to exit)")
    print()

    try:
        while True:
            try:
                conn, addr = server.accept()
                print(f"\n[+] Connected: {addr[0]}:{addr[1]}")
                print("-" * 70)

                welcome = f"Welcome to {hostname}\n"
                conn.send(welcome.encode())

                handle_client(conn, addr)

                print(f"[-] Client {addr[0]} disconnected")
                print()

            except Exception as e:
                print(f"[ERROR] {e}")

    except KeyboardInterrupt:
        print("\n[!] Server stopped.")
    finally:
        server.close()

def handle_client(conn, addr):
    while True:
        try:
            header = conn.recv(1024).decode('utf-8', errors='ignore').strip()

            if not header:
                break

            parts = header.split(None, 2)
            command = parts[0] if parts else ""

            print(f"> {header}")

            if command == "EXIT":
                break

            elif command == "EXEC":
                if len(parts) < 2:
                    continue

                cmd = " ".join(parts[1:])
                output = execute_cmd(cmd)
                conn.sendall(output.encode('utf-8', errors='ignore'))

            elif command == "UPLOAD":
                if len(parts) < 3:
                    continue

                filename = parts[1]
                try:
                    filesize = int(parts[2])
                except ValueError:
                    continue

                file_data = b""
                while len(file_data) < filesize:
                    chunk = conn.recv(min(4096, filesize - len(file_data)))
                    if not chunk:
                        break
                    file_data += chunk

                try:
                    with open(filename, 'wb') as f:
                        f.write(file_data)
                    conn.send(b"[ok]\n")
                    print(f"[+] File uploaded: {filename} ({filesize} bytes)")
                except Exception as e:
                    conn.send(f"[ERROR: {e}]\n".encode())

            elif command == "DOWNLOAD":
                if len(parts) < 2:
                    continue

                filename = parts[1]

                try:
                    if not os.path.exists(filename):
                        conn.send(b"ERROR: File not found\n")
                        print(f"[-] File not found: {filename}")
                        continue

                    filesize = os.path.getsize(filename)
                    conn.send(f"{filesize}\n".encode())

                    with open(filename, 'rb') as f:
                        file_data = f.read()
                        conn.sendall(file_data)

                    print(f"[+] File sent: {filename} ({filesize} bytes)")

                except Exception as e:
                    conn.send(f"ERROR: {e}\n".encode())

            elif command == "RUNPY":
                if len(parts) < 2:
                    continue

                script_name = parts[1]

                if not os.path.exists(script_name):
                    output = f"[ERROR: Script not found: {script_name}]\n"
                    conn.send(output.encode())
                    continue

                output = execute_cmd(f"python {script_name}")
                conn.sendall(output.encode('utf-8', errors='ignore'))

            else:
                output = f"[ERROR: Unknown command: {command}]\n"
                conn.send(output.encode())

        except BrokenPipeError:
            break
        except Exception as e:
            print(f"[ERROR] {e}")
            try:
                conn.send(f"[ERROR: {e}]\n".encode())
            except:
                break

def execute_cmd(cmd):
    try:
        output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT, timeout=30)
        return output.decode('utf-8', errors='ignore')
    except subprocess.CalledProcessError as e:
        return e.output.decode('utf-8', errors='ignore')
    except subprocess.TimeoutExpired:
        return "[ERROR: Command timeout (30s)]\n"
    except Exception as e:
        return f"[ERROR: {e}]\n"

if __name__ == "__main__":
    main()
