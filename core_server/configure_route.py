import requests
import sys

def scan_ports():
    payload = {
        "source": "ipc_test_device/mic_level", 
        "target": "ipc_test_device/motor_speed", 
        "enabled": True
    }
    
    # Try typical ports
    ports = range(8080, 8090)
    
    for port in ports:
        url = f"http://localhost:{port}/routing/connect"
        print(f"Scanning port {port}...", end=" ", flush=True)
        try:
            resp = requests.post(url, json=payload, timeout=0.5)
            if resp.status_code == 200:
                print(f"SUCCESS! \nResponse: {resp.json()}")
                return
            else:
                print(f"Active but returned {resp.status_code}")
        except requests.exceptions.ConnectionError:
            print("Refused")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    scan_ports()
