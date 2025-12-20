
import time
import random
from saba_ipc import SabaIPCClient

# Configuration
DEVICE_ID = "ipc_test_device"
HOST = "127.0.0.1"
PORT = 8085

# Initialize Client
client = SabaIPCClient(
    device_id=DEVICE_ID,
    device_name="IPC Test Device",
    host=HOST,
    port=PORT
)

# Define Tool
@client.tool(description="Echoes back the input message")
def ipc_echo(message: str):
    print(f"   [TOOL] ipc_echo called with: {message}")
    # Simulate work to prove async behavior
    time.sleep(2) 
    print(f"   [TOOL] ipc_echo finished")
    return f"Echo from IPC: {message}"

# Define Ports
client.add_outport("mic_level", "float", "Microphone Level")
client.add_inport("motor_speed", "float", "Motor Speed Control")

# Define InPort Callback
def on_motor_speed(port, value):
    print(f"   [PORT] Received {port} = {value}")

client.on_inport_data(on_motor_speed)

if __name__ == "__main__":
    print("[TEST] Starting IPC Client...")
    
    # Start background threads
    rx_thread = client.start(daemon=True)
    
    try:
        # Simulate Main Loop (e.g. collecting sensor data)
        while True:
            # Simulate high-frequency data
            level = random.random()
            print(f"[TEST] Sending mic_level={level:.2f}")
            client.set_port("mic_level", level)
            
            time.sleep(0.1) # 10Hz
            
    except KeyboardInterrupt:
        print("[TEST] Stopping...")
        client.stop()
