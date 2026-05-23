import sys
import socket
import json
from pathlib import Path

def main():
    if len(sys.argv) < 5:
        print("Usage: python3 inject_verdict.py <session_id> <layer> <claim_id> <verdict>")
        sys.exit(1)
    
    session_id, layer, claim_id, verdict = sys.argv[1:5]
    socket_path = Path(f"/tmp/swarm-mediator-{session_id}.sock")
    
    if not socket_path.exists():
        print(f"[-] Socket not found: {socket_path}. Is the daemon running for session {session_id}?")
        sys.exit(1)
        
    payload = {
        "action": "fact_inject",
        "session_id": session_id,
        "layer": layer,
        "claim_id": claim_id,
        "verdict": verdict
    }
    
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(str(socket_path))
        sock.sendall(json.dumps(payload).encode("utf-8"))
        sock.shutdown(socket.SHUT_WR)
        response_data = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            response_data += chunk
        sock.close()
        
        response = json.loads(response_data.decode("utf-8"))
        if response.get("status") == "ACK":
            print(f"[+] Verdict '{verdict}' successfully injected for claim '{claim_id}'.")
        else:
            print(f"[-] Daemon responded with error: {response.get('reason')}")
            
    except Exception as e:
        print(f"[-] Failed to inject fact: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
