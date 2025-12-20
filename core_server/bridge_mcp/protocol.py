from typing import Dict, Any, Optional
import json
from .utils import log
from .device_store import DeviceStore
from .command import CommandWaiter

class ProtocolHandler:
    """
    Unified Message Processor for SABA.
    Handles business logic regardless of transport (IPC vs MQTT).
    """
    def __init__(self, device_store: DeviceStore, cmd_waiter: CommandWaiter, port_store, port_router):
        self.device_store = device_store
        self.cmd_waiter = cmd_waiter
        self.port_store = port_store
        self.port_router = port_router

    def parse_topic(self, topic: str):
        """
        Standard Topic Format: mcp/dev/{device_id}/{leaf...}
        """
        parts = topic.split("/")
        if len(parts) >= 4 and parts[0] == "mcp" and parts[1] == "dev":
            device_id = parts[2]
            leaf = "/".join(parts[3:])
            return device_id, leaf
        return None, None

    def handle_message(self, topic: str, payload: Dict[str, Any], protocol: str, device_id_hint: str = None):
        """
        Main entry point for all incoming messages.
        
        Args:
            topic: The topic string (e.g., mcp/dev/xyz/announce)
            payload: The parsed JSON payload
            protocol: "ipc" or "mqtt"
            device_id_hint: Optional override for deviceID (e.g. from socket connection)
        """
        # 1. Parse Topic
        dev_id, leaf = self.parse_topic(topic)
        if not dev_id:
            # If topic doesn't have ID but we have a hint (unlikely in this topic schema but possible)
            if device_id_hint:
                dev_id = device_id_hint
                # Try to guess leaf? Unsafe.
                # In current SABA, topic always contains ID.
            else:
                return

        # 2. Add Protocol Metadata
        # We might want to track which protocol a device is using
        
        # 3. Route by Leaf (Action)
        
        if leaf == "announce":
            self.device_store.upsert_announce(dev_id, payload, protocol=protocol)
            # Note: MQTT might do "claiming" here. 
            # Ideally ProtocolHandler returns "actions" for the transport to take? 
            # Or we inject a 'ClaimService'. For now, we'll keep claim logic in MQTT transport or move it here later.
            return ("announce", dev_id)

        elif leaf == "status":
            self.device_store.update_status(dev_id, payload)
            return ("status", dev_id)

        elif leaf == "events":
            rid = payload.get("request_id")
            if rid:
                self.cmd_waiter.resolve(rid, payload)
            return ("events", rid)

        elif leaf == "ports/announce":
            self.port_store.upsert_ports_announce(dev_id, payload)
            return ("ports_announce", dev_id)

        elif leaf == "ports/data":
            port_name = payload.get("port")
            value = payload.get("value")
            if port_name is not None:
                try:
                    val = float(value)
                    routed = self.port_router.route(dev_id, port_name, val)
                    log(f"[PROTOCOL] Routed {dev_id}/{port_name} ({val}) -> {routed} targets")
                    return ("routed", routed)
                except:
                    pass
            return ("ports_data", None)
            
        return ("unknown", None)
