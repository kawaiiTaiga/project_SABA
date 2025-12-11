import queue
import threading
import json
import uuid
from typing import Dict, Any, Optional, Tuple
from .utils import log
from .config import CMD_TIMEOUT_MS, MQTT_HOST, MQTT_PORT
from .device_store import DeviceStore
import hmac
import hashlib
import time

class CommandWaiter:
    def __init__(self):
        self._qmap: Dict[str, queue.Queue] = {}
        self._lock = threading.Lock()

    def register(self, rid: str) -> queue.Queue:
        with self._lock:
            q = queue.Queue(maxsize=1)
            self._qmap[rid] = q
            return q

    def resolve(self, rid: str, payload: Dict[str, Any]):
        with self._lock:
            q = self._qmap.pop(rid, None)
        if q:
            try:
                q.put_nowait(payload)
            except Exception:
                pass

def publish_cmd(device_store: DeviceStore, cmd_waiter: CommandWaiter, mqtt_client, 
                device_id: str, tool: str, args: Any,
                request_id: Optional[str]=None, timeout_ms: int=CMD_TIMEOUT_MS) -> Tuple[bool, Dict[str, Any]]:
    rid = request_id or uuid.uuid4().hex
    topic = f"mcp/dev/{device_id}/cmd"
    
    if isinstance(args, str):
        parsed_args = {}
        separator = ',' if ',' in args else '&'
        for pair in args.split(separator):
            if '=' in pair:
                key, value = pair.split('=', 1)
                parsed_args[key.strip()] = value.strip()
            elif ':' in pair:
                key, value = pair.split(':', 1)
                parsed_args[key.strip()] = value.strip()
        args = parsed_args
    elif isinstance(args, dict) and "kwargs" in args and len(args) == 1:
        args = args["kwargs"]
    
    payload = {"type":"device.command","tool":tool,"args":args,"request_id":rid}
    
    # HMAC Signing
    token = device_store.get_token(device_id)
    if token:
        ts = int(time.time())
        
        # Create the inner payload as a deterministic JSON string
        inner_payload = {"type":"device.command","tool":tool,"args":args,"request_id":rid, "timestamp": ts}
        inner_payload_str = json.dumps(inner_payload, separators=(',', ':'))
        
        # Sign the string
        signature = hmac.new(
            token.encode('utf-8'),
            inner_payload_str.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        # Construct final payload with the signed string and signature
        # We send the inner payload as a STRING to ensure the device verifies exactly what we signed
        payload = {
            "data": inner_payload_str,
            "signature": signature
        }
        log(f"[SEC] Signed command for {device_id} with ts={ts}")
    else:
        log(f"[SEC] Warning: No token for {device_id}, sending unsigned command")
        # Fallback for unclaimed devices (or if token missing)
        payload = {"type":"device.command","tool":tool,"args":args,"request_id":rid}

    log(f"[DEBUG] Publishing to {topic}: {json.dumps(payload, indent=2)}")
    
    q = cmd_waiter.register(rid)

    if not device_store.get(device_id):
        log(f"[DEBUG] Device {device_id} not found in store")
        return False, {"ok": False, "error": {"code": "unknown_device",
                                              "message": f"device_id '{device_id}' not found in announce cache"},
                       "request_id": rid}

    try:
        mqtt_client.publish(topic, json.dumps(payload), qos=1, retain=False)
        log(f"[DEBUG] MQTT publish success to {topic}")
    except Exception as e:
        log(f"[DEBUG] MQTT publish failed: {e}")
        return False, {"ok": False, "error": {"code": "mqtt_connect_failed",
                                              "message": f"cannot connect to broker {MQTT_HOST}:{MQTT_PORT} ({e})"},
                       "request_id": rid}

    try:
        resp = q.get(timeout=timeout_ms/1000.0)
        return True, resp
    except queue.Empty:
        return False, {"ok": False, "error": {"code":"timeout",
                                              "message": f"no event for request_id={rid} within {timeout_ms}ms"},
                       "request_id": rid}
