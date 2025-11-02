#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Projection Manager v2 - EVENT 지원 + 실시간 이벤트 모니터링
- Action/Event 탭 분리
- EVENT 테스트 및 실시간 로그
- MQTT events 토픽 구독
"""
import os, sys, json, logging, socket, requests, threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List
from pathlib import Path
from http import HTTPStatus
from collections import deque

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
import uvicorn
import docker

# Optional MQTT support
try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False
    log("[WARN] paho-mqtt not installed. Event monitoring disabled. Install with: pip install paho-mqtt")

# ---- STDERR-only logging
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
def log(*a, **k): print(*a, file=sys.stderr, flush=True, **k)

# ========= Env =========
API_PORT = int(os.getenv("API_PORT", "8084"))
PROJECTION_CONFIG_PATH = os.getenv("PROJECTION_CONFIG_PATH", "./projection_config.json")
BRIDGE_API_URL = os.getenv("BRIDGE_API_URL", "http://bridge:8083")
MQTT_HOST = os.getenv("MQTT_HOST", "mcp-broker")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ========= MQTT Event Collector =========
class MQTTEventCollector:
    def __init__(self, host: str, port: int, max_events: int = 100):
        self.host = host
        self.port = port
        self.max_events = max_events
        self.events: Dict[str, deque] = {}  # device_id -> deque of events
        self._lock = threading.Lock()
        self.client = None
        self._running = False
        self._mqtt_available = MQTT_AVAILABLE
        
    def start(self):
        """Start MQTT client in background thread"""
        if not self._mqtt_available:
            log("[MQTT] paho-mqtt not installed, event monitoring disabled")
            return
        
        if self._running:
            return
        
        try:
            self.client = mqtt.Client()
            self.client.on_connect = self._on_connect
            self.client.on_message = self._on_message
            
            self.client.connect(self.host, self.port, 60)
            self._running = True
            thread = threading.Thread(target=self.client.loop_forever, daemon=True)
            thread.start()
            log(f"[MQTT] Started event collector: {self.host}:{self.port}")
        except Exception as e:
            log(f"[MQTT] Failed to connect: {e}")
    
    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            client.subscribe("mcp/dev/+/events")
            log("[MQTT] Subscribed to mcp/dev/+/events")
        else:
            log(f"[MQTT] Connection failed: {rc}")
    
    def _on_message(self, client, userdata, msg):
        try:
            # Topic: mcp/dev/{device_id}/events
            parts = msg.topic.split('/')
            if len(parts) >= 3:
                device_id = parts[2]
                payload = json.loads(msg.payload.decode('utf-8'))
                
                with self._lock:
                    if device_id not in self.events:
                        self.events[device_id] = deque(maxlen=self.max_events)
                    
                    event_entry = {
                        "timestamp": now_iso(),
                        "device_id": device_id,
                        "payload": payload
                    }
                    self.events[device_id].append(event_entry)
                    
                log(f"[MQTT] Event from {device_id}: {payload.get('type', 'unknown')}")
        except Exception as e:
            log(f"[MQTT] Error processing message: {e}")
    
    def get_recent_events(self, device_id: str, limit: int = 20) -> List[Dict]:
        """Get recent events for a device"""
        if not self._mqtt_available:
            return []
        with self._lock:
            if device_id not in self.events:
                return []
            events = list(self.events[device_id])
            return events[-limit:] if len(events) > limit else events
    
    def clear_events(self, device_id: str):
        """Clear events for a device"""
        if not self._mqtt_available:
            return
        with self._lock:
            if device_id in self.events:
                self.events[device_id].clear()

mqtt_collector = MQTTEventCollector(MQTT_HOST, MQTT_PORT) if MQTT_AVAILABLE else None

# ========= Projection Config Manager =========
class ProjectionConfigManager:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.ensure_config_exists()
    
    def ensure_config_exists(self):
        if not Path(self.config_path).exists():
            default_config = {
                "devices": {},
                "global": {
                    "auto_enable_new_devices": True,
                    "auto_enable_new_tools": True,
                    "auto_enable_new_events": False
                }
            }
            self.save_config(default_config)
            log(f"[CONFIG] Created default config at {self.config_path}")
    
    def load_config(self) -> Dict[str, Any]:
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            log(f"[CONFIG] Error loading config: {e}")
            return {"devices": {}, "global": {"auto_enable_new_devices": True, "auto_enable_new_tools": True, "auto_enable_new_events": False}}
    
    def save_config(self, config: Dict[str, Any]) -> bool:
        try:
            os.makedirs(os.path.dirname(self.config_path) or '.', exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            log(f"[CONFIG] Saved config to {self.config_path}")
            return True
        except Exception as e:
            log(f"[CONFIG] Error saving config: {e}")
            return False

config_manager = ProjectionConfigManager(PROJECTION_CONFIG_PATH)

# ========= Bridge API Client =========
class BridgeAPIClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
    
    def get_devices(self) -> List[Dict[str, Any]]:
        try:
            response = requests.get(f"{self.base_url}/devices", timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            log(f"[BRIDGE_API] Error getting devices: {e}")
            return []
    
    def get_device(self, device_id: str) -> Optional[Dict[str, Any]]:
        try:
            response = requests.get(f"{self.base_url}/devices/{device_id}", timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            log(f"[BRIDGE_API] Error getting device {device_id}: {e}")
            return None
    
    def health_check(self) -> bool:
        try:
            response = requests.get(f"{self.base_url}/healthz", timeout=5)
            return response.status_code == 200
        except Exception:
            return False

bridge_api = BridgeAPIClient(BRIDGE_API_URL)

# ========= Docker Manager =========
class DockerManager:
    def __init__(self):
        self.client = None
        try:
            self.client = docker.from_env()
            log("[DOCKER] Connected to Docker daemon")
        except Exception as e:
            log(f"[DOCKER] Failed to connect to Docker: {e}")
    
    def restart_bridge_container(self) -> bool:
        if not self.client:
            return False
        try:
            container = self.client.containers.get("mcp-bridge")
            container.restart()
            log("[DOCKER] Bridge container restarted")
            return True
        except Exception as e:
            log(f"[DOCKER] Failed to restart: {e}")
            return False
    
    def get_bridge_status(self) -> Dict[str, Any]:
        if not self.client:
            return {"status": "docker_unavailable"}
        try:
            container = self.client.containers.get("mcp-bridge")
            return {
                "status": container.status,
                "running": container.status == "running",
                "id": container.id[:12],
                "name": container.name
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

docker_manager = DockerManager()

# ========= FastAPI App =========
app = FastAPI(title="Project Saba MCP Manager v2")

@app.on_event("startup")
def startup_event():
    """Start MQTT collector on startup"""
    if mqtt_collector:
        mqtt_collector.start()
    else:
        log("[MQTT] Event monitoring disabled (paho-mqtt not installed)")

@app.get("/", response_class=HTMLResponse)
def projection_manager_ui():
    """Enhanced UI with Action/Event tabs"""
    return HTMLResponse(content=get_html_template_v2())

@app.get("/healthz")
def healthz():
    return {"ok": True, "ts": now_iso(), "service": "projection-manager-v2", "port": API_PORT}

@app.get("/api/config")
def get_config():
    return config_manager.load_config()

@app.post("/api/config")
def save_config(config: dict):
    if config_manager.save_config(config):
        return {"ok": True, "message": "Configuration saved"}
    raise HTTPException(HTTPStatus.INTERNAL_SERVER_ERROR, "Failed to save")

@app.get("/api/devices")
def get_devices():
    return bridge_api.get_devices()

@app.get("/api/devices/{device_id}")
def get_device(device_id: str):
    device = bridge_api.get_device(device_id)
    if not device:
        raise HTTPException(HTTPStatus.NOT_FOUND, "Device not found")
    return device

@app.get("/api/devices/{device_id}/events")
def get_device_events(device_id: str, limit: int = 20):
    """Get recent events for a device"""
    if not mqtt_collector:
        return {"device_id": device_id, "events": [], "count": 0, "note": "MQTT not available (install paho-mqtt)"}
    events = mqtt_collector.get_recent_events(device_id, limit)
    return {"device_id": device_id, "events": events, "count": len(events)}

@app.delete("/api/devices/{device_id}/events")
def clear_device_events(device_id: str):
    """Clear event history for a device"""
    if not mqtt_collector:
        return {"ok": False, "message": "MQTT not available"}
    mqtt_collector.clear_events(device_id)
    return {"ok": True, "message": f"Cleared events for {device_id}"}

@app.post("/api/bridge/invoke")
def bridge_invoke(payload: dict):
    """Proxy to Bridge API invoke endpoint"""
    try:
        response = requests.post(
            f"{bridge_api.base_url}/invoke",
            json=payload,
            timeout=10
        )
        return response.json()
    except Exception as e:
        raise HTTPException(HTTPStatus.INTERNAL_SERVER_ERROR, f"Bridge invoke failed: {e}")

@app.get("/api/bridge/health")
def bridge_health():
    healthy = bridge_api.health_check()
    return {"healthy": healthy, "url": BRIDGE_API_URL}

@app.post("/api/bridge/reload")
def bridge_reload():
    return {"ok": True, "message": "Use restart button to apply changes"}

@app.get("/api/docker/status")
def docker_status():
    return docker_manager.get_bridge_status()

@app.post("/api/docker/restart")
def docker_restart():
    if docker_manager.restart_bridge_container():
        return {"ok": True, "message": "Bridge restarted"}
    raise HTTPException(HTTPStatus.INTERNAL_SERVER_ERROR, "Failed to restart")

def get_html_template_v2():
    """Enhanced HTML with Action/Event tabs and real-time event monitoring"""
    return '''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Project Saba MCP Manager v2</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: system-ui; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; padding: 20px; }
        .container { max-width: 1400px; margin: 0 auto; background: white; border-radius: 15px; box-shadow: 0 10px 30px rgba(0,0,0,0.2); overflow: hidden; }
        .header { background: linear-gradient(135deg, #2c3e50 0%, #34495e 100%); color: white; padding: 20px; text-align: center; }
        .header h1 { font-size: 2em; margin-bottom: 5px; }
        .header .version { font-size: 0.9em; opacity: 0.7; }
        .content { padding: 30px; }
        
        /* Tabs */
        .tabs { display: flex; border-bottom: 2px solid #e0e0e0; margin-bottom: 20px; }
        .tab { padding: 12px 24px; cursor: pointer; background: none; border: none; font-size: 1em; color: #666; transition: all 0.3s; }
        .tab:hover { background: #f5f5f5; }
        .tab.active { color: #667eea; border-bottom: 3px solid #667eea; font-weight: 600; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        
        /* Device Cards */
        .device-card { background: #f9f9f9; border-radius: 10px; padding: 20px; margin-bottom: 15px; border-left: 4px solid #667eea; }
        .device-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }
        .device-name { font-size: 1.2em; font-weight: 600; }
        .device-status { padding: 4px 12px; border-radius: 20px; font-size: 0.85em; }
        .status-online { background: #4caf50; color: white; }
        .status-offline { background: #f44336; color: white; }
        
        /* Tool Lists */
        .tool-list { margin-top: 15px; }
        .tool-item { background: white; padding: 15px; margin-bottom: 10px; border-radius: 8px; border: 1px solid #e0e0e0; }
        .tool-header { display: flex; justify-content: space-between; align-items: center; }
        .tool-name { font-weight: 600; color: #333; }
        .tool-toggle { margin-left: auto; }
        .tool-desc { color: #666; font-size: 0.9em; margin-top: 8px; }
        
        /* Event specific */
        .event-item { border-left: 4px solid #ff9800; }
        .event-signals { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
        .signal-badge { background: #fff3e0; color: #e65100; padding: 4px 10px; border-radius: 12px; font-size: 0.85em; }
        .event-test-btn { background: #2196f3; color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; margin-top: 10px; }
        .event-test-btn:hover { background: #1976d2; }
        .event-log { background: #263238; color: #aed581; padding: 15px; border-radius: 8px; margin-top: 10px; max-height: 200px; overflow-y: auto; font-family: 'Courier New', monospace; font-size: 0.85em; }
        .event-log-entry { margin-bottom: 8px; }
        .event-log-time { color: #64b5f6; }
        .event-log-type { color: #ffd54f; }
        
        /* Buttons */
        button { cursor: pointer; transition: all 0.3s; }
        .btn-primary { background: #667eea; color: white; border: none; padding: 10px 20px; border-radius: 6px; font-size: 1em; }
        .btn-primary:hover { background: #5568d3; }
        .btn-danger { background: #f44336; color: white; border: none; padding: 10px 20px; border-radius: 6px; }
        .btn-danger:hover { background: #d32f2f; }
        
        /* Settings */
        .settings-section { background: #f9f9f9; padding: 20px; border-radius: 10px; margin-bottom: 20px; }
        .settings-section h3 { margin-bottom: 15px; }
        .checkbox-group { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
        
        /* Alert */
        .alert { padding: 15px; border-radius: 8px; margin-bottom: 20px; display: none; }
        .alert-success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .alert-error { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        
        /* Loading */
        .loading { text-align: center; padding: 20px; display: none; }
        .spinner { border: 4px solid #f3f3f3; border-top: 4px solid #667eea; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 0 auto; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        
        /* Toggle Switch */
        .switch { position: relative; display: inline-block; width: 50px; height: 24px; }
        .switch input { opacity: 0; width: 0; height: 0; }
        .slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #ccc; transition: .4s; border-radius: 24px; }
        .slider:before { position: absolute; content: ""; height: 18px; width: 18px; left: 3px; bottom: 3px; background-color: white; transition: .4s; border-radius: 50%; }
        input:checked + .slider { background-color: #4caf50; }
        input:checked + .slider:before { transform: translateX(26px); }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 Project Saba MCP Manager</h1>
            <div class="version">v2.0 - Event Monitoring Edition</div>
        </div>
        
        <div class="content">
            <div class="alert" id="alert"></div>
            <div class="loading" id="loading"><div class="spinner"></div></div>
            
            <!-- Main Tabs -->
            <div class="tabs">
                <button class="tab active" onclick="switchMainTab('devices')">Devices</button>
                <button class="tab" onclick="switchMainTab('settings')">Settings</button>
                <button class="tab" onclick="switchMainTab('bridge')">Bridge Status</button>
            </div>
            
            <div id="main-content">
                <!-- Devices Tab -->
                <div id="tab-devices" class="tab-content active">
                    <div id="devices-container"></div>
                </div>
                
                <!-- Settings Tab -->
                <div id="tab-settings" class="tab-content">
                    <div class="settings-section">
                        <h3>Global Settings</h3>
                        <div class="checkbox-group">
                            <input type="checkbox" id="auto-enable-devices">
                            <label for="auto-enable-devices">Auto-enable new devices</label>
                        </div>
                        <div class="checkbox-group">
                            <input type="checkbox" id="auto-enable-tools">
                            <label for="auto-enable-tools">Auto-enable new actions</label>
                        </div>
                        <div class="checkbox-group">
                            <input type="checkbox" id="auto-enable-events">
                            <label for="auto-enable-events">Auto-enable new events</label>
                        </div>
                        <button class="btn-primary" onclick="saveGlobalSettings()">Save Settings</button>
                    </div>
                </div>
                
                <!-- Bridge Status Tab -->
                <div id="tab-bridge" class="tab-content">
                    <div class="settings-section">
                        <h3>Bridge Container</h3>
                        <div id="bridge-status"></div>
                        <button class="btn-danger" onclick="restartBridge()">Restart Bridge</button>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        let currentConfig = {};
        let devices = [];
        let eventRefreshIntervals = {};
        
        // Main tab switching
        function switchMainTab(tabName) {
            document.querySelectorAll('.tabs .tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            event.target.classList.add('active');
            document.getElementById(`tab-${tabName}`).classList.add('active');
            
            if (tabName === 'bridge') loadBridgeStatus();
        }
        
        // Device sub-tab switching
        function switchDeviceTab(deviceId, tabName) {
            const container = document.getElementById(`device-${deviceId}`);
            container.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            container.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            container.querySelector(`[data-tab="${tabName}"]`).classList.add('active');
            container.querySelector(`#${deviceId}-${tabName}`).classList.add('active');
            
            if (tabName === 'events') {
                startEventRefresh(deviceId);
            } else {
                stopEventRefresh(deviceId);
            }
        }
        
        // Load data
        async function loadData() {
            try {
                showLoading(true);
                const [configResp, devicesResp] = await Promise.all([
                    fetch('/api/config'),
                    fetch('/api/devices')
                ]);
                
                currentConfig = await configResp.json();
                devices = await devicesResp.json();
                
                renderDevices();
                renderSettings();
            } catch (error) {
                showAlert('Failed to load data: ' + error.message, 'error');
            } finally {
                showLoading(false);
            }
        }
        
        function renderSettings() {
            const global = currentConfig.global || {};
            document.getElementById('auto-enable-devices').checked = global.auto_enable_new_devices !== false;
            document.getElementById('auto-enable-tools').checked = global.auto_enable_new_tools !== false;
            document.getElementById('auto-enable-events').checked = global.auto_enable_new_events === true;
        }
        
        function renderDevices() {
            const container = document.getElementById('devices-container');
            container.innerHTML = devices.map(device => {
                const tools = device.tools || [];
                const actions = tools.filter(t => t.kind !== 'event');
                const events = tools.filter(t => t.kind === 'event');
                const online = device.online;
                
                return `
                    <div class="device-card" id="device-${device.device_id}">
                        <div class="device-header">
                            <div class="device-name">${device.device_id}</div>
                            <div class="device-status ${online ? 'status-online' : 'status-offline'}">
                                ${online ? 'Online' : 'Offline'}
                            </div>
                        </div>
                        
                        <div class="tabs" style="border-bottom: 1px solid #ddd; margin-bottom: 15px;">
                            <button class="tab active" data-tab="actions" onclick="switchDeviceTab('${device.device_id}', 'actions')">
                                Actions (${actions.length})
                            </button>
                            <button class="tab" data-tab="events" onclick="switchDeviceTab('${device.device_id}', 'events')">
                                Events (${events.length})
                            </button>
                        </div>
                        
                        <!-- Actions Tab -->
                        <div id="${device.device_id}-actions" class="tab-content active">
                            ${renderToolList(device.device_id, actions, 'action')}
                        </div>
                        
                        <!-- Events Tab -->
                        <div id="${device.device_id}-events" class="tab-content">
                            ${renderToolList(device.device_id, events, 'event')}
                            ${events.length > 0 ? `
                                <div style="margin-top: 20px;">
                                    <h4>Event Log (Real-time)</h4>
                                    <button class="btn-primary" onclick="clearEventLog('${device.device_id}')">Clear Log</button>
                                    <div class="event-log" id="event-log-${device.device_id}">
                                        <div style="color: #64b5f6;">Waiting for events...</div>
                                    </div>
                                </div>
                            ` : ''}
                        </div>
                    </div>
                `;
            }).join('');
        }
        
        function renderToolList(deviceId, tools, kind) {
            if (tools.length === 0) {
                return `<div style="color: #999; padding: 20px; text-align: center;">No ${kind}s available</div>`;
            }
            
            return `<div class="tool-list">${tools.map(tool => {
                const toolConfig = currentConfig.devices?.[deviceId]?.tools?.[tool.name] || {};
                const enabled = toolConfig.enabled !== false;
                
                if (kind === 'event') {
                    const signals = tool.signals?.event_types || [];
                    return `
                        <div class="tool-item event-item">
                            <div class="tool-header">
                                <div class="tool-name">${tool.name}</div>
                                <label class="switch tool-toggle">
                                    <input type="checkbox" ${enabled ? 'checked' : ''} 
                                           onchange="toggleTool('${deviceId}', '${tool.name}', '${kind}', this.checked)">
                                    <span class="slider"></span>
                                </label>
                            </div>
                            <div class="tool-desc">${tool.description || 'No description'}</div>
                            ${signals.length > 0 ? `
                                <div class="event-signals">
                                    ${signals.map(s => `<span class="signal-badge">${s}</span>`).join('')}
                                </div>
                            ` : ''}
                            ${enabled ? `<button class="event-test-btn" onclick="testEventSubscribe('${deviceId}', '${tool.name}')">Test Subscribe</button>` : ''}
                        </div>
                    `;
                } else {
                    return `
                        <div class="tool-item">
                            <div class="tool-header">
                                <div class="tool-name">${tool.name}</div>
                                <label class="switch tool-toggle">
                                    <input type="checkbox" ${enabled ? 'checked' : ''} 
                                           onchange="toggleTool('${deviceId}', '${tool.name}', '${kind}', this.checked)">
                                    <span class="slider"></span>
                                </label>
                            </div>
                            <div class="tool-desc">${tool.description || 'No description'}</div>
                        </div>
                    `;
                }
            }).join('')}</div>`;
        }
        
        async function toggleTool(deviceId, toolName, kind, enabled) {
            if (!currentConfig.devices) currentConfig.devices = {};
            if (!currentConfig.devices[deviceId]) {
                currentConfig.devices[deviceId] = { enabled: true, device_alias: null, tools: {} };
            }
            if (!currentConfig.devices[deviceId].tools[toolName]) {
                currentConfig.devices[deviceId].tools[toolName] = { alias: null, description: null };
            }
            
            currentConfig.devices[deviceId].tools[toolName].enabled = enabled;
            currentConfig.devices[deviceId].tools[toolName].kind = kind;
            
            await saveConfig();
        }
        
        async function testEventSubscribe(deviceId, eventName) {
            try {
                showAlert(`Testing ${eventName} subscription...`, 'success');
                // Projection Manager를 통해 Bridge에 subscribe 요청
                const response = await fetch(`/api/bridge/invoke`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        device_id: deviceId,
                        tool: eventName,
                        args: { op: 'subscribe', interval_ms: 3000 }
                    })
                });
                
                const result = await response.json();
                
                if (response.ok && result.ok !== false) {
                    showAlert(`Subscribed to ${eventName}. Watch the event log below.`, 'success');
                    startEventRefresh(deviceId);
                } else {
                    const errorMsg = result.error?.message || result.message || 'Unknown error';
                    showAlert('Subscribe failed: ' + errorMsg, 'error');
                }
            } catch (error) {
                showAlert('Subscribe error: ' + error.message, 'error');
            }
        }
        
        function startEventRefresh(deviceId) {
            if (eventRefreshIntervals[deviceId]) return;
            
            eventRefreshIntervals[deviceId] = setInterval(async () => {
                try {
                    const response = await fetch(`/api/devices/${deviceId}/events?limit=10`);
                    const data = await response.json();
                    
                    const logDiv = document.getElementById(`event-log-${deviceId}`);
                    if (logDiv && data.events.length > 0) {
                        logDiv.innerHTML = data.events.map(e => {
                            const payload = e.payload;
                            const text = payload.result?.text || '';
                            const eventType = payload.result?.assets?.[0]?.event_type || 'unknown';
                            return `
                                <div class="event-log-entry">
                                    <span class="event-log-time">[${e.timestamp}]</span>
                                    <span class="event-log-type">${eventType}</span>: ${text}
                                </div>
                            `;
                        }).join('');
                    }
                } catch (error) {
                    console.error('Event refresh error:', error);
                }
            }, 2000);
        }
        
        function stopEventRefresh(deviceId) {
            if (eventRefreshIntervals[deviceId]) {
                clearInterval(eventRefreshIntervals[deviceId]);
                delete eventRefreshIntervals[deviceId];
            }
        }
        
        async function clearEventLog(deviceId) {
            try {
                await fetch(`/api/devices/${deviceId}/events`, { method: 'DELETE' });
                document.getElementById(`event-log-${deviceId}`).innerHTML = 
                    '<div style="color: #64b5f6;">Event log cleared. Waiting for new events...</div>';
                showAlert('Event log cleared', 'success');
            } catch (error) {
                showAlert('Failed to clear log: ' + error.message, 'error');
            }
        }
        
        async function saveConfig() {
            try {
                const response = await fetch('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(currentConfig)
                });
                
                if (response.ok) {
                    showAlert('Configuration saved', 'success');
                    return true;
                } else {
                    showAlert('Save failed', 'error');
                    return false;
                }
            } catch (error) {
                showAlert('Save error: ' + error.message, 'error');
                return false;
            }
        }
        
        async function saveGlobalSettings() {
            currentConfig.global = {
                auto_enable_new_devices: document.getElementById('auto-enable-devices').checked,
                auto_enable_new_tools: document.getElementById('auto-enable-tools').checked,
                auto_enable_new_events: document.getElementById('auto-enable-events').checked
            };
            await saveConfig();
        }
        
        async function loadBridgeStatus() {
            try {
                const response = await fetch('/api/docker/status');
                const status = await response.json();
                document.getElementById('bridge-status').innerHTML = `
                    <p>Status: <strong>${status.status}</strong></p>
                    <p>Container: ${status.name || 'N/A'}</p>
                    <p>ID: ${status.id || 'N/A'}</p>
                `;
            } catch (error) {
                document.getElementById('bridge-status').innerHTML = `<p style="color: red;">Error: ${error.message}</p>`;
            }
        }
        
        async function restartBridge() {
            if (!confirm('Restart Bridge container? This will cause a few seconds of service interruption.')) {
                return;
            }
            
            try {
                showLoading(true);
                const response = await fetch('/api/docker/restart', { method: 'POST' });
                
                if (response.ok) {
                    showAlert('Bridge restarted successfully!', 'success');
                    setTimeout(() => loadData(), 3000);
                } else {
                    showAlert('Restart failed', 'error');
                }
            } catch (error) {
                showAlert('Restart error: ' + error.message, 'error');
            } finally {
                showLoading(false);
            }
        }
        
        function showLoading(show) {
            document.getElementById('loading').style.display = show ? 'block' : 'none';
        }
        
        function showAlert(message, type) {
            const alertEl = document.getElementById('alert');
            alertEl.textContent = message;
            alertEl.className = `alert alert-${type}`;
            alertEl.style.display = 'block';
            setTimeout(() => { alertEl.style.display = 'none'; }, 5000);
        }
        
        // Initialize
        loadData();
        setInterval(loadData, 30000); // Refresh every 30 seconds
    </script>
</body>
</html>'''

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
    
    log(f"[boot] Projection Manager v2 API_PORT={ACTIVE_API_PORT}")
    log(f"[boot] PROJECTION_CONFIG_PATH={PROJECTION_CONFIG_PATH}")
    log(f"[boot] BRIDGE_API_URL={BRIDGE_API_URL}")
    log(f"[boot] MQTT_HOST={MQTT_HOST}:{MQTT_PORT}")
    log(f"[boot] Web Interface: http://0.0.0.0:{ACTIVE_API_PORT}")
    
    uvicorn.run(app, host="0.0.0.0", port=int(ACTIVE_API_PORT), log_level="warning", access_log=False)