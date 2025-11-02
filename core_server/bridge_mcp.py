#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MQTT <-> MCP Bridge (웹 인터페이스 제거, MCP SSE 전용)
- MQTT ingest: mcp/dev/+/announce|status|events
- In-memory DeviceStore (Raw device data)
- Tool Projection Layer (Configuration-based tool filtering/aliasing)
- Command Router (request_id matching with timeout)
- MCP Server (FastMCP):
    tools:
      - invoke(device_id, tool, args)              # generic invoker (fallback)
      - {projected_tool_name}_{device_alias}(...) # projected device-specific tools
    resources:
      - bridge://devices
      - bridge://device/<device_id>
      - bridge://projections
- SSE endpoint for MCP: /sse (포트 8083)
"""
import os, sys, json, time, uuid, threading, queue, requests, logging, socket, base64, io
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List, Union
from pathlib import Path

# FastMCP and MCP types
from mcp.server.fastmcp import FastMCP, Context
from mcp.types import ImageContent, TextContent, Resource

# Pydantic for dynamic model creation
from pydantic import create_model, BaseModel

# ---- STDERR-only logging (STDIO-safe)
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
def log(*a, **k): print(*a, file=sys.stderr, flush=True, **k)

# ========= Env (Docker defaults) =========
MQTT_HOST = os.getenv("MQTT_HOST", "mcp-broker")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
KEEPALIVE = int(os.getenv("KEEPALIVE", "60"))
API_PORT  = int(os.getenv("API_PORT", "8083"))       # MCP SSE 전용
CMD_TIMEOUT_MS = int(os.getenv("CMD_TIMEOUT_MS", "8000"))
SUB_ALL        = os.getenv("DEBUG_SUB_ALL", "0") == "1"
PROJECTION_CONFIG_PATH = os.getenv("PROJECTION_CONFIG_PATH", "./projection_config.json")

TOPIC_ANN  = "mcp/dev/+/announce"
TOPIC_STAT = "mcp/dev/+/status"
TOPIC_EV   = "mcp/dev/+/events"

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ========= Tool Projection Layer =========
class ToolProjectionStore:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.config: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self.load_config()
    
    def load_config(self):
        """Load projection configuration from JSON file"""
        try:
            if Path(self.config_path).exists():
                with open(self.config_path, 'r') as f:
                    self.config = json.load(f)
                log(f"[PROJECTION] Loaded config from {self.config_path}")
            else:
                # Create default config with EVENT support
                self.config = {
                    "devices": {},
                    "global": {
                        "auto_enable_new_devices": True,
                        "auto_enable_new_tools": True,
                        "auto_enable_new_events": False  # EVENT는 기본 숨김
                    }
                }
                self.save_config()
                log(f"[PROJECTION] Created default config at {self.config_path}")
        except Exception as e:
            log(f"[PROJECTION] Error loading config: {e}")
            self.config = {
                "devices": {}, 
                "global": {
                    "auto_enable_new_devices": True, 
                    "auto_enable_new_tools": True,
                    "auto_enable_new_events": False
                }
            }
    
    def save_config(self):
        """Save current configuration to file"""
        try:
            with open(self.config_path, 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            log(f"[PROJECTION] Error saving config: {e}")
    
    def get_device_projection(self, device_id: str) -> Dict[str, Any]:
        """Get projection settings for a device"""
        with self._lock:
            return self.config.get("devices", {}).get(device_id, {})
    
    def is_device_enabled(self, device_id: str) -> bool:
        """Check if device is enabled in projection"""
        projection = self.get_device_projection(device_id)
        if "enabled" in projection:
            return projection["enabled"]
        return self.config.get("global", {}).get("auto_enable_new_devices", True)
    
    def is_tool_enabled(self, device_id: str, tool_name: str, tool_kind: str = "action") -> bool:
        """Check if specific tool is enabled in projection (kind-aware)"""
        projection = self.get_device_projection(device_id)
        tools = projection.get("tools", {})
        tool_config = tools.get(tool_name, {})
        
        # 명시적 설정이 있으면 그걸 따름
        if "enabled" in tool_config:
            return tool_config["enabled"]
        
        # 디바이스가 비활성화면 모든 툴 비활성
        if not self.is_device_enabled(device_id):
            return False
        
        # 종류별 기본값
        if tool_kind == "event":
            return self.config.get("global", {}).get("auto_enable_new_events", False)
        else:
            return self.config.get("global", {}).get("auto_enable_new_tools", True)
    
    def get_device_alias(self, device_id: str, device_name: Optional[str] = None) -> str:
        """Get device alias or fallback to original name"""
        projection = self.get_device_projection(device_id)
        alias = projection.get("device_alias")
        if alias:
            return alias
        return device_name or device_id
    
    def get_tool_projection(self, device_id: str, tool_name: str, original_tool: Dict[str, Any]) -> Dict[str, Any]:
        """Get projected tool configuration"""
        projection = self.get_device_projection(device_id)
        tools = projection.get("tools", {})
        tool_config = tools.get(tool_name, {})
        
        alias = tool_config.get("alias")
        if alias:
            projected_name = alias
        else:
            projected_name = tool_name
        
        projected_desc = tool_config.get("description")
        if projected_desc is None:
            projected_desc = original_tool.get("description", "")
        
        tool_kind = original_tool.get("kind", "action")
        
        result = {
            "name": projected_name,
            "description": projected_desc,
            "parameters": original_tool.get("parameters", {}),
            "original_name": tool_name,
            "device_id": device_id,
            "kind": tool_kind
        }
        
        # EVENT 전용 필드
        if tool_kind == "event":
            result["capabilities"] = original_tool.get("capabilities", {})
            result["signals"] = original_tool.get("signals", {})
        
        return result
    
    def auto_add_device(self, device_id: str, device_name: Optional[str], tools: List[Dict[str, Any]]):
        """Auto-add new device to projection config if not exists"""
        with self._lock:
            if device_id not in self.config.get("devices", {}):
                device_config = {
                    "enabled": self.config.get("global", {}).get("auto_enable_new_devices", True),
                    "device_alias": None,
                    "tools": {}
                }
                
                for tool in tools:
                    tool_name = tool.get("name", "")
                    tool_kind = tool.get("kind", "action")
                    if tool_name:
                        # KIND에 따라 다른 기본값
                        if tool_kind == "event":
                            default_enabled = self.config.get("global", {}).get("auto_enable_new_events", False)
                        else:
                            default_enabled = self.config.get("global", {}).get("auto_enable_new_tools", True)
                        
                        device_config["tools"][tool_name] = {
                            "enabled": default_enabled,
                            "kind": tool_kind,
                            "alias": None,
                            "description": None
                        }
                
                self.config.setdefault("devices", {})[device_id] = device_config
                self.save_config()
                log(f"[PROJECTION] Auto-added device {device_id} with {len(tools)} tools")

projection_store = ToolProjectionStore(PROJECTION_CONFIG_PATH)

# ========= Dynamic Tool Registry =========
class DynamicToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._registered_funcs: Dict[str, Any] = {}
    
    def register_device_tools(self, device_id: str, tools: List[Dict[str, Any]], device_name: Optional[str] = None):
        """Register projected tools for a device (only enabled ones)"""
        with self._lock:
            old_keys = [k for k in self._tools.keys() if k.endswith(f"_{device_id}")]
            for k in old_keys:
                self._tools.pop(k, None)
                self._registered_funcs.pop(k, None)
            
            projection_store.auto_add_device(device_id, device_name, tools)
            device_alias = projection_store.get_device_alias(device_id, device_name)
            
            registered_count = 0
            for tool in tools:
                original_tool_name = tool.get("name", "")
                if not original_tool_name:
                    continue
                
                if not projection_store.is_tool_enabled(device_id, original_tool_name):
                    log(f"[TOOLS] Skipping disabled tool: {original_tool_name} for device {device_id}")
                    continue
                
                projected_tool = projection_store.get_tool_projection(device_id, original_tool_name, tool)
                projected_name = projected_tool["name"]
                tool_key = f"{projected_name}_{device_id}"
                
                self._tools[tool_key] = {
                    "device_id": device_id,
                    "device_alias": device_alias,
                    "original_name": original_tool_name,
                    "projected_name": projected_name,
                    "description": projected_tool["description"],
                    "parameters": projected_tool["parameters"],
                    "tool_key": tool_key
                }
                registered_count += 1
            
            log(f"[TOOLS] registered {registered_count}/{len(tools)} projected tools for device {device_id} (alias: {device_alias})")
    
    def get_tool_info(self, tool_key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._tools.get(tool_key)
    
    def list_all_tools(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._tools.values())
    
    def get_registered_function(self, tool_key: str) -> Optional[Any]:
        with self._lock:
            return self._registered_funcs.get(tool_key)
    
    def set_registered_function(self, tool_key: str, func: Any):
        with self._lock:
            self._registered_funcs[tool_key] = func

tool_registry = DynamicToolRegistry()

# ========= In-memory stores =========
class DeviceStore:
    def __init__(self):
        self._by_id: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def upsert_announce(self, device_id: str, msg: Dict[str, Any]):
        with self._lock:
            d = self._by_id.setdefault(device_id, {"device_id": device_id})
            d["name"] = msg.get("name")
            d["version"] = msg.get("version")
            d["http_base"] = msg.get("http_base")
            d["tools"] = msg.get("tools", [])
            d["last_announce"] = msg
            d["last_seen"] = now_iso()
        
        tools = msg.get("tools", [])
        device_name = msg.get("name")
        tool_registry.register_device_tools(device_id, tools, device_name)
        
        try:
            register_dynamic_tools_for_device(device_id)
        except NameError:
            log(f"[DEVICE] Device {device_id} announced, tools will be registered after FastMCP initialization")
            pass

    def update_status(self, device_id: str, msg: Dict[str, Any]):
        with self._lock:
            d = self._by_id.setdefault(device_id, {"device_id": device_id})
            d["online"] = bool(msg.get("online", True))
            d["uptime_ms"] = msg.get("uptime_ms")
            d["rssi"] = msg.get("rssi")
            d["last_status"] = msg
            d["last_seen"] = now_iso()

    def get(self, device_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            if device_id not in self._by_id:
                return None
            return json.loads(json.dumps(self._by_id[device_id]))

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            out = []
            for d in self._by_id.values():
                dd = json.loads(json.dumps(d))
                last_status = dd.get("last_status", {})
                ts = last_status.get("ts")
                if ts:
                    try:
                        dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                        dd["online"] = (datetime.now(timezone.utc) - dt).total_seconds() < 90
                    except Exception:
                        pass
                out.append(dd)
            return out

device_store = DeviceStore()

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

cmd_waiter = CommandWaiter()

# ========= MQTT Client (thread) =========
import paho.mqtt.client as mqtt

def parse_topic(topic: str):
    parts = topic.split("/")
    if len(parts) >= 4:
        return parts[2], parts[3]
    return None, None

def mqtt_thread():
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"bridge-mcp-{uuid.uuid4().hex[:6]}",
        protocol=mqtt.MQTTv5
    )
    client.enable_logger()

    def on_connect(c, userdata, flags, reason_code, properties=None):
        log(f"[mqtt] connected rc={reason_code} host={MQTT_HOST}:{MQTT_PORT}")
        if SUB_ALL:
            sub = ("mcp/#", 0)
            c.subscribe(sub)
            log(f"[mqtt] subscribe {sub}")
        else:
            c.subscribe(TOPIC_ANN); log(f"[mqtt] subscribe {TOPIC_ANN}")
            c.subscribe(TOPIC_STAT); log(f"[mqtt] subscribe {TOPIC_STAT}")
            c.subscribe(TOPIC_EV); log(f"[mqtt] subscribe {TOPIC_EV}")

    def on_message(c, userdata, msg):
        log(f"[mqtt] RX {msg.topic} {len(msg.payload)}B")
        dev_id, leaf = parse_topic(msg.topic)
        if not dev_id or not leaf:
            return
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            log("[mqtt] JSON parse error from broker")
            return

        if leaf == "announce":
            device_store.upsert_announce(dev_id, payload)
            register_dynamic_tools_for_device(dev_id)
        elif leaf == "status":
            device_store.update_status(dev_id, payload)
        elif leaf == "events":
            rid = payload.get("request_id")
            if rid:
                cmd_waiter.resolve(rid, payload)

    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(MQTT_HOST, MQTT_PORT, keepalive=KEEPALIVE)
    client.loop_forever(retry_first_connection=True)

threading.Thread(target=mqtt_thread, daemon=True).start()

# ========= Publish helper =========
def publish_cmd(device_id: str, tool: str, args: Any,
                request_id: Optional[str]=None, timeout_ms: int=CMD_TIMEOUT_MS):
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
    log(f"[DEBUG] Publishing to {topic}: {json.dumps(payload, indent=2)}")
    
    q = cmd_waiter.register(rid)

    if not device_store.get(device_id):
        return False, {"ok": False, "error": {"code": "unknown_device",
                                              "message": f"device_id '{device_id}' not found in announce cache"},
                       "request_id": rid}

    c = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"bridge-pub-{uuid.uuid4().hex[:6]}",
        protocol=mqtt.MQTTv5
    )
    try:
        c.connect(MQTT_HOST, MQTT_PORT, keepalive=KEEPALIVE)
    except Exception as e:
        return False, {"ok": False, "error": {"code": "mqtt_connect_failed",
                                              "message": f"cannot connect to broker {MQTT_HOST}:{MQTT_PORT} ({e})"},
                       "request_id": rid}

    c.loop_start()
    c.publish(topic, json.dumps(payload), qos=0, retain=False)
    c.loop_stop()
    c.disconnect()

    try:
        resp = q.get(timeout=timeout_ms/1000.0)
        return True, resp
    except queue.Empty:
        return False, {"ok": False, "error": {"code":"timeout",
                                              "message": f"no event for request_id={rid} within {timeout_ms}ms"},
                       "request_id": rid}

# ========= Image processing helper =========
def fetch_and_convert_to_base64(url: str, timeout: int = 10) -> Optional[str]:
    """Fetch image from URL and convert to base64"""
    try:
        cache_bust_url = f"{url}{'&' if '?' in url else '?'}t={int(time.time() * 1000)}"
        response = requests.get(cache_bust_url, timeout=timeout)
        response.raise_for_status()
        b64_data = base64.b64encode(response.content).decode('utf-8')
        log(f"[BASE64] Converted image to base64 ({len(b64_data)} chars)")
        return b64_data
    except Exception as e:
        log(f"[BASE64] Failed to fetch/convert {url}: {e}")
        return None

def convert_response_to_content_list(resp: Dict[str, Any]) -> List[Union[ImageContent, TextContent]]:
    """Convert device response to MCP content list"""
    result = resp.get("result", {})
    text = result.get("text", "")
    assets = result.get("assets", [])
    
    content = []
    
    for asset in assets:
        kind = str(asset.get("kind", ""))
        mime = str(asset.get("mime", "application/octet-stream")).lower()
        url = asset.get("url")
        
        if kind == "image" and mime.startswith("image/") and url:
            b64_data = fetch_and_convert_to_base64(url)
            if b64_data:
                content.append(ImageContent(
                    type="image",
                    mimeType=mime,
                    data=b64_data
                ))
    
    if text:
        content.append(TextContent(type="text", text=text))
    
    return content

# ========= JSON Schema to Pydantic Model =========
def json_schema_to_pydantic_model(name: str, schema: dict):
    """JSON Schema를 Pydantic 모델로 변환"""
    fields = {}
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    
    for prop_name, prop_schema in properties.items():
        field_type = str
        
        if prop_schema.get("type") == "integer":
            field_type = int
        elif prop_schema.get("type") == "number":
            field_type = float
        elif prop_schema.get("type") == "boolean":
            field_type = bool
        elif prop_schema.get("type") == "object":
            field_type = dict
        elif prop_schema.get("type") == "array":
            field_type = list
        elif prop_schema.get("type") == "string":
            field_type = str
        
        default_value = ...
        if prop_name not in required:
            if "enum" in prop_schema and prop_schema["enum"]:
                default_value = prop_schema["enum"][0]
            else:
                default_value = None
        
        fields[prop_name] = (field_type, default_value)
    
    return create_model(name, **fields)

# ========= FastMCP Server =========
mcp = FastMCP("bridge-mcp")

# ---- Resources ----
@mcp.resource("bridge://devices")
def res_devices() -> Resource:
    return Resource(
        uri="bridge://devices",
        name="devices",
        description="Known devices with latest announce/status (raw data)",
        mimeType="application/json",
        text=json.dumps(device_store.list(), indent=2)
    )

@mcp.resource("bridge://device/{device_id}")
def res_device(device_id: str) -> Resource:
    d = device_store.get(device_id)
    if not d:
        return Resource(
            uri=f"bridge://device/{device_id}",
            name="device",
            description="Device not found",
            mimeType="application/json",
            text=json.dumps({"error":"not found"})
        )
    return Resource(
        uri=f"bridge://device/{device_id}",
        name="device",
        description=f"Device {device_id} details (raw data)",
        mimeType="application/json",
        text=json.dumps(d, indent=2)
    )

@mcp.resource("bridge://projections")
def res_projections() -> Resource:
    """Show current projection configuration and projected tools"""
    projected_tools = tool_registry.list_all_tools()
    projection_summary = {
        "config": projection_store.config,
        "projected_tools": projected_tools,
        "stats": {
            "total_projected_tools": len(projected_tools),
            "devices_in_config": len(projection_store.config.get("devices", {}))
        }
    }
    return Resource(
        uri="bridge://projections",
        name="projections",
        description="Current projection configuration and projected tools",
        mimeType="application/json",
        text=json.dumps(projection_summary, indent=2)
    )

@mcp.resource("bridge://device/{device_id}/events")
def res_device_events(device_id: str) -> Resource:
    """
    Get EVENT capabilities for a device.
    Events cannot be called directly via MCP but can be integrated via SDK for vibe coding workflows.
    """
    device = device_store.get(device_id)
    if not device:
        return Resource(
            uri=f"bridge://device/{device_id}/events",
            name="device_events",
            description="Device not found",
            mimeType="application/json",
            text=json.dumps({"error": "device not found"})
        )
    
    tools = device.get("tools", [])
    events = []
    
    for tool in tools:
        kind = tool.get("kind", "action")
        if kind == "event":
            tool_name = tool.get("name", "")
            
            # Projection 체크 (enabled인 것만)
            if not projection_store.is_tool_enabled(device_id, tool_name, kind):
                continue
            
            projected = projection_store.get_tool_projection(device_id, tool_name, tool)
            
            event_info = {
                "name": projected["name"],
                "original_name": projected["original_name"],
                "description": projected["description"],
                "parameters": projected["parameters"],
                "capabilities": projected.get("capabilities", {}),
                "signals": projected.get("signals", {}),
                "kind": "event"
            }
            events.append(event_info)
    
    result = {
        "device_id": device_id,
        "device_alias": projection_store.get_device_alias(device_id, device.get('name')),
        "events": events,
        "count": len(events),
        "note": "These events cannot be invoked directly via MCP. Use SDK integration for vibe coding workflows."
    }
    
    return Resource(
        uri=f"bridge://device/{device_id}/events",
        name="device_events",
        description=f"EVENT capabilities for device {device_id} (for SDK integration)",
        mimeType="application/json",
        text=json.dumps(result, indent=2)
    )

# ---- Static Tools ----
@mcp.tool()
def invoke(device_id: str, tool: str, args: dict | None = None) -> List[Union[ImageContent, TextContent]]:
    """Generic tool invoker (fallback for any device tool) - uses original tool names"""
    args = args or {}
    ok, resp = publish_cmd(device_id, tool, args)
    if not ok:
        error_msg = resp.get("error", {}).get("message", "Unknown error")
        return [TextContent(type="text", text=f"Error: {error_msg}")]
    
    return convert_response_to_content_list(resp)

@mcp.tool()
def list_devices() -> List[TextContent]:
    """List devices from announce/status cache with projection info (ACTION/EVENT counts)."""
    devices = device_store.list()
    device_summary = []
    for device in devices:
        device_id = device['device_id']
        status = "online" if device.get("online", False) else "offline"
        
        # ACTION/EVENT 구분
        tools = device.get("tools", [])
        actions_count = len([t for t in tools if t.get("kind", "action") == "action"])
        events_count = len([t for t in tools if t.get("kind") == "event"])
        
        device_alias = projection_store.get_device_alias(device_id, device.get('name'))
        is_enabled = projection_store.is_device_enabled(device_id)
        
        # Projected ACTION tools만 카운트 (EVENT는 MCP tool이 아님)
        projected_actions = [t for t in tool_registry.list_all_tools() if t['device_id'] == device_id]
        projected_count = len(projected_actions)
        
        device_summary.append(
            f"• {device_id} → '{device_alias}' ({status}, {projected_count}/{actions_count} actions, {events_count} events, {'enabled' if is_enabled else 'disabled'})"
        )
    
    summary_text = f"Found {len(devices)} devices:\n" + "\n".join(device_summary)
    return [TextContent(type="text", text=summary_text)]

@mcp.tool()
def get_tools(device_id: str) -> List[TextContent]:
    """List a device's announced tools with projection status (ACTION and EVENT)."""
    d = device_store.get(device_id)
    if not d:
        return [TextContent(type="text", text=f"Error: device_id '{device_id}' not found")]
    
    tools = d.get("tools", [])
    if not tools:
        return [TextContent(type="text", text=f"Device {device_id} has no announced tools")]
    
    action_summary = []
    event_summary = []
    
    for tool in tools:
        name = tool.get("name", "unknown")
        desc = tool.get("description", "")
        kind = tool.get("kind", "action")
        
        is_enabled = projection_store.is_tool_enabled(device_id, name, kind)
        if is_enabled:
            projected_tool = projection_store.get_tool_projection(device_id, name, tool)
            projected_name = projected_tool["name"]
            projected_desc = projected_tool["description"]
            line = f"• {name} → '{projected_name}' (enabled): {projected_desc}"
        else:
            line = f"• {name} (disabled): {desc}"
        
        if kind == "event":
            event_summary.append(line)
        else:
            action_summary.append(line)
    
    device_alias = projection_store.get_device_alias(device_id, d.get('name'))
    
    result_lines = [f"Device {device_id} → '{device_alias}' ({len(tools)} tools total)"]
    
    if action_summary:
        result_lines.append(f"\nACTIONS ({len(action_summary)}):")
        result_lines.extend(action_summary)
    
    if event_summary:
        result_lines.append(f"\nEVENTS ({len(event_summary)}) [Use bridge://device/{device_id}/events for details]:")
        result_lines.extend(event_summary)
    
    summary_text = "\n".join(result_lines)
    return [TextContent(type="text", text=summary_text)]

# ---- Dynamic Tool Creation and Registration ----
def register_dynamic_tools_for_device(device_id: str):
    """Register dynamic projected tools for a specific device with FastMCP using proper schemas (ACTION only)"""
    device = device_store.get(device_id)
    if not device or not device.get("tools"):
        return
    
    log(f"[MCP] Registering dynamic projected tools for device {device_id}")
    
    for tool_info in device["tools"]:
        tool_name = tool_info.get("name", "")
        tool_kind = tool_info.get("kind", "action")
        
        if not tool_name:
            continue
        
        # EVENT는 MCP Tool로 등록하지 않음 (Resource로만 노출)
        if tool_kind == "event":
            log(f"[MCP] Skipping EVENT (not an MCP tool): {tool_name} for device {device_id}")
            continue
        
        if not projection_store.is_tool_enabled(device_id, tool_name, tool_kind):
            log(f"[MCP] Skipping disabled tool: {tool_name} for device {device_id}")
            continue
        
        projected_tool = projection_store.get_tool_projection(device_id, tool_name, tool_info)
        projected_name = projected_tool["name"]
        
        tool_key = f"{projected_name}_{device_id}"
        
        log(f"[MCP] Processing ACTION tool: {tool_name} -> {projected_name} (key: {tool_key})")
        
        if tool_registry.get_registered_function(tool_key):
            log(f"[MCP] Tool {tool_key} already registered, skipping")
            continue
        
        try:
            schema = tool_info.get("parameters", {})
            if not schema or schema.get("type") != "object":
                log(f"[MCP] Skipping tool {tool_key}: invalid or missing schema")
                continue
            
            ParamModel = json_schema_to_pydantic_model(f"{tool_key}_params", schema)
            
            def create_tool_func(device_id_copy, original_tool_name_copy, projected_tool_copy, param_model):
                def tool_func(params: param_model) -> List[Union[ImageContent, TextContent]]:
                    """Dynamically generated projected device tool function with proper schema"""
                    args = params.dict()
                    log(f"[PROJECTED_TOOL] {projected_tool_copy['name']} ({original_tool_name_copy}) called with args: {json.dumps(args, indent=2)}")
                    
                    ok, resp = publish_cmd(device_id_copy, original_tool_name_copy, args)
                    
                    if not ok:
                        error_msg = resp.get("error", {}).get("message", "Unknown error")
                        return [TextContent(type="text", text=f"Error: {error_msg}")]
                    
                    return convert_response_to_content_list(resp)
                
                tool_func.__name__ = projected_tool_copy["name"]
                tool_func.__doc__ = projected_tool_copy["description"]
                
                return tool_func
            
            dynamic_func = create_tool_func(device_id, tool_name, projected_tool, ParamModel)
            decorated_func = mcp.tool()(dynamic_func)
            tool_registry.set_registered_function(tool_key, decorated_func)
            
            log(f"[MCP] Successfully registered projected tool: {tool_key} (function name: {projected_name}, original: {tool_name})")
            
        except Exception as e:
            log(f"[MCP] Failed to register projected tool {tool_key}: {e}")

def register_all_announced_devices():
    """Register tools for all devices that were announced before FastMCP initialization"""
    devices = device_store.list()
    log(f"[MCP] Registering tools for {len(devices)} announced devices")
    for device in devices:
        device_id = device.get("device_id")
        if device_id:
            register_dynamic_tools_for_device(device_id)

# Register tools for any devices that announced early
register_all_announced_devices()

# ========= Minimal FastAPI App for MCP SSE + Projection Manager API =========
from fastapi import FastAPI, HTTPException
import uvicorn

app = FastAPI(title="Bridge MCP (SSE + Minimal API)")

@app.get("/healthz")
def healthz():
    return {"ok": True, "ts": now_iso(), "service": "mcp-bridge", "port": API_PORT}

# ========= API Endpoints for Projection Manager =========
@app.get("/devices")
def get_devices_api():
    """Get devices list for projection manager"""
    return device_store.list()

@app.get("/devices/{device_id}")
def get_device_api(device_id: str):
    """Get specific device for projection manager"""
    d = device_store.get(device_id)
    if not d:
        raise HTTPException(HTTPStatus.NOT_FOUND, "device not found")
    return d

@app.post("/invoke")
def invoke_api(payload: dict):
    """HTTP endpoint for invoking device tools (for Projection Manager)"""
    device_id = payload.get("device_id")
    tool = payload.get("tool")
    args = payload.get("args", {})
    
    if not device_id or not tool:
        raise HTTPException(HTTPStatus.BAD_REQUEST, "device_id and tool are required")
    
    log(f"[API] Invoke request: device={device_id}, tool={tool}, args={args}")
    
    ok, resp = publish_cmd(device_id, tool, args)
    
    if not ok:
        error_msg = resp.get("error", {}).get("message", "Unknown error")
        return {"ok": False, "error": error_msg, "response": resp}
    
    return {"ok": True, "response": resp}

# Mount MCP SSE endpoint - 모든 초기화 후에 실행
try:
    sse_app = mcp.sse_app()
    app.mount("/sse", sse_app)
    log("[MCP] SSE endpoint mounted successfully at /sse")
except Exception as e:
    log(f"[MCP] Failed to mount SSE endpoint: {e}")
    # 기본 SSE 엔드포인트라도 생성
    @app.get("/sse")
    def sse_fallback():
        return {"error": "MCP SSE not available", "details": str(e)}

# ========= Main =========
def pick_free_port(base: int, tries: int) -> int | None:
    for p in range(base, base + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("0.0.0.0", p))
            except OSError:
                continue
            return p
    return None

if __name__ == "__main__":
    ACTIVE_API_PORT = API_PORT
    if os.getenv("AUTO_PORT_FALLBACK", "1") == "1":
        pf = pick_free_port(API_PORT, 10)
        if pf:
            ACTIVE_API_PORT = pf
    log(f"[boot] python={sys.version}")
    log(f"[boot] MQTT_HOST={MQTT_HOST} MQTT_PORT={MQTT_PORT} KEEPALIVE={KEEPALIVE} API_PORT={ACTIVE_API_PORT}")
    log(f"[boot] PROJECTION_CONFIG_PATH={PROJECTION_CONFIG_PATH}")
    log(f"[boot] MCP SSE endpoint: http://0.0.0.0:{ACTIVE_API_PORT}/sse")
    uvicorn.run(app, host="0.0.0.0", port=int(ACTIVE_API_PORT), log_level="warning", access_log=False)