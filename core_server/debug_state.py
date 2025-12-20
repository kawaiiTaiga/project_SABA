import requests
import json

BASE_URL = "http://localhost:8083"

def check():
    # 1. Check Device
    try:
        url = f"{BASE_URL}/devices/ipc_test_device"
        print(f"GET {url}")
        resp = requests.get(url, timeout=1)
        if resp.status_code == 200:
            d = resp.json()
            print(f"[DEVICE] Protocol: {d.get('protocol')}")
            print(f"[DEVICE] Online: {d.get('online')}")
        else:
            print(f"[DEVICE] Not Found ({resp.status_code})")
    except Exception as e:
        print(f"[DEVICE] Error: {e}")

    # 2. Check Routing
    try:
        url = f"{BASE_URL}/routing/connections"
        print(f"GET {url}")
        resp = requests.get(url, timeout=1)
        conns = resp.json()
        found = False
        for c in conns:
            if c['source'] == "ipc_test_device/mic_level" and c['target'] == "ipc_test_device/motor_speed":
                print(f"[ROUTING] FOUND: {c}")
                found = True
        if not found:
            print("[ROUTING] Route NOT found")
    except Exception as e:
        print(f"[ROUTING] Error: {e}")

if __name__ == "__main__":
    check()
