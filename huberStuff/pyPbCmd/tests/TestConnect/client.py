import socket
import sys
import os

def main():
    if len(sys.argv) < 2:
        print("Usage: python client.py <SERVER_IP> [PORT]")
        print("Examples:")
        print("  python client.py 192.168.1.50 5050")
        print("  python client.py 192.168.1.50")
        sys.exit(1)

    server_ip = sys.argv[1]
    server_port = int(sys.argv[2]) if len(sys.argv) > 2 else 5050

    print("=" * 70)
    print("REMOTE CLIENT")
    print("=" * 70)
    print(f"Connecting to {server_ip}:{server_port}...")

    try:
        conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        conn.connect((server_ip, server_port))

        welcome = conn.recv(1024).decode('utf-8', errors='ignore')
        print(f"\n{welcome}")
        print("=" * 70)

        interactive_shell(conn)

    except ConnectionRefusedError:
        print(f"[!] Failed to connect to {server_ip}:{server_port}")
        print("[!] Make sure server is running")
        sys.exit(1)
    except Exception as e:
        print(f"[!] Error: {e}")
        sys.exit(1)
    finally:
        try:
            conn.close()
        except:
            pass
        print("[!] Disconnected")

def interactive_shell(conn):
    print("\nCOMMANDS:")
    print("  exec <cmd>         - run CMD command")
    print("  upload <file>      - upload file to remote")
    print("  download <file>    - download file from remote")
    print("  runpy <file.py>    - run Python script")
    print("  info               - remote machine info")
    print("  exit               - disconnect")
    print()

    while True:
        try:
            cmd = input("cmd> ").strip()

            if not cmd:
                continue

            if cmd == "exit":
                conn.send(b"EXIT\n")
                print("[!] Disconnecting...")
                break

            elif cmd == "info":
                info_cmds = [
                    ("python -V", "Python Version:"),
                    ("where python", "Python Path:"),
                    ("echo %CD%", "Current Dir:"),
                ]
                for info_cmd, label in info_cmds:
                    conn.send(f"EXEC {info_cmd}\n".encode())
                    response = conn.recv(8192).decode('utf-8', errors='ignore')
                    print(f"{label}\n{response}")
                continue

            elif cmd.startswith("exec "):
                command = cmd[5:]
                conn.send(f"EXEC {command}\n".encode())
                response = recv_until_prompt(conn)
                print(response, end='')

            elif cmd.startswith("upload "):
                parts = cmd.split()
                if len(parts) < 2:
                    print("[!] Usage: upload <file>")
                    continue

                filepath = parts[1]

                if not os.path.exists(filepath):
                    print(f"[!] File not found: {filepath}")
                    continue

                filename = os.path.basename(filepath)
                filesize = os.path.getsize(filepath)

                conn.send(f"UPLOAD {filename} {filesize}\n".encode())

                with open(filepath, 'rb') as f:
                    file_data = f.read()
                    conn.sendall(file_data)

                response = conn.recv(1024).decode('utf-8', errors='ignore')
                print(f"[+] Uploaded: {filename} ({filesize} bytes)")
                if response:
                    print(response, end='')

            elif cmd.startswith("download "):
                parts = cmd.split()
                if len(parts) < 2:
                    print("[!] Usage: download <file>")
                    continue

                remote_file = parts[1]
                conn.send(f"DOWNLOAD {remote_file}\n".encode())

                header = conn.recv(1024).decode('utf-8', errors='ignore').strip()

                if header.startswith("ERROR"):
                    print(f"[!] {header}")
                    continue

                try:
                    filesize = int(header)
                except ValueError:
                    print(f"[!] File size error")
                    continue

                file_data = b""
                while len(file_data) < filesize:
                    chunk = conn.recv(min(4096, filesize - len(file_data)))
                    if not chunk:
                        break
                    file_data += chunk

                local_filename = f"downloaded_{os.path.basename(remote_file)}"
                with open(local_filename, 'wb') as f:
                    f.write(file_data)

                print(f"[+] Downloaded: {local_filename} ({filesize} bytes)")

            elif cmd.startswith("runpy "):
                parts = cmd.split()
                if len(parts) < 2:
                    print("[!] Usage: runpy <file.py>")
                    continue

                script_name = parts[1]
                conn.send(f"RUNPY {script_name}\n".encode())
                response = recv_until_prompt(conn)
                print(response, end='')

            else:
                print("[!] Unknown command")

        except BrokenPipeError:
            print("[!] Connection lost")
            break
        except Exception as e:
            print(f"[!] Error: {e}")

def recv_until_prompt(conn, timeout=5):
    conn.settimeout(timeout)
    response = b""

    try:
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            response += chunk
    except socket.timeout:
        pass
    finally:
        conn.settimeout(None)

    return response.decode('utf-8', errors='ignore')

if __name__ == "__main__":
    main()
