from saba_ipc import SabaIPCClient
import time

# 1. Initialize Agent with Config
client = SabaIPCClient(
    device_id="ipc_agent_test",
    device_name="IPC Agent Device",
    port=8085,
    outports=[{"name": "mic_level", "data_type": "float", "description": "Microphone Level"}],
    inports=[{"name": "motor_speed", "data_type": "float", "description": "Motor Speed Control"}]
)

# 2. Register Tools (Easy!)
@client.tool(description="Echoes back the input message")
def ipc_echo(message: str) -> str:
    print(f"   >>> Echo tool called with: {message}")
    return f"Echo from Agent: {message}"

@client.tool()
def add(a: int, b: int) -> int:
    """Adds two numbers"""
    return a + b

# 4. Handle Port Data (RECEIVING from Server -> InPort)
def on_motor_data(port: str, value: float):
    print(f"   >>> [INPORT] Received: {port} = {value}")

client.on_inport_data(on_motor_data)

# 5. Start!
print("Starting IPC Agent...")
client.start(daemon=True)

# 6. Simulate Main Loop
try:
    val = 0.0
    while True:
        # === SENDING DATA (Agent -> OutPort) ===
        val = (val + 0.1) % 1.0
        client.set_port("mic_level", val)
        print(f"   <<< [OUTPORT] Sent: mic_level = {val:.1f}")
        
        time.sleep(1)
except KeyboardInterrupt:
    print("Stopping...")
