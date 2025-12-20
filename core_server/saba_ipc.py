import socket
import json
import time
import threading
import inspect
import queue
from typing import Dict, Any, Callable, Optional, List, Union

class SabaIPCClient:
    def __init__(self, device_id: str, device_name: str = None, host: str = "127.0.0.1", port: int = 8085, 
                 outports: List[Dict[str, str]] = None, inports: List[Dict[str, str]] = None):
        self.device_id = device_id
        self.device_name = device_name or device_id
        self.host = host
        self.port = port
        
        self.tools: Dict[str, Dict[str, Any]] = {}
        self.tool_callbacks: Dict[str, Callable] = {}
        self.outports: List[Dict[str, Any]] = outports or []
        self.inports: List[Dict[str, Any]] = inports or []
        self.on_port_data_callback: Optional[Callable[[str, float], None]] = None
        
        self.running = False
        self.sock: Optional[socket.socket] = None
        
        # Concurrency
        self.msg_queue = queue.Queue(maxsize=1000) # Rx Queue
        
        # Tx Queue for non-blocking sends
        self.tx_queue = queue.Queue(maxsize=2000) 
        
        self.rx_thread: Optional[threading.Thread] = None
        self.tx_thread: Optional[threading.Thread] = None
        self.process_thread: Optional[threading.Thread] = None

    def tool(self, name: str = None, description: str = None):
        """Decorator to register a function as an MCP tool"""
        def decorator(func):
            tool_name = name or func.__name__
            tool_desc = description or func.__doc__ or "No description"
            
            # Auto-generate schema from type hints (simple version)
            sig = inspect.signature(func)
            params = {}
            required = []
            
            for param_name, param in sig.parameters.items():
                param_type = "string"
                if param.annotation == int: param_type = "integer"
                elif param.annotation == float: param_type = "number"
                elif param.annotation == bool: param_type = "boolean"
                elif param.annotation == dict: param_type = "object"
                elif param.annotation == list: param_type = "array"
                
                params[param_name] = {"type": param_type}
                if param.default == inspect.Parameter.empty:
                    required.append(param_name)
            
            tool_def = {
                "name": tool_name,
                "description": tool_desc,
                "parameters": {
                    "type": "object",
                    "properties": params,
                    "required": required
                }
            }
            
            self.tools[tool_name] = tool_def
            self.tool_callbacks[tool_name] = func
            return func
        return decorator

    def add_outport(self, name: str, data_type: str = "float", description: str = ""):
        self.outports.append({
            "name": name,
            "data_type": data_type,
            "description": description
        })

    def add_inport(self, name: str, data_type: str = "float", description: str = ""):
        self.inports.append({
            "name": name,
            "data_type": data_type,
            "description": description
        })
        
    def on_inport_data(self, callback: Callable[[str, float], None]):
        """Register callback for InPort data: callback(port_name, value)"""
        self.on_port_data_callback = callback

    def set_port(self, name: str, value: float):
        """
        Publish value to OutPort.
        NON-BLOCKING: Drops message if queue is full.
        """
        msg = {
            "topic": f"mcp/dev/{self.device_id}/ports/data",
            "payload": {
                "port": name,
                "value": value
            }
        }
        try:
            # put_nowait raises Full if full. We silently drop/ignore.
            self.tx_queue.put_nowait(msg)
        except queue.Full:
            print(f"[IPC] WARNING: Tx Queue Full (Dropping {name})")

    def start(self, daemon=False):
        """Start the client background threads"""
        self.running = True
        
        # 1. Start RX Thread (Socket -> Queue)
        self.rx_thread = threading.Thread(target=self._rx_loop, name="IPC-Rx", daemon=daemon)
        self.rx_thread.start()
        
        # 2. Start TX Thread (Queue -> Socket)
        self.tx_thread = threading.Thread(target=self._tx_loop, name="IPC-Tx", daemon=daemon)
        self.tx_thread.start()
        
        # 3. Start Processor Thread (Queue -> Dispatch)
        self.process_thread = threading.Thread(target=self._processor_loop, name="IPC-Process", daemon=daemon)
        self.process_thread.start()
        
        print(f"[IPC] Client started for {self.device_id}")
        return self.rx_thread

    def stop(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass

    def _send_system_msg(self, data: Dict[str, Any]):
        """
        Send critical system message (Announce, Reply).
        Uses blocking put with timeout to ensure delivery if possible.
        """
        try:
            self.tx_queue.put(data, timeout=1.0)
        except queue.Full:
            print("[IPC] Critical: Tx Queue full, system message dropped!")

    def _connect(self):
        """Establish connection and send Announces"""
        while self.running:
            try:
                print(f"[IPC] Connecting to {self.host}:{self.port}...")
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.connect((self.host, self.port))
                self.sock = s
                print(f"[IPC] Connected!")

                # 1. Announce Device (Tools)
                announce_msg = {
                    "topic": f"mcp/dev/{self.device_id}/announce",
                    "payload": {
                        "name": self.device_name,
                        "version": "1.0.0",
                        "tools": list(self.tools.values())
                    }
                }
                
                self._send_system_msg(announce_msg)
                
                # 2. Announce Ports
                if self.outports or self.inports:
                    ports_msg = {
                        "topic": f"mcp/dev/{self.device_id}/ports/announce",
                        "payload": {
                            "outports": self.outports,
                            "inports": self.inports
                        }
                    }
                    self._send_system_msg(ports_msg)
                
                return True
                
            except Exception as e:
                print(f"[IPC] Connection failed: {e}. Retrying in 3s...")
                time.sleep(3)
        return False

    def _rx_loop(self):
        """Continuously read from socket and push to queue"""
        buffer = ""
        
        while self.running:
            if not self.sock:
                if not self._connect():
                    break
            
            try:
                self.sock.settimeout(5.0)
                try:
                    data = self.sock.recv(4096)
                except socket.timeout:
                    
                    hb = {
                        "topic": f"mcp/dev/{self.device_id}/status",
                        "payload": {"online": True, "uptime": int(time.time())}
                    }
                    self._send_system_msg(hb)
                    continue
                except ConnectionError:
                    raise

                if not data:
                    raise ConnectionResetError("Server closed")
                
                # print(f"[IPC RAW] {len(data)}B: {data}")
                buffer += data.decode("utf-8")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line: continue
                    
                    try:
                        cmd = json.loads(line)
                        # print(f"[IPC DEBUG] Rx: {cmd}") # Uncomment for heavy debugging
                        if cmd.get("type") == "ports.set":
                             print(f"[IPC DEBUG] RX PortSet: {cmd}")
                        
                        if self.msg_queue.full():
                            try:
                                self.msg_queue.put_nowait(cmd)
                            except queue.Full:
                                print(f"[IPC] WARNING: Rx Queue full, dropping message")
                        else:
                            self.msg_queue.put(cmd)
                            
                    except json.JSONDecodeError:
                        print(f"[IPC] Corrupt JSON ignored")
                        
            except Exception as e:
                print(f"[IPC] Connection lost (Rx): {e}")
                if self.sock: 
                    try: self.sock.close() 
                    except: pass
                    self.sock = None
                time.sleep(1) 

    def _tx_loop(self):
        """
        Dedicated thread for writing to socket.
        Consumes from self.tx_queue.
        """
        while self.running:
            try:
                # Block until message available
                msg = self.tx_queue.get(timeout=1.0)
            except queue.Empty:
                continue
                
            if self.sock:
                try:
                    data_str = json.dumps(msg) + "\n"
                    # blocking sendall on the socket
                    self.sock.sendall(data_str.encode("utf-8"))
                    # Debug Log for Port Data (Sampled?)
                    # if "ports/data" in data_str:
                    #    print(f"[IPC] Sent Port Data") 
                except Exception as e:
                    # On Tx Error, force socket closed so Rx loop attempts reconnect
                    print(f"[IPC] Tx Error: {e}")
                    # Close socket to signal failure to Rx loop (which might be blocked on recv)
                    if self.sock:
                        try:
                            self.sock.shutdown(socket.SHUT_RDWR)
                        except: pass
                        try: 
                            self.sock.close()
                        except: pass
                        self.sock = None
            else:
                # Not connected. Drop message? Or wait? 
                pass


    def _processor_loop(self):
        """Pull messages from queue and process them"""
        while self.running:
            try:
                # Wait for message
                cmd = self.msg_queue.get(timeout=1.0) 
            except queue.Empty:
                continue
            
            try:
                self._dispatch_message(cmd)
            except Exception as e:
                print(f"[IPC] Processing error: {e}")

    def _dispatch_message(self, cmd: Dict[str, Any]):
        msg_type = cmd.get("type")
        
        # Tool Command -> ASYNC EXECUTION
        if msg_type == "device.command":
            t = threading.Thread(target=self._execute_tool, args=(cmd,), daemon=True)
            t.start()
            
        # InPort Data -> FAST CALLBACK
        elif msg_type == "ports.set":
            port = cmd.get("port")
            val = cmd.get("value")
            print(f"[IPC DEBUG] _dispatch_message: ports.set received! port={port}, value={val}")
            if self.on_port_data_callback:
                try:
                    self.on_port_data_callback(port, val)
                except Exception as e:
                    print(f"[IPC] Error in port callback: {e}")
            else:
                print(f"[IPC DEBUG] No callback registered for InPort!")
    
    def _execute_tool(self, cmd: Dict[str, Any]):
        """Runs in separate thread"""
        rid = cmd.get("request_id")
        tool_name = cmd.get("tool")
        args = cmd.get("args") or {}
        
        print(f"[IPC] Invoke tool: {tool_name} args={args}")
        
        result_text = ""
        if tool_name in self.tool_callbacks:
            try:
                # Execute user function
                res = self.tool_callbacks[tool_name](**args)
                result_text = str(res)
            except Exception as e:
                result_text = f"Error executing tool: {e}"
                print(f"[IPC] Tool Error: {e}")
        else:
            result_text = f"Tool {tool_name} not found"

        # Reply
        resp = {
            "topic": f"mcp/dev/{self.device_id}/events",
            "payload": {
                "request_id": rid,
                "result": {
                    "text": result_text
                }
            }
        }
        self._send_system_msg(resp)
