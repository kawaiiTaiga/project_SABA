#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Projection Manager - 웹 관리 인터페이스 전용
- Projection 설정 파일 직접 읽기/쓰기
- Bridge API와 통신하여 장치 정보 조회
- Docker API를 통한 bridge 컨테이너 재시작
- 포트 8084에서 웹 인터페이스 제공
"""
import os, sys, json, logging, socket, requests
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List
from pathlib import Path
from http import HTTPStatus

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
import uvicorn
import docker

# ---- STDERR-only logging (STDIO-safe)
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
def log(*a, **k): print(*a, file=sys.stderr, flush=True, **k)

# ========= Env =========
API_PORT = int(os.getenv("API_PORT", "8084"))  # 웹 관리 인터페이스 전용 포트
PROJECTION_CONFIG_PATH = os.getenv("PROJECTION_CONFIG_PATH", "./projection_config.json")
BRIDGE_API_URL = os.getenv("BRIDGE_API_URL", "http://bridge:8083")
DOCKER_HOST = os.getenv("DOCKER_HOST", "unix:///var/run/docker.sock")

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ========= Projection Config Manager =========
class ProjectionConfigManager:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.ensure_config_exists()
    
    def ensure_config_exists(self):
        """Ensure config file exists with default values"""
        if not Path(self.config_path).exists():
            default_config = {
                "devices": {},
                "global": {
                    "auto_enable_new_devices": True,
                    "auto_enable_new_tools": True
                }
            }
            self.save_config(default_config)
            log(f"[CONFIG] Created default config at {self.config_path}")
    
    def load_config(self) -> Dict[str, Any]:
        """Load projection configuration from JSON file"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            log(f"[CONFIG] Loaded config from {self.config_path}")
            return config
        except Exception as e:
            log(f"[CONFIG] Error loading config: {e}")
            return {
                "devices": {},
                "global": {
                    "auto_enable_new_devices": True,
                    "auto_enable_new_tools": True
                }
            }
    
    def save_config(self, config: Dict[str, Any]) -> bool:
        """Save configuration to file"""
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            
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
        """Get devices from bridge API"""
        try:
            response = requests.get(f"{self.base_url}/devices", timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            log(f"[BRIDGE_API] Error getting devices: {e}")
            return []
    
    def get_device(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Get specific device from bridge API"""
        try:
            response = requests.get(f"{self.base_url}/devices/{device_id}", timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            log(f"[BRIDGE_API] Error getting device {device_id}: {e}")
            return None
    
    def health_check(self) -> bool:
        """Check if bridge API is healthy"""
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
        """Restart the bridge container"""
        if not self.client:
            log("[DOCKER] Docker client not available")
            return False
        
        try:
            container = self.client.containers.get("mcp-bridge")
            container.restart()
            log("[DOCKER] Bridge container restarted successfully")
            return True
        except docker.errors.NotFound:
            log("[DOCKER] Bridge container 'mcp-bridge' not found")
            return False
        except Exception as e:
            log(f"[DOCKER] Failed to restart bridge container: {e}")
            return False
    
    def get_bridge_status(self) -> Dict[str, Any]:
        """Get bridge container status"""
        if not self.client:
            return {"status": "docker_unavailable", "error": "Docker client not available"}
        
        try:
            container = self.client.containers.get("mcp-bridge")
            
            # 기본 정보만 안전하게 가져오기
            result = {
                "status": container.status,
                "running": container.status == "running",
                "id": container.id[:12],
                "name": container.name
            }
            
            # 이미지 정보는 별도로 안전하게 처리
            try:
                # attrs에서 직접 이미지 이름 가져오기 (API 호출 없이)
                image_info = container.attrs.get('Config', {}).get('Image', 'unknown')
                result["image"] = image_info
            except Exception as e:
                log(f"[DOCKER] Warning: Could not get image info: {e}")
                result["image"] = "unknown"
            
            return result
            
        except docker.errors.NotFound:
            log("[DOCKER] Container 'mcp-bridge' not found")
            return {
                "status": "container_not_found", 
                "error": "Container 'mcp-bridge' not found"
            }
        except Exception as e:
            log(f"[DOCKER] Failed to get bridge status: {e}")
            return {"status": "error", "error": str(e)}

docker_manager = DockerManager()

# ========= FastAPI App =========
app = FastAPI(title="Project Saba MCP Manager")

def get_html_template():
    """Get HTML template with minimal inline content"""
    return '''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Project Saba MCP Manager</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; background: white; border-radius: 15px; box-shadow: 0 10px 30px rgba(0,0,0,0.2); overflow: hidden; }
        .header { background: linear-gradient(135deg, #2c3e50 0%, #34495e 100%); color: white; padding: 20px; text-align: center; position: relative; }
        .header h1 { font-size: 2em; margin-bottom: 10px; }
        .header .subtitle { font-size: 0.9em; opacity: 0.8; margin-bottom: 15px; }
        .language-selector { position: absolute; top: 20px; right: 20px; }
        .language-selector select { padding: 5px 10px; border: none; border-radius: 5px; background: rgba(255,255,255,0.2); color: white; }
        .status-badge { display: inline-block; padding: 5px 15px; border-radius: 20px; font-size: 0.9em; font-weight: bold; margin: 0 5px; }
        .status-online { background: #27ae60; }
        .status-offline { background: #e74c3c; }
        .status-warning { background: #f39c12; }
        .main-content { padding: 30px; }
        .section { margin-bottom: 30px; border: 1px solid #e0e0e0; border-radius: 10px; overflow: hidden; }
        .section-header { background: #f8f9fa; padding: 15px 20px; border-bottom: 1px solid #e0e0e0; font-weight: bold; color: #333; }
        .section-content { padding: 20px; }
        .naming-rules { background: #f8f9fa; padding: 15px; border-radius: 5px; margin-top: 10px; font-size: 0.9em; color: #666; }
        .naming-rules strong { color: #333; }
        .btn { padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; font-weight: bold; transition: all 0.3s ease; }
        .btn-primary { background: #3498db; color: white; }
        .btn-success { background: #27ae60; color: white; }
        .btn-warning { background: #f39c12; color: white; }
        .btn-danger { background: #e74c3c; color: white; }
        .actions { display: flex; gap: 15px; margin-top: 30px; justify-content: center; flex-wrap: wrap; }
        .loading { display: none; text-align: center; padding: 20px; }
        .spinner { border: 4px solid #f3f3f3; border-top: 4px solid #3498db; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 0 auto 10px; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        .alert { padding: 15px; border-radius: 5px; margin-bottom: 20px; display: none; }
        .alert-success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .alert-error { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
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
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="language-selector">
                <select id="language-select" onchange="changeLanguage()">
                    <option value="ko">한국어</option>
                    <option value="en">English</option>
                </select>
            </div>
            <h1>Project Saba MCP Manager</h1>
            <div class="subtitle">IoT Device Tool Projection Control</div>
            <div>
                <span id="bridge-status" class="status-badge status-offline">Bridge: Checking...</span>
                <span id="docker-status" class="status-badge status-offline">Docker: Checking...</span>
            </div>
        </div>
        
        <div class="main-content">
            <div id="alert" class="alert"></div>
            
            <div class="loading" id="loading">
                <div class="spinner"></div>
                <div>Loading...</div>
            </div>
            
            <div class="section">
                <div class="section-header">Device List & Projection Settings</div>
                <div class="section-content">
                    <div class="naming-rules">
                        <strong>Alias Naming Rules:</strong><br>
                        • Only letters (a-z, A-Z), numbers (0-9), underscore (_), hyphen (-) allowed<br>
                        • No spaces, special characters, or non-ASCII characters<br>
                        • Examples: take_photo, camera-shot ✅ / take photo, 사진촬영 ❌
                    </div>
                    <div id="devices-container">Loading devices...</div>
                </div>
            </div>
            
            <div class="section">
                <div class="section-header">Global Settings</div>
                <div class="section-content">
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
                        <label><input type="checkbox" id="auto-enable-devices"> Auto-enable new devices</label>
                        <label><input type="checkbox" id="auto-enable-tools"> Auto-enable new tools</label>
                    </div>
                </div>
            </div>
            
            <div class="actions">
                <button class="btn btn-primary" onclick="loadData()">Refresh</button>
                <button class="btn btn-success" onclick="saveConfig()">Save Settings</button>
                <button class="btn btn-warning" onclick="reloadBridgeConfig()">Reload Bridge Config</button>
                <button class="btn btn-danger" onclick="restartBridge()">Restart Bridge</button>
            </div>
        </div>
    </div>

    <script>
        let currentConfig = {};
        let currentLanguage = 'ko';
        
        const translations = {
            ko: {
                'online': '온라인',
                'offline': '오프라인',
                'config_saved': '설정이 저장되었습니다!',
                'config_save_failed': '설정 저장 실패: ',
                'no_devices': '등록된 장치가 없습니다.',
                'enabled': '활성화'
            },
            en: {
                'online': 'Online',
                'offline': 'Offline',
                'config_saved': 'Configuration saved!',
                'config_save_failed': 'Configuration save failed: ',
                'no_devices': 'No registered devices.',
                'enabled': 'Enabled'
            }
        };
        
        function changeLanguage() {
            currentLanguage = document.getElementById('language-select').value;
            updateLanguage();
        }
        
        function updateLanguage() {
            // Update language-specific elements
            if (currentLanguage === 'ko') {
                document.querySelector('.subtitle').textContent = 'IoT 장치 도구 투영 제어';
                document.querySelector('.section-header').textContent = '장치 목록 및 Projection 설정';
                document.querySelector('.naming-rules strong').textContent = '별칭 명명 규칙:';
                document.querySelector('.naming-rules').innerHTML = `
                    <strong>별칭 명명 규칙:</strong><br>
                    • 영문자(a-z, A-Z), 숫자(0-9), 밑줄(_), 하이픈(-) 만 사용 가능<br>
                    • 공백이나 특수문자, 한글 사용 불가<br>
                    • 예시: take_photo, camera-shot ✅ / take photo, 사진촬영 ❌
                `;
            } else {
                document.querySelector('.subtitle').textContent = 'IoT Device Tool Projection Control';
                document.querySelector('.section-header').textContent = 'Device List & Projection Settings';
                document.querySelector('.naming-rules').innerHTML = `
                    <strong>Alias Naming Rules:</strong><br>
                    • Only letters (a-z, A-Z), numbers (0-9), underscore (_), hyphen (-) allowed<br>
                    • No spaces, special characters, or non-ASCII characters<br>
                    • Examples: take_photo, camera-shot ✅ / take photo, 사진촬영 ❌
                `;
            }
        }
        
        function t(key) {
            return translations[currentLanguage][key] || key;
        }
        
        document.addEventListener('DOMContentLoaded', function() {
            loadData();
            setInterval(checkStatus, 10000);
        });
        
        async function checkStatus() {
            try {
                const bridgeResponse = await fetch('/api/bridge/health');
                const bridgeData = await bridgeResponse.json();
                
                const bridgeStatusEl = document.getElementById('bridge-status');
                if (bridgeData.healthy) {
                    bridgeStatusEl.textContent = `Bridge: ${t('online')}`;
                    bridgeStatusEl.className = 'status-badge status-online';
                } else {
                    bridgeStatusEl.textContent = `Bridge: ${t('offline')}`;
                    bridgeStatusEl.className = 'status-badge status-offline';
                }
                
                const dockerResponse = await fetch('/api/docker/status');
                const dockerData = await dockerResponse.json();
                
                const dockerStatusEl = document.getElementById('docker-status');
                if (dockerData.running) {
                    dockerStatusEl.textContent = `Docker: ${t('online')}`;
                    dockerStatusEl.className = 'status-badge status-online';
                } else {
                    dockerStatusEl.textContent = `Docker: ${t('offline')}`;
                    dockerStatusEl.className = 'status-badge status-offline';
                }
            } catch (error) {
                console.error('Status check failed:', error);
            }
        }
        
        async function loadData() {
            showLoading(true);
            try {
                const configResponse = await fetch('/api/config');
                currentConfig = await configResponse.json();
                
                const devicesResponse = await fetch('/api/devices');
                const devicesData = await devicesResponse.json();
                
                renderDevices(devicesData);
                renderGlobalSettings();
                
                showAlert('Data loaded successfully.', 'success');
            } catch (error) {
                showAlert('Data loading failed: ' + error.message, 'error');
            } finally {
                showLoading(false);
                checkStatus();
            }
        }
        
        function renderDevices(devices) {
            const container = document.getElementById('devices-container');
            
            if (!devices || devices.length === 0) {
                container.innerHTML = `<p>${t('no_devices')}</p>`;
                return;
            }
            
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
                                ${device.online ? t('online') : t('offline')}
                            </span>
                            <label>
                                <input type="checkbox" ${projection.enabled !== false ? 'checked' : ''} 
                                       onchange="updateDeviceEnabled('${deviceId}', this.checked)"> ${t('enabled')}
                            </label>
                        </div>
                    </div>
                    <div class="device-tools">
                        <div style="margin-bottom: 15px;">
                            <label>Device Alias:</label>
                            <input type="text" value="${projection.device_alias || ''}" 
                                   onchange="updateDeviceAlias('${deviceId}', this.value)"
                                   placeholder="Device display name">
                        </div>
                        <div>
                            <strong>Tools (${device.tools?.length || 0}):</strong>
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
            if (!tools || tools.length === 0) {
                return '<p>No tools available.</p>';
            }
            
            return tools.map(tool => {
                const toolName = tool.name;
                const projection = toolProjections[toolName] || {};
                
                return `
                    <div class="tool-item">
                        <div><strong>${toolName}</strong></div>
                        <div style="font-size: 0.9em; color: #666; margin: 5px 0;">
                            ${tool.description || 'No description'}
                        </div>
                        <div class="tool-controls">
                            <div class="form-group">
                                <label>Enable</label>
                                <input type="checkbox" ${projection.enabled !== false ? 'checked' : ''} 
                                       onchange="updateToolEnabled('${deviceId}', '${toolName}', this.checked)">
                            </div>
                            <div class="form-group">
                                <label>Alias</label>
                                <input type="text" value="${projection.alias || ''}" 
                                       onchange="updateToolAlias('${deviceId}', '${toolName}', this.value)"
                                       placeholder="Tool display name">
                            </div>
                            <div class="form-group">
                                <label>Description (override)</label>
                                <input type="text" value="${projection.description || ''}" 
                                       onchange="updateToolDescription('${deviceId}', '${toolName}', this.value)"
                                       placeholder="Custom description (optional)">
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        }
        
        function renderGlobalSettings() {
            const autoDevices = document.getElementById('auto-enable-devices');
            const autoTools = document.getElementById('auto-enable-tools');
            
            autoDevices.checked = currentConfig.global?.auto_enable_new_devices !== false;
            autoTools.checked = currentConfig.global?.auto_enable_new_tools !== false;
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
                const response = await fetch('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(currentConfig)
                });
                
                const result = await response.json();
                
                if (response.ok) {
                    showAlert(t('config_saved'), 'success');
                } else {
                    showAlert(t('config_save_failed') + result.message, 'error');
                }
            } catch (error) {
                showAlert(t('config_save_failed') + error.message, 'error');
            } finally {
                showLoading(false);
            }
        }
        
        async function reloadBridgeConfig() {
            try {
                showLoading(true);
                const response = await fetch('/api/bridge/reload', { method: 'POST' });
                const result = await response.json();
                
                if (response.ok) {
                    showAlert('Bridge configuration reloaded: ' + result.message, 'success');
                } else {
                    showAlert('Bridge configuration reload failed: ' + result.message, 'error');
                }
            } catch (error) {
                showAlert('Bridge configuration reload failed: ' + error.message, 'error');
            } finally {
                showLoading(false);
            }
        }
        
        async function restartBridge() {
            if (!confirm('Restart Bridge container? This will cause a few seconds of service interruption.')) {
                return;
            }
            
            try {
                showLoading(true);
                const response = await fetch('/api/docker/restart', { method: 'POST' });
                const result = await response.json();
                
                if (response.ok) {
                    showAlert('Bridge container restarted successfully!', 'success');
                    setTimeout(() => {
                        checkStatus();
                        loadData();
                    }, 3000);
                } else {
                    showAlert('Bridge restart failed: ' + result.message, 'error');
                }
            } catch (error) {
                showAlert('Bridge restart failed: ' + error.message, 'error');
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
            
            setTimeout(() => {
                alertEl.style.display = 'none';
            }, 5000);
        }
    </script>
</body>
</html>'''

@app.get("/", response_class=HTMLResponse)
def projection_manager_ui():
    """Project Saba MCP Manager Web Interface"""
    return HTMLResponse(content=get_html_template())

# ========= API Endpoints =========

@app.get("/healthz")
def healthz():
    return {"ok": True, "ts": now_iso(), "service": "projection-manager", "port": API_PORT}

@app.get("/api/config")
def get_config():
    """Get current projection configuration"""
    return config_manager.load_config()

@app.post("/api/config")
def save_config(config: dict):
    """Save projection configuration"""
    if config_manager.save_config(config):
        return {"ok": True, "message": "Configuration saved successfully"}
    else:
        raise HTTPException(HTTPStatus.INTERNAL_SERVER_ERROR, "Failed to save configuration")

@app.get("/api/devices")
def get_devices():
    """Get devices from bridge API"""
    return bridge_api.get_devices()

@app.get("/api/devices/{device_id}")
def get_device(device_id: str):
    """Get specific device from bridge API"""
    return device

@app.get("/api/bridge/health")
def bridge_health():
    """Check bridge API health"""
    healthy = bridge_api.health_check()
    return {
        "healthy": healthy,
        "url": BRIDGE_API_URL,
        "port": 8083 if healthy else None
    }

@app.post("/api/bridge/reload")
def bridge_reload():
    """Trigger bridge configuration reload"""
    try:
        # Bridge API doesn't have reload endpoint in the clean version,
        # so we'll just return a success message with instruction
        return {
            "ok": True,
            "message": "Bridge configuration will be reloaded on next container restart",
            "instruction": "Use 'Bridge 재시작' button to apply changes"
        }
    except Exception as e:
        raise HTTPException(HTTPStatus.INTERNAL_SERVER_ERROR, f"Failed to reload bridge config: {e}")

@app.get("/api/docker/status")
def docker_status():
    """Get Docker container status"""
    return docker_manager.get_bridge_status()

@app.post("/api/docker/restart")
def docker_restart():
    """Restart bridge container"""
    if docker_manager.restart_bridge_container():
        return {"ok": True, "message": "Bridge container restarted successfully"}
    else:
        raise HTTPException(HTTPStatus.INTERNAL_SERVER_ERROR, "Failed to restart bridge container")

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
    log(f"[boot] Projection Manager API_PORT={ACTIVE_API_PORT}")
    log(f"[boot] PROJECTION_CONFIG_PATH={PROJECTION_CONFIG_PATH}")
    log(f"[boot] BRIDGE_API_URL={BRIDGE_API_URL}")
    log(f"[boot] Web Interface: http://0.0.0.0:{ACTIVE_API_PORT}")
    
    uvicorn.run(app, host="0.0.0.0", port=int(ACTIVE_API_PORT), log_level="warning", access_log=False)