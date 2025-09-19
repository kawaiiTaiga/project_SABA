#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Single-file MQTT <-> MCP Bridge (Updated with Dynamic Tool Creation and Projection Layer)
- MQTT ingest: mcp/dev/+/announce|status|events
- In-memory DeviceStore (Raw device data)
- Tool Projection Layer (Configuration-based tool filtering/aliasing)
- Command Router (request_id matching with timeout)
- Asset Proxy (FastAPI): /assets/<request_id>[/{index}]
- SSE endpoint for MCP: /sse
- MCP Server (FastMCP):
    tools:
      - invoke(device_id, tool, args)              # generic invoker (fallback)
      - {projected_tool_name}_{device_alias}(...) # projected device-specific tools
    resources:
      - bridge://devices
      - bridge://device/<device_id>
      - bridge://asset/<request_id>
      - bridge://projections
"""
import os, sys, json, time, uuid, threading, queue, requests, logging, socket, base64, io
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List, Union
from http import HTTPStatus
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
MQTT_HOST = os.getenv("MQTT_HOST", "mcp-broker")     # docker-compose service name
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
KEEPALIVE = int(os.getenv("KEEPALIVE", "60"))
API_PORT  = int(os.getenv("API_PORT", "8083"))       # default exposed port
CMD_TIMEOUT_MS = int(os.getenv("CMD_TIMEOUT_MS", "8000"))
ASSET_TTL_SEC  = int(os.getenv("ASSET_TTL_SEC", "600"))
SUB_ALL        = os.getenv("DEBUG_SUB_ALL", "0") == "1"  # subscribe mcp/# for debug
PROJECTION_CONFIG_PATH = os.getenv("PROJECTION_CONFIG_PATH", "./projection_config.json")

TOPIC_ANN  = "mcp/dev/+/announce"
TOPIC_STAT = "mcp/dev/+/status"
TOPIC_EV   = "mcp/dev/+/events"

ACTIVE_API_PORT: Optional[int] = None  # bound port (for proxy URL)

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
                # Create default config
                self.config = {
                    "devices": {},
                    "global": {
                        "auto_enable_new_devices": True,
                        "auto_enable_new_tools": True
                    }
                }
                self.save_config()
                log(f"[PROJECTION] Created default config at {self.config_path}")
        except Exception as e:
            log(f"[PROJECTION] Error loading config: {e}")
            self.config = {"devices": {}, "global": {"auto_enable_new_devices": True, "auto_enable_new_tools": True}}
    
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
        # Default to global setting
        return self.config.get("global", {}).get("auto_enable_new_devices", True)
    
    def is_tool_enabled(self, device_id: str, tool_name: str) -> bool:
        """Check if specific tool is enabled in projection"""
        projection = self.get_device_projection(device_id)
        tools = projection.get("tools", {})
        tool_config = tools.get(tool_name, {})
        
        if "enabled" in tool_config:
            return tool_config["enabled"]
        # Default to global setting if device is enabled
        if self.is_device_enabled(device_id):
            return self.config.get("global", {}).get("auto_enable_new_tools", True)
        return False
    
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
        
        # Get projected name - if alias is None or empty, use original name
        alias = tool_config.get("alias")
        if alias:
            projected_name = alias
        else:
            projected_name = tool_name
        
        # Get projected description (original if not overridden)
        projected_desc = tool_config.get("description")
        if projected_desc is None:
            projected_desc = original_tool.get("description", "")
        
        result = {
            "name": projected_name,
            "description": projected_desc,
            "parameters": original_tool.get("parameters", {}),
            "original_name": tool_name,
            "device_id": device_id
        }
        
        # Debug logging
        log(f"[PROJECTION] get_tool_projection for {device_id}.{tool_name}:")
        log(f"[PROJECTION]   tool_config: {tool_config}")
        log(f"[PROJECTION]   alias: {alias}")
        log(f"[PROJECTION]   projected_name: {projected_name}")
        log(f"[PROJECTION]   result: {result}")
        
        return result
    
    def auto_add_device(self, device_id: str, device_name: Optional[str], tools: List[Dict[str, Any]]):
        """Auto-add new device to projection config if not exists"""
        with self._lock:
            if device_id not in self.config.get("devices", {}):
                device_config = {
                    "enabled": self.config.get("global", {}).get("auto_enable_new_devices", True),
                    "device_alias": None,  # Will use original name
                    "tools": {}
                }
                
                # Auto-add tools
                for tool in tools:
                    tool_name = tool.get("name", "")
                    if tool_name:
                        device_config["tools"][tool_name] = {
                            "enabled": self.config.get("global", {}).get("auto_enable_new_tools", True),
                            "alias": None,  # Will use original name + device_id
                            "description": None  # Will use original description
                        }
                
                self.config.setdefault("devices", {})[device_id] = device_config
                self.save_config()
                log(f"[PROJECTION] Auto-added device {device_id} with {len(tools)} tools")

projection_store = ToolProjectionStore(PROJECTION_CONFIG_PATH)

# ========= Dynamic Tool Registry (Updated) =========
class DynamicToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Dict[str, Any]] = {}  # tool_key -> tool_info
        self._lock = threading.Lock()
        self._registered_funcs: Dict[str, Any] = {}  # tool_key -> registered function
    
    def register_device_tools(self, device_id: str, tools: List[Dict[str, Any]], device_name: Optional[str] = None):
        """Register projected tools for a device (only enabled ones)"""
        with self._lock:
            # Remove old tools for this device
            old_keys = [k for k in self._tools.keys() if k.endswith(f"_{device_id}")]
            for k in old_keys:
                self._tools.pop(k, None)
                self._registered_funcs.pop(k, None)
            
            # Auto-add to projection config if new
            projection_store.auto_add_device(device_id, device_name, tools)
            
            # Get device alias
            device_alias = projection_store.get_device_alias(device_id, device_name)
            
            # Add projected tools (only enabled ones)
            registered_count = 0
            for tool in tools:
                original_tool_name = tool.get("name", "")
                if not original_tool_name:
                    continue
                
                # Check if tool is enabled in projection
                if not projection_store.is_tool_enabled(device_id, original_tool_name):
                    log(f"[TOOLS] Skipping disabled tool: {original_tool_name} for device {device_id}")
                    continue
                
                # Get projected tool configuration
                projected_tool = projection_store.get_tool_projection(device_id, original_tool_name, tool)
                
                # Create projected tool key
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

# ========= In-memory stores (DeviceStore unchanged) =========
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
        
        # Register projected tools (filtering applied here)
        tools = msg.get("tools", [])
        device_name = msg.get("name")
        tool_registry.register_device_tools(device_id, tools, device_name)
        
        # Register dynamic tools - moved to a separate function call after FastMCP is initialized
        try:
            register_dynamic_tools_for_device(device_id)
        except NameError:
            # Function not yet defined, will be called later
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
                # online by last status ts within 90s
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

# request_id -> Queue for single response
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

# request_id -> {"ts": datetime, "event": payload}
asset_cache: Dict[str, Dict[str, Any]] = {}
asset_lock = threading.Lock()

def asset_gc_thread():
    while True:
        try:
            now = datetime.now(timezone.utc)
            with asset_lock:
                stale = [rid for rid, v in asset_cache.items()
                         if (now - v.get("ts", now)).total_seconds() > ASSET_TTL_SEC]
                for rid in stale:
                    asset_cache.pop(rid, None)
            time.sleep(15)
        except Exception as e:
            log(f"[asset-gc] error: {e}")
            time.sleep(30)

# ========= MQTT Client (thread) - unchanged =========
import paho.mqtt.client as mqtt

def parse_topic(topic: str):
    # "mcp/dev/<device_id>/<leaf>"
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
            # Projected tools are registered in upsert_announce
            register_dynamic_tools_for_device(dev_id)
        elif leaf == "status":
            device_store.update_status(dev_id, payload)
        elif leaf == "events":
            rid = payload.get("request_id")
            if rid:
                with asset_lock:
                    asset_cache[rid] = {"ts": datetime.now(timezone.utc), "event": payload}
                cmd_waiter.resolve(rid, payload)

    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(MQTT_HOST, MQTT_PORT, keepalive=KEEPALIVE)
    client.loop_forever(retry_first_connection=True)

threading.Thread(target=mqtt_thread, daemon=True).start()
threading.Thread(target=asset_gc_thread, daemon=True).start()

# ========= Publish helper (Updated to use original tool names) =========
def publish_cmd(device_id: str, tool: str, args: Any,
                request_id: Optional[str]=None, timeout_ms: int=CMD_TIMEOUT_MS):
    rid = request_id or uuid.uuid4().hex
    topic = f"mcp/dev/{device_id}/cmd"
    
    # args 정규화 (모든 케이스 처리)
    if isinstance(args, str):
        # "quality=high,flash=on" 또는 "quality=high&flash=on" 형식
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
        # {"kwargs": {...}} 형식
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

# ========= Image processing helper (unchanged) =========
def fetch_and_convert_to_base64(url: str, timeout: int = 10) -> Optional[str]:
    """Fetch image from URL and convert to base64"""
    try:
        # Add cache-busting parameter to ensure fresh image
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
    
    # Process images first
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
    
    # Add text content after images
    if text:
        content.append(TextContent(type="text", text=text))
    
    return content

# ========= JSON Schema to Pydantic Model (unchanged) =========
def json_schema_to_pydantic_model(name: str, schema: dict):
    """JSON Schema를 Pydantic 모델로 변환"""
    fields = {}
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    
    for prop_name, prop_schema in properties.items():
        field_type = str  # 기본값
        
        # 타입 매핑
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
        
        # enum이 있으면 첫 번째 값을 기본값으로 사용
        default_value = ...
        if prop_name not in required:
            if "enum" in prop_schema and prop_schema["enum"]:
                default_value = prop_schema["enum"][0]
            else:
                default_value = None
        
        fields[prop_name] = (field_type, default_value)
    
    return create_model(name, **fields)

# ========= FastMCP Server (Updated) =========
mcp = FastMCP("bridge-mcp")

# ---- Resources (Updated with projection info) ----
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

@mcp.resource("bridge://asset/{request_id}")
def res_asset(request_id: str) -> Resource:
    with asset_lock:
        rec = asset_cache.get(request_id)
    if not rec:
        return Resource(
            uri=f"bridge://asset/{request_id}",
            name="asset",
            description="Asset not found",
            mimeType="application/json",
            text=json.dumps({"error":"not found"})
        )
    ev = rec["event"]
    content_list = convert_response_to_content_list(ev)
    return Resource(
        uri=f"bridge://asset/{request_id}",
        name="asset",
        description="Event result with assets",
        mimeType="application/json",
        text=json.dumps({"content": [c.__dict__ if hasattr(c, '__dict__') else str(c) for c in content_list]}, indent=2)
    )

# ---- Static Tools (Updated) ----
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
    """List devices from announce/status cache with projection info."""
    devices = device_store.list()
    device_summary = []
    for device in devices:
        device_id = device['device_id']
        status = "online" if device.get("online", False) else "offline"
        tools_count = len(device.get("tools", []))
        
        # Get projection info
        device_alias = projection_store.get_device_alias(device_id, device.get('name'))
        is_enabled = projection_store.is_device_enabled(device_id)
        
        # Count projected tools
        projected_tools = [t for t in tool_registry.list_all_tools() if t['device_id'] == device_id]
        projected_count = len(projected_tools)
        
        device_summary.append(
            f"• {device_id} → '{device_alias}' ({status}, {projected_count}/{tools_count} tools projected, {'enabled' if is_enabled else 'disabled'})"
        )
    
    summary_text = f"Found {len(devices)} devices:\n" + "\n".join(device_summary)
    return [TextContent(type="text", text=summary_text)]

@mcp.tool()
def get_tools(device_id: str) -> List[TextContent]:
    """List a device's announced tools with projection status."""
    d = device_store.get(device_id)
    if not d:
        return [TextContent(type="text", text=f"Error: device_id '{device_id}' not found")]
    
    tools = d.get("tools", [])
    if not tools:
        return [TextContent(type="text", text=f"Device {device_id} has no announced tools")]
    
    tool_summary = []
    for tool in tools:
        name = tool.get("name", "unknown")
        desc = tool.get("description", "")
        
        # Check projection status
        is_enabled = projection_store.is_tool_enabled(device_id, name)
        if is_enabled:
            projected_tool = projection_store.get_tool_projection(device_id, name, tool)
            projected_name = projected_tool["name"]
            projected_desc = projected_tool["description"]
            tool_summary.append(f"• {name} → '{projected_name}' (enabled): {projected_desc}")
        else:
            tool_summary.append(f"• {name} (disabled): {desc}")
    
    device_alias = projection_store.get_device_alias(device_id, d.get('name'))
    summary_text = f"Device {device_id} → '{device_alias}' tools ({len(tools)} total):\n" + "\n".join(tool_summary)
    return [TextContent(type="text", text=summary_text)]

# ---- Dynamic Tool Creation and Registration (Updated) ----
def register_dynamic_tools_for_device(device_id: str):
    """Register dynamic projected tools for a specific device with FastMCP using proper schemas"""
    device = device_store.get(device_id)
    if not device or not device.get("tools"):
        return
    
    log(f"[MCP] Registering dynamic projected tools for device {device_id}")
    
    for tool_info in device["tools"]:
        tool_name = tool_info.get("name", "")
        if not tool_name:
            continue
        
        # Check if tool is enabled in projection
        if not projection_store.is_tool_enabled(device_id, tool_name):
            log(f"[MCP] Skipping disabled tool: {tool_name} for device {device_id}")
            continue
        
        # Get projected tool configuration
        projected_tool = projection_store.get_tool_projection(device_id, tool_name, tool_info)
        projected_name = projected_tool["name"]
        
        # Create tool key using PROJECTED name, not original name
        tool_key = f"{projected_name}_{device_id}"
        
        log(f"[MCP] Processing tool: {tool_name} -> {projected_name} (key: {tool_key})")
        
        # Check if already registered
        if tool_registry.get_registered_function(tool_key):
            log(f"[MCP] Tool {tool_key} already registered, skipping")
            continue
        
        try:
            # Convert parameters to Pydantic model
            schema = tool_info.get("parameters", {})
            if not schema or schema.get("type") != "object":
                log(f"[MCP] Skipping tool {tool_key}: invalid or missing schema")
                continue
            
            ParamModel = json_schema_to_pydantic_model(f"{tool_key}_params", schema)
            
            # Create dynamic function with closure
            def create_tool_func(device_id_copy, original_tool_name_copy, projected_tool_copy, param_model):
                def tool_func(params: param_model) -> List[Union[ImageContent, TextContent]]:
                    """Dynamically generated projected device tool function with proper schema"""
                    args = params.dict()  # Pydantic 모델을 dict로 변환
                    log(f"[PROJECTED_TOOL] {projected_tool_copy['name']} ({original_tool_name_copy}) called with args: {json.dumps(args, indent=2)}")
                    
                    # Use original tool name for MQTT command
                    ok, resp = publish_cmd(device_id_copy, original_tool_name_copy, args)
                    
                    if not ok:
                        error_msg = resp.get("error", {}).get("message", "Unknown error")
                        return [TextContent(type="text", text=f"Error: {error_msg}")]
                    
                    return convert_response_to_content_list(resp)
                
                # Set function metadata using PROJECTED name
                tool_func.__name__ = projected_tool_copy["name"]  # Use projected name, not tool_key!
                tool_func.__doc__ = projected_tool_copy["description"]
                
                return tool_func
            
            # Create dynamic function
            dynamic_func = create_tool_func(device_id, tool_name, projected_tool, ParamModel)
            
            # Register with FastMCP using projected name
            decorated_func = mcp.tool()(dynamic_func)
            
            # Store in registry
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

# ========= FastAPI App for Asset Proxy (Updated) =========
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

def _proxy_stream(url: str, timeout=15):
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        for chunk in r.iter_content(chunk_size=16384):
            if chunk:
                yield chunk

# Create FastAPI app and mount MCP SSE
app = FastAPI(title="Bridge MCP (Asset Proxy + SSE + Projection Layer)")

@app.get("/", response_class=HTMLResponse)
def projection_manager():
    """Projection Manager Web Interface"""
    html_content = """<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MCP Bridge - Projection Manager</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; background: white; border-radius: 15px; box-shadow: 0 10px 30px rgba(0,0,0,0.2); overflow: hidden; }
        .header { background: linear-gradient(135deg, #2c3e50 0%, #34495e 100%); color: white; padding: 20px; text-align: center; }
        .header h1 { font-size: 2em; margin-bottom: 10px; }
        .status-badge { display: inline-block; padding: 5px 15px; border-radius: 20px; font-size: 0.9em; font-weight: bold; }
        .status-online { background: #27ae60; }
        .status-offline { background: #e74c3c; }
        .main-content { padding: 30px; }
        .section { margin-bottom: 30px; border: 1px solid #e0e0e0; border-radius: 10px; overflow: hidden; }
        .section-header { background: #f8f9fa; padding: 15px 20px; border-bottom: 1px solid #e0e0e0; font-weight: bold; color: #333; }
        .section-content { padding: 20px; }
        .device-card { border: 1px solid #e0e0e0; border-radius: 8px; margin-bottom: 15px; overflow: hidden; }
        .device-header { background: #f1f3f4; padding: 15px; display: flex; justify-content: space-between; align-items: center; }
        .device-info h3 { color: #333; margin-bottom: 5px; }
        .device-id { color: #666; font-size: 0.9em; font-family: monospace; }
        .device-status { display: flex; align-items: center; gap: 10px; }
        .device-tools { padding: 15px; background: #fafafa; }
        .tool-item { background: white; border: 1px solid #e0e0e0; border-radius: 5px; padding: 10px; margin-bottom: 10px; }
        .tool-controls { display: grid; grid-template-columns: 1fr 1fr 2fr; gap: 10px; align-items: center; margin-top: 10px; }
        .form-group { display: flex; flex-direction: column; }
        .form-group label { font-size: 0.8em; color: #666; margin-bottom: 3px; }
        input[type="text"], textarea, select { padding: 8px 12px; border: 1px solid #ccc; border-radius: 4px; font-size: 0.9em; }
        input[type="checkbox"] { transform: scale(1.2); }
        .btn { padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; font-weight: bold; transition: all 0.3s ease; }
        .btn-primary { background: #3498db; color: white; }
        .btn-primary:hover { background: #2980b9; }
        .btn-success { background: #27ae60; color: white; }
        .btn-success:hover { background: #219a52; }
        .btn-warning { background: #f39c12; color: white; }
        .btn-warning:hover { background: #e67e22; }
        .btn-danger { background: #e74c3c; color: white; }
        .btn-danger:hover { background: #c0392b; }
        .actions { display: flex; gap: 15px; margin-top: 30px; justify-content: center; }
        .loading { display: none; text-align: center; padding: 20px; }
        .spinner { border: 4px solid #f3f3f3; border-top: 4px solid #3498db; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 0 auto 10px; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        .alert { padding: 15px; border-radius: 5px; margin-bottom: 20px; display: none; }
        .alert-success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .alert-error { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        .alert-warning { background: #fff3cd; color: #856404; border: 1px solid #ffeaa7; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>MCP Bridge - Projection Manager</h1>
            <div id="status" class="status-badge status-offline">연결 확인 중...</div>
        </div>
        
        <div class="main-content">
            <div id="alert" class="alert"></div>
            
            <div class="loading" id="loading">
                <div class="spinner"></div>
                <div>데이터를 불러오는 중...</div>
            </div>
            
            <div class="section">
                <div class="section-header">장치 목록 및 Projection 설정</div>
                <div class="section-content">
                    <div id="devices-container"></div>
                </div>
            </div>
            
            <div class="section">
                <div class="section-header">글로벌 설정</div>
                <div class="section-content">
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
                        <label><input type="checkbox" id="auto-enable-devices"> 새 장치 자동 활성화</label>
                        <label><input type="checkbox" id="auto-enable-tools"> 새 도구 자동 활성화</label>
                    </div>
                </div>
            </div>
            
            <div class="actions">
                <button class="btn btn-primary" onclick="loadData()">새로고침</button>
                <button class="btn btn-success" onclick="saveConfig()">설정 저장</button>
                <button class="btn btn-warning" onclick="reloadConfig()">설정 리로드</button>
                <button class="btn btn-danger" onclick="restartContainer()">컨테이너 재시작</button>
            </div>
        </div>
    </div>

    <script>
        const API_BASE = '';  // 같은 서버에서 제공되므로 상대 경로 사용
        let currentConfig = {};
        
        document.addEventListener('DOMContentLoaded', function() {
            loadData();
            setInterval(checkStatus, 5000);
        });
        
        async function checkStatus() {
            try {
                const response = await fetch('/healthz');
                const data = await response.json();
                
                const statusEl = document.getElementById('status');
                if (response.ok && data.ok) {
                    statusEl.textContent = '온라인';
                    statusEl.className = 'status-badge status-online';
                } else {
                    statusEl.textContent = '오프라인';
                    statusEl.className = 'status-badge status-offline';
                }
            } catch (error) {
                const statusEl = document.getElementById('status');
                statusEl.textContent = '연결 실패';
                statusEl.className = 'status-badge status-offline';
            }
        }
        
        async function loadData() {
            showLoading(true);
            try {
                const projectionResponse = await fetch('/projections');
                const projectionData = await projectionResponse.json();
                
                const devicesResponse = await fetch('/devices');
                const devicesData = await devicesResponse.json();
                
                currentConfig = projectionData.config;
                renderDevices(devicesData, projectionData);
                renderGlobalSettings();
                
                showAlert('데이터를 성공적으로 불러왔습니다.', 'success');
            } catch (error) {
                showAlert('데이터 로딩 실패: ' + error.message, 'error');
            } finally {
                showLoading(false);
            }
        }
        
        function renderDevices(devices, projectionData) {
            const container = document.getElementById('devices-container');
            container.innerHTML = '';
            
            devices.forEach(device => {
                const deviceId = device.device_id;
                const projection = currentConfig.devices[deviceId] || {};
                
                const deviceEl = document.createElement('div');
                deviceEl.className = 'device-card';
                deviceEl.innerHTML = `
                    <div class="device-header">
                        <div class="device-info">
                            <h3>${device.name || deviceId}</h3>
                            <div class="device-id">${deviceId}</div>
                        </div>
                        <div class="device-status">
                            <span class="status-badge ${device.online ? 'status-online' : 'status-offline'}">
                                ${device.online ? '온라인' : '오프라인'}
                            </span>
                            <label>
                                <input type="checkbox" ${projection.enabled ? 'checked' : ''} 
                                       onchange="updateDeviceEnabled('${deviceId}', this.checked)"> 활성화
                            </label>
                        </div>
                    </div>
                    <div class="device-tools">
                        <div style="margin-bottom: 15px;">
                            <label>장치 별칭:</label>
                            <input type="text" value="${projection.device_alias || ''}" 
                                   onchange="updateDeviceAlias('${deviceId}', this.value)"
                                   placeholder="장치 표시 이름">
                        </div>
                        <div>
                            <strong>도구 목록 (${device.tools?.length || 0}개):</strong>
                            <div id="tools-${deviceId}">
                                ${renderTools(deviceId, device.tools || [], projection.tools || {})}
                            </div>
                        </div>
                    </div>
                `;
                container.appendChild(deviceEl);
            });
        }
        
        function renderTools(deviceId, tools, toolProjections) {
            return tools.map(tool => {
                const toolName = tool.name;
                const projection = toolProjections[toolName] || {};
                
                return `
                    <div class="tool-item">
                        <div><strong>${toolName}</strong></div>
                        <div style="font-size: 0.9em; color: #666; margin: 5px 0;">
                            ${tool.description || '설명 없음'}
                        </div>
                        <div class="tool-controls">
                            <div class="form-group">
                                <label>활성화</label>
                                <input type="checkbox" ${projection.enabled ? 'checked' : ''} 
                                       onchange="updateToolEnabled('${deviceId}', '${toolName}', this.checked)">
                            </div>
                            <div class="form-group">
                                <label>별칭</label>
                                <input type="text" value="${projection.alias || ''}" 
                                       onchange="updateToolAlias('${deviceId}', '${toolName}', this.value)"
                                       placeholder="도구 표시 이름">
                            </div>
                            <div class="form-group">
                                <label>설명 (override)</label>
                                <input type="text" value="${projection.description || ''}" 
                                       onchange="updateToolDescription('${deviceId}', '${toolName}', this.value)"
                                       placeholder="커스텀 설명 (선택사항)">
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        }
        
        function renderGlobalSettings() {
            const autoDevices = document.getElementById('auto-enable-devices');
            const autoTools = document.getElementById('auto-enable-tools');
            
            autoDevices.checked = currentConfig.global?.auto_enable_new_devices || false;
            autoTools.checked = currentConfig.global?.auto_enable_new_tools || false;
        }
        
        function updateDeviceEnabled(deviceId, enabled) {
            ensureDeviceExists(deviceId);
            currentConfig.devices[deviceId].enabled = enabled;
        }
        
        function updateDeviceAlias(deviceId, alias) {
            ensureDeviceExists(deviceId);
            currentConfig.devices[deviceId].device_alias = alias || null;
        }
        
        function updateToolEnabled(deviceId, toolName, enabled) {
            ensureDeviceExists(deviceId);
            ensureToolExists(deviceId, toolName);
            currentConfig.devices[deviceId].tools[toolName].enabled = enabled;
        }
        
        function updateToolAlias(deviceId, toolName, alias) {
            ensureDeviceExists(deviceId);
            ensureToolExists(deviceId, toolName);
            currentConfig.devices[deviceId].tools[toolName].alias = alias || null;
        }
        
        function updateToolDescription(deviceId, toolName, description) {
            ensureDeviceExists(deviceId);
            ensureToolExists(deviceId, toolName);
            currentConfig.devices[deviceId].tools[toolName].description = description || null;
        }
        
        function ensureDeviceExists(deviceId) {
            if (!currentConfig.devices) currentConfig.devices = {};
            if (!currentConfig.devices[deviceId]) {
                currentConfig.devices[deviceId] = {
                    enabled: true,
                    device_alias: null,
                    tools: {}
                };
            }
        }
        
        function ensureToolExists(deviceId, toolName) {
            if (!currentConfig.devices[deviceId].tools[toolName]) {
                currentConfig.devices[deviceId].tools[toolName] = {
                    enabled: true,
                    alias: null,
                    description: null
                };
            }
        }
        
        async function saveConfig() {
            currentConfig.global = {
                auto_enable_new_devices: document.getElementById('auto-enable-devices').checked,
                auto_enable_new_tools: document.getElementById('auto-enable-tools').checked
            };
            
            try {
                showLoading(true);
                const configJson = JSON.stringify(currentConfig, null, 2);
                
                const modal = document.createElement('div');
                modal.style.cssText = `
                    position: fixed; top: 0; left: 0; width: 100%; height: 100%;
                    background: rgba(0,0,0,0.8); z-index: 1000;
                    display: flex; align-items: center; justify-content: center;
                `;
                
                modal.innerHTML = `
                    <div style="background: white; padding: 30px; border-radius: 10px; max-width: 80%; max-height: 80%; overflow: auto;">
                        <h3>설정 JSON (복사해서 projection_config.json에 저장하세요)</h3>
                        <textarea style="width: 100%; height: 400px; font-family: monospace; font-size: 12px;" readonly>${configJson}</textarea>
                        <div style="margin-top: 15px; text-align: center;">
                            <button class="btn btn-primary" onclick="copyToClipboard('${configJson.replace(/'/g, "\\'")}')">클립보드에 복사</button>
                            <button class="btn btn-secondary" onclick="this.closest('div').parentElement.remove()">닫기</button>
                        </div>
                    </div>
                `;
                
                document.body.appendChild(modal);
                showAlert('설정이 준비되었습니다. JSON을 복사해서 파일에 저장하세요.', 'warning');
            } catch (error) {
                showAlert('설정 저장 실패: ' + error.message, 'error');
            } finally {
                showLoading(false);
            }
        }
        
        function copyToClipboard(text) {
            navigator.clipboard.writeText(text).then(function() {
                showAlert('클립보드에 복사되었습니다!', 'success');
            });
        }
        
        async function reloadConfig() {
            try {
                showLoading(true);
                const response = await fetch('/projections/reload', { method: 'POST' });
                const data = await response.json();
                
                if (response.ok) {
                    showAlert('설정이 리로드되었습니다. ' + data.message, 'success');
                    await loadData();
                } else {
                    showAlert('설정 리로드 실패: ' + data.message, 'error');
                }
            } catch (error) {
                showAlert('설정 리로드 실패: ' + error.message, 'error');
            } finally {
                showLoading(false);
            }
        }
        
        async function restartContainer() {
            if (!confirm('컨테이너를 재시작하시겠습니까? 이 작업은 PowerShell에서 수동으로 실행해야 합니다.')) {
                return;
            }
            
            const modal = document.createElement('div');
            modal.style.cssText = `
                position: fixed; top: 0; left: 0; width: 100%; height: 100%;
                background: rgba(0,0,0,0.8); z-index: 1000;
                display: flex; align-items: center; justify-content: center;
            `;
            
            modal.innerHTML = `
                <div style="background: white; padding: 30px; border-radius: 10px; max-width: 600px;">
                    <h3>컨테이너 재시작 명령어</h3>
                    <p>PowerShell에서 다음 명령어를 실행하세요:</p>
                    <div style="background: #f4f4f4; padding: 15px; border-radius: 5px; font-family: monospace; margin: 15px 0;">
                        docker compose restart bridge
                    </div>
                    <div style="text-align: center;">
                        <button class="btn btn-primary" onclick="copyToClipboard('docker compose restart bridge')">명령어 복사</button>
                        <button class="btn btn-secondary" onclick="this.closest('div').parentElement.remove()">닫기</button>
                    </div>
                </div>
            `;
            
            document.body.appendChild(modal);
        }
        
        function showLoading(show) {
            document.getElementById('loading').style.display = show ? 'block' : 'none';
        }
        
        function showAlert(message, type) {
            const alertEl = document.getElementById('alert');
            alertEl.textContent = message;
            alertEl.className = `alert alert-${type}`;
            alertEl.style.display = 'block';
            
            setTimeout(() => {
                alertEl.style.display = 'none';
            }, 5000);
        }
    </script>
</body>
</html>"""
    return html_content

@app.get("/healthz")
def healthz():
    return {"ok": True, "ts": now_iso(), "port": ACTIVE_API_PORT or API_PORT}

@app.get("/devices")
def list_devices_api():
    return device_store.list()

@app.get("/devices/{device_id}")
def device_detail(device_id: str):
    d = device_store.get(device_id)
    if not d:
        raise HTTPException(HTTPStatus.NOT_FOUND, "device not found")
    return d

@app.get("/projections")
def get_projections():
    """Get current projection configuration"""
    projected_tools = tool_registry.list_all_tools()
    return {
        "config": projection_store.config,
        "projected_tools": projected_tools,
        "stats": {
            "total_projected_tools": len(projected_tools),
            "devices_in_config": len(projection_store.config.get("devices", {}))
        }
    }

@app.post("/projections/reload")
def reload_projections():
    """Reload projection configuration from file"""
    try:
        projection_store.load_config()
        log("[PROJECTION] Configuration reloaded from file")
        
        # Clear our internal registry (won't affect FastMCP, but keeps our state clean)
        tool_registry._tools.clear()
        tool_registry._registered_funcs.clear()
        log("[PROJECTION] Cleared internal tool registry")
        
        # Re-register all tools with updated projections
        # Note: FastMCP doesn't support remove_tool in version 2.12.3
        # This will cause "Tool already exists" warnings but won't break anything
        total_registered = 0
        for device_id, device_data in device_store._by_id.items():
            tools = device_data.get("tools", [])
            device_name = device_data.get("name")
            tool_registry.register_device_tools(device_id, tools, device_name)
            register_dynamic_tools_for_device(device_id)
            
            # Count projected tools for this device
            device_projected = len([t for t in tool_registry.list_all_tools() if t['device_id'] == device_id])
            total_registered += device_projected
        
        log(f"[PROJECTION] Reload completed - {total_registered} tools processed")
        log("[PROJECTION] Note: FastMCP 2.12.3 doesn't support dynamic tool removal")
        log("[PROJECTION] To see projection changes in MCP clients, restart the container:")
        log("[PROJECTION] docker compose restart bridge")
        
        return {
            "ok": True,
            "message": f"Projection configuration reloaded successfully. Processed {total_registered} tools.",
            "warning": "FastMCP 2.12.3 doesn't support dynamic tool removal. Restart container to see changes in MCP clients.",
            "restart_command": "docker compose restart bridge",
            "stats": {
                "processed_tools": total_registered,
                "fastmcp_version": "2.12.3",
                "remove_tool_supported": False
            }
        }
    except Exception as e:
        log(f"[PROJECTION] Reload failed: {e}")
        raise HTTPException(HTTPStatus.INTERNAL_SERVER_ERROR, f"Failed to reload projections: {e}")

@app.post("/projections/force-restart")
def force_restart_server():
    """Force restart the application process (experimental)"""
    try:
        import os
        import signal
        projection_store.load_config()
        
        log("[PROJECTION] Configuration reloaded - attempting process restart")
        log("[PROJECTION] WARNING: This will terminate the current process")
        
        # Save current state if needed
        current_devices = len(device_store.list())
        current_tools = len(tool_registry.list_all_tools())
        
        def delayed_restart():
            import threading
            import time
            def restart_process():
                time.sleep(1)  # Give time for response to be sent
                os.kill(os.getpid(), signal.SIGTERM)
            
            threading.Thread(target=restart_process, daemon=True).start()
        
        delayed_restart()
        
        return {
            "ok": True,
            "message": "Process restart initiated. Server will restart in 1 second.",
            "warning": "This is experimental. Monitor docker logs to ensure restart succeeds.",
            "stats": {
                "devices_before_restart": current_devices,
                "tools_before_restart": current_tools
            }
        }
    except Exception as e:
        log(f"[PROJECTION] Force restart failed: {e}")
        raise HTTPException(HTTPStatus.INTERNAL_SERVER_ERROR, f"Failed to restart: {e}")

@app.post("/projections/hot-reload-attempt")
def hot_reload_attempt():
    """Attempt hot reload by creating new FastMCP instance (experimental)"""
    try:
        global mcp, tool_registry
        
        projection_store.load_config()
        log("[PROJECTION] Attempting experimental hot reload...")
        
        # Create new FastMCP instance
        from mcp.server.fastmcp import FastMCP
        new_mcp = FastMCP("bridge-mcp-reloaded")
        
        # Re-register static tools on new instance
        @new_mcp.tool()
        def invoke(device_id: str, tool: str, args: dict | None = None):
            """Generic tool invoker (fallback for any device tool)"""
            args = args or {}
            ok, resp = publish_cmd(device_id, tool, args)
            if not ok:
                error_msg = resp.get("error", {}).get("message", "Unknown error")
                return [TextContent(type="text", text=f"Error: {error_msg}")]
            return convert_response_to_content_list(resp)

        @new_mcp.tool()
        def list_devices():
            """List devices from announce/status cache with projection info."""
            devices = device_store.list()
            device_summary = []
            for device in devices:
                device_id = device['device_id']
                status = "online" if device.get("online", False) else "offline"
                tools_count = len(device.get("tools", []))
                
                device_alias = projection_store.get_device_alias(device_id, device.get('name'))
                is_enabled = projection_store.is_device_enabled(device_id)
                
                projected_tools = [t for t in tool_registry.list_all_tools() if t['device_id'] == device_id]
                projected_count = len(projected_tools)
                
                device_summary.append(
                    f"• {device_id} → '{device_alias}' ({status}, {projected_count}/{tools_count} tools projected, {'enabled' if is_enabled else 'disabled'})"
                )
            
            summary_text = f"Found {len(devices)} devices:\n" + "\n".join(device_summary)
            return [TextContent(type="text", text=summary_text)]

        @new_mcp.tool()
        def get_tools(device_id: str):
            """List a device's announced tools with projection status."""
            d = device_store.get(device_id)
            if not d:
                return [TextContent(type="text", text=f"Error: device_id '{device_id}' not found")]
            
            tools = d.get("tools", [])
            if not tools:
                return [TextContent(type="text", text=f"Device {device_id} has no announced tools")]
            
            tool_summary = []
            for tool in tools:
                name = tool.get("name", "unknown")
                desc = tool.get("description", "")
                
                is_enabled = projection_store.is_tool_enabled(device_id, name)
                if is_enabled:
                    projected_tool = projection_store.get_tool_projection(device_id, name, tool)
                    projected_name = projected_tool["name"]
                    projected_desc = projected_tool["description"]
                    tool_summary.append(f"• {name} → '{projected_name}' (enabled): {projected_desc}")
                else:
                    tool_summary.append(f"• {name} (disabled): {desc}")
            
            device_alias = projection_store.get_device_alias(device_id, d.get('name'))
            summary_text = f"Device {device_id} → '{device_alias}' tools ({len(tools)} total):\n" + "\n".join(tool_summary)
            return [TextContent(type="text", text=summary_text)]
        
        # Clear and re-register dynamic tools
        tool_registry._tools.clear()
        tool_registry._registered_funcs.clear()
        
        total_registered = 0
        for device_id, device_data in device_store._by_id.items():
            tools = device_data.get("tools", [])
            device_name = device_data.get("name")
            tool_registry.register_device_tools(device_id, tools, device_name)
            
            # Register projected tools on new instance
            if projection_store.is_device_enabled(device_id):
                for tool_info in tools:
                    tool_name = tool_info.get("name", "")
                    if not tool_name or not projection_store.is_tool_enabled(device_id, tool_name):
                        continue
                    
                    projected_tool = projection_store.get_tool_projection(device_id, tool_name, tool_info)
                    projected_name = projected_tool["name"]
                    tool_key = f"{projected_name}_{device_id}"
                    
                    try:
                        schema = tool_info.get("parameters", {})
                        if schema and schema.get("type") == "object":
                            ParamModel = json_schema_to_pydantic_model(f"{tool_key}_params", schema)
                            
                            def create_tool_func(device_id_copy, original_tool_name_copy, projected_tool_copy, param_model):
                                def tool_func(params: param_model):
                                    args = params.dict()
                                    ok, resp = publish_cmd(device_id_copy, original_tool_name_copy, args)
                                    if not ok:
                                        error_msg = resp.get("error", {}).get("message", "Unknown error")
                                        return [TextContent(type="text", text=f"Error: {error_msg}")]
                                    return convert_response_to_content_list(resp)
                                
                                tool_func.__name__ = tool_key
                                tool_func.__doc__ = projected_tool_copy["description"]
                                return tool_func
                            
                            dynamic_func = create_tool_func(device_id, tool_name, projected_tool, ParamModel)
                            decorated_func = new_mcp.tool()(dynamic_func)
                            tool_registry.set_registered_function(tool_key, decorated_func)
                            total_registered += 1
                            
                    except Exception as e:
                        log(f"[HOT_RELOAD] Failed to register tool {tool_key}: {e}")
            
            device_projected = len([t for t in tool_registry.list_all_tools() if t['device_id'] == device_id])
        
        # TODO: Replace old mcp instance (this is tricky and might not work)
        # mcp = new_mcp  # This probably won't work for existing connections
        
        log(f"[PROJECTION] Hot reload attempt completed - {total_registered} tools registered on new instance")
        
        return {
            "ok": True,
            "message": f"Hot reload attempted. Registered {total_registered} tools on new FastMCP instance.",
            "warning": "This is highly experimental and may not work for existing MCP connections.",
            "recommendation": "Container restart is still the most reliable method.",
            "stats": {
                "registered_tools": total_registered
            }
        }
    except Exception as e:
        log(f"[PROJECTION] Hot reload attempt failed: {e}")
        raise HTTPException(HTTPStatus.INTERNAL_SERVER_ERROR, f"Hot reload failed: {e}")

@app.get("/tools")
def list_dynamic_tools():
    """List all dynamically registered projected tools"""
    return {"tools": tool_registry.list_all_tools()}

@app.get("/assets/{request_id}")
def asset_proxy_first(request_id: str):
    with asset_lock:
        rec = asset_cache.get(request_id)
    if not rec:
        raise HTTPException(HTTPStatus.NOT_FOUND, "asset not found for request_id")
    ev = rec["event"]
    assets = ev.get("result", {}).get("assets", [])
    if not assets:
        raise HTTPException(HTTPStatus.BAD_REQUEST, "no assets in event")
    url = assets[0].get("url")
    mime = assets[0].get("mime", "application/octet-stream")
    if not url:
        raise HTTPException(HTTPStatus.BAD_REQUEST, "asset url missing")
    return StreamingResponse(_proxy_stream(url), media_type=mime)

@app.get("/assets/{request_id}/{index}")
def asset_proxy_indexed(request_id: str, index: int):
    with asset_lock:
        rec = asset_cache.get(request_id)
    if not rec:
        raise HTTPException(HTTPStatus.NOT_FOUND, "asset not found for request_id")
    ev = rec["event"]
    assets = ev.get("result", {}).get("assets", [])
    if not assets or index < 0 or index >= len(assets):
        raise HTTPException(HTTPStatus.NOT_FOUND, "asset index out of range")
    url = assets[index].get("url")
    mime = assets[index].get("mime", "application/octet-stream")
    if not url:
        raise HTTPException(HTTPStatus.BAD_REQUEST, "asset url missing")
    return StreamingResponse(_proxy_stream(url), media_type=mime)

# Mount MCP SSE endpoint
app.mount("/", mcp.sse_app())

# After FastMCP is fully initialized, register tools for any devices that announced early
register_all_announced_devices()

# ========= Main (Docker: just run uvicorn) =========
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
    uvicorn.run(app, host="0.0.0.0", port=int(ACTIVE_API_PORT), log_level="warning", access_log=False)