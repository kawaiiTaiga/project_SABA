
import socket
import threading
import json
import time
from typing import Dict, Any, Optional
from .utils import log
from .config import IPC_PORT
from .device_store import DeviceStore
from .command import CommandWaiter
from .protocol import ProtocolHandler

class IPCAgent:
    def __init__(self, device_store: DeviceStore, cmd_waiter: CommandWaiter, port_store, port_router):
        self.device_store = device_store
        self.cmd_waiter = cmd_waiter
        self.port_store = port_store
        self.port_router = port_router
        
        # Unified Protocol Handler
        self.protocol = ProtocolHandler(device_store, cmd_waiter, port_store, port_router)
        
        self._connections: Dict[str, socket.socket] = {}
        self._lock = threading.Lock()
        self.running = False
        self.server_socket = None

    def start(self):
        self.running = True
        thread = threading.Thread(target=self._server_loop, daemon=True)
        thread.start()
        log(f"[IPC] Started IPC Agent on port {IPC_PORT}")

    def _server_loop(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.server_socket.bind(("0.0.0.0", IPC_PORT))
            self.server_socket.listen(5)
        except Exception as e:
            log(f"[IPC] Failed to bind port {IPC_PORT}: {e}")
            return

        while self.running:
            try:
                client_sock, addr = self.server_socket.accept()
                log(f"[IPC] New connection from {addr}")
                threading.Thread(target=self._handle_client, args=(client_sock,), daemon=True).start()
            except Exception as e:
                log(f"[IPC] Accept error: {e}")
                time.sleep(1)

    def _handle_client(self, sock: socket.socket):
        device_id = None
        buffer = ""
        
        try:
            while True:
                data = sock.recv(4096)
                if not data:
                    break
                
                buffer += data.decode("utf-8")
                
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        msg = json.loads(line)
                        
                        # Process Message via Protocol Handler
                        topic = msg.get("topic", "")
                        payload = msg.get("payload", {})
                        
                        # DEBUG: Log all incoming messages (sample ports/data)
                        if "ports/data" in topic:
                            log(f"[IPC] RX ports/data: {topic} -> {payload}")
                        elif "status" not in topic:
                            log(f"[IPC] RX: {topic}")
                        
                        # Handle Logic
                        action, result_id = self.protocol.handle_message(topic, payload, protocol="ipc", device_id_hint=device_id)
                        
                        # Update Socket Map if Announce
                        if action == "announce" and result_id:
                             new_did = result_id
                             if new_did != device_id:
                                 device_id = new_did
                                 with self._lock:
                                     self._connections[device_id] = sock
                                 log(f"[IPC] Registered socket for device {device_id}")

                    except json.JSONDecodeError:
                        log(f"[IPC] Invalid JSON: {line}")
                    except Exception as e:
                        log(f"[IPC] Error processing message: {e}")

        except Exception as e:
            log(f"[IPC] Connection error: {e}")
        finally:
            if device_id:
                log(f"[IPC] Device {device_id} disconnected")
                with self._lock:
                    if self._connections.get(device_id) == sock:
                        del self._connections[device_id]
                
                # Explicitly mark as offline immediately
                try:
                    self.device_store.update_status(device_id, {"online": False})
                except Exception as e:
                    log(f"[IPC] Failed to mark offline: {e}")

            sock.close()

    def send_cmd(self, device_id: str, payload: Dict[str, Any]) -> bool:
        """Send a JSON command string with newline delimiter to the device socket"""
        with self._lock:
            sock = self._connections.get(device_id)
        
        if not sock:
            log(f"[IPC] No socket connection for {device_id}")
            return False
            
        try:
            data = json.dumps(payload) + "\n"
            sock.sendall(data.encode("utf-8"))
            return True
        except Exception as e:
            log(f"[IPC] Failed to send cmd to {device_id}: {e}")
            return False

    def send_port_set(self, device_id: str, port_name: str, value: float) -> bool:
        """Send a port set command via IPC"""
        log(f"[IPC] DEBUG: Sending PortSet to {device_id}: {port_name}={value}")
        payload = {
            "type": "ports.set",
            "port": port_name,
            "value": value
        }
        return self.send_cmd(device_id, payload)
