#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Single-file MQTT <-> MCP Bridge (Improved with proper image handling)
- MQTT ingest: mcp/dev/+/announce|status|events
- In-memory DeviceStore
- Command Router (request_id matching with timeout)
- Asset Proxy (FastAPI): /assets/<request_id>[/{index}]
- SSE endpoint for MCP: /sse
- MCP Server (FastMCP):
    tools:
      - invoke(device_id, tool, args)              # generic invoker (fallback)
      - {tool_name}_{device_id}(...)               # dynamic device-specific tools
    resources:
      - bridge://devices
      - bridge://device/<device_id>
      - bridge://asset/<request_id>
"""
import os, sys, json, time, uuid, threading, queue, requests, logging, socket, base64, io
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List, Union
from http import HTTPStatus

# FastMCP and MCP types
from mcp.server.fastmcp import FastMCP, Context
from mcp.types import ImageContent, TextContent, Resource

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

TOPIC_ANN  = "mcp/dev/+/announce"
TOPIC_STAT = "mcp/dev/+/status"
TOPIC_EV   = "mcp/dev/+/events"

ACTIVE_API_PORT: Optional[int] = None  # bound port (for proxy URL)

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ========= Dynamic Tool Registry =========
class DynamicToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Dict[str, Any]] = {}  # tool_key -> tool_info
        self._lock = threading.Lock()
        self._registered_funcs: Dict[str, Any] = {}  # tool_key -> registered function
    
    def register_device_tools(self, device_id: str, tools: List[Dict[str, Any]]):
        """Register all tools for a device"""
        with self._lock:
            # Remove old tools for this device
            old_keys = [k for k in self._tools.keys() if k.endswith(f"_{device_id}")]
            for k in old_keys:
                self._tools.pop(k, None)
                self._registered_funcs.pop(k, None)
            
            # Add new tools
            for tool in tools:
                tool_name = tool.get("name", "")
                if not tool_name:
                    continue
                    
                tool_key = f"{tool_name}_{device_id}"
                self._tools[tool_key] = {
                    "device_id": device_id,
                    "original_name": tool_name,
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", {}),
                    "tool_key": tool_key
                }
            
            log(f"[TOOLS] registered {len(tools)} tools for device {device_id}")
    
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
        
        # Register dynamic tools
        tools = msg.get("tools", [])
        tool_registry.register_device_tools(device_id, tools)

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

# ========= MQTT Client (thread) =========
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
            # Register dynamic tools after device announcement
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

# ========= Publish helper =========
def publish_cmd(device_id: str, tool: str, args: Dict[str, Any],
                request_id: Optional[str]=None, timeout_ms: int=CMD_TIMEOUT_MS):
    rid = request_id or uuid.uuid4().hex
    topic = f"mcp/dev/{device_id}/cmd"
    payload = {"type":"device.command","tool":tool,"args":args,"request_id":rid}
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

# ========= FastMCP Server =========
mcp = FastMCP("bridge-mcp")

# ---- Resources ----
@mcp.resource("bridge://devices")
def res_devices() -> Resource:
    return Resource(
        uri="bridge://devices",
        name="devices",
        description="Known devices with latest announce/status",
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
        description=f"Device {device_id} details",
        mimeType="application/json",
        text=json.dumps(d, indent=2)
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

# ---- Static Tools ----
@mcp.tool()
def invoke(device_id: str, tool: str, args: dict | None = None) -> List[Union[ImageContent, TextContent]]:
    """Generic tool invoker (fallback for any device tool)"""
    args = args or {}
    ok, resp = publish_cmd(device_id, tool, args)
    if not ok:
        error_msg = resp.get("error", {}).get("message", "Unknown error")
        return [TextContent(type="text", text=f"Error: {error_msg}")]
    
    return convert_response_to_content_list(resp)

@mcp.tool()
def list_devices() -> List[TextContent]:
    """List devices from announce/status cache."""
    devices = device_store.list()
    device_summary = []
    for device in devices:
        status = "online" if device.get("online", False) else "offline"
        tools_count = len(device.get("tools", []))
        device_summary.append(f"• {device['device_id']}: {device.get('name', 'Unknown')} ({status}, {tools_count} tools)")
    
    summary_text = f"Found {len(devices)} devices:\n" + "\n".join(device_summary)
    return [TextContent(type="text", text=summary_text)]

@mcp.tool()
def get_tools(device_id: str) -> List[TextContent]:
    """List a device's announced tools."""
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
        tool_summary.append(f"• {name}: {desc}")
    
    summary_text = f"Device {device_id} tools ({len(tools)} total):\n" + "\n".join(tool_summary)
    return [TextContent(type="text", text=summary_text)]

# ---- Dynamic Tool Creation and Registration ----
def create_dynamic_tool(tool_info: Dict[str, Any]):
    """Create a dynamic tool function for a specific device tool"""
    device_id = tool_info["device_id"]
    original_name = tool_info["original_name"]
    description = tool_info["description"]
    parameters = tool_info.get("parameters", {})
    
    def dynamic_tool_func(**kwargs) -> List[Union[ImageContent, TextContent]]:
        """Dynamically generated device tool function"""
        args = dict(kwargs)
        ok, resp = publish_cmd(device_id, original_name, args)
        
        if not ok:
            error_msg = resp.get("error", {}).get("message", "Unknown error")
            return [TextContent(type="text", text=f"Error: {error_msg}")]
        
        return convert_response_to_content_list(resp)
    
    # Set function metadata for FastMCP
    tool_key = tool_info["tool_key"]
    dynamic_tool_func.__name__ = tool_key
    dynamic_tool_func.__doc__ = f"{description} (device: {device_id})"
    
    return dynamic_tool_func

def register_dynamic_tools_for_device(device_id: str):
    """Register dynamic tools for a specific device with FastMCP"""
    device = device_store.get(device_id)
    if not device or not device.get("tools"):
        return
    
    log(f"[MCP] Registering dynamic tools for device {device_id}")
    
    for tool_info in device["tools"]:
        tool_name = tool_info.get("name", "")
        if not tool_name:
            continue
        
        tool_key = f"{tool_name}_{device_id}"
        
        # Check if already registered
        if tool_registry.get_registered_function(tool_key):
            log(f"[MCP] Tool {tool_key} already registered, skipping")
            continue
        
        try:
            # Create tool info for registry
            registry_tool_info = {
                "device_id": device_id,
                "original_name": tool_name,
                "description": tool_info.get("description", f"{tool_name} on {device_id}"),
                "parameters": tool_info.get("parameters", {}),
                "tool_key": tool_key
            }
            
            # Create dynamic function
            dynamic_func = create_dynamic_tool(registry_tool_info)
            
            # Register with FastMCP
            # Note: This registers the tool function directly
            decorated_func = mcp.tool()(dynamic_func)
            
            # Store in registry for tracking
            tool_registry.set_registered_function(tool_key, decorated_func)
            
            log(f"[MCP] Successfully registered dynamic tool: {tool_key}")
            
        except Exception as e:
            log(f"[MCP] Failed to register tool {tool_key}: {e}")

# ========= FastAPI App for Asset Proxy =========
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
import uvicorn

def _proxy_stream(url: str, timeout=15):
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        for chunk in r.iter_content(chunk_size=16384):
            if chunk:
                yield chunk

# Create FastAPI app and mount MCP SSE
app = FastAPI(title="Bridge MCP (Asset Proxy + SSE)")

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

@app.get("/tools")
def list_dynamic_tools():
    """List all dynamically registered tools"""
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
    uvicorn.run(app, host="0.0.0.0", port=int(ACTIVE_API_PORT), log_level="warning", access_log=False)