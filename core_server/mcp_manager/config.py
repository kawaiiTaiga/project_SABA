import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any

# ---- STDERR-only logging
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
def log(*a, **k): print(*a, file=sys.stderr, flush=True, **k)

# ========= Env =========
API_PORT = int(os.getenv("API_PORT", "8084"))
PROJECTION_CONFIG_PATH = os.getenv("PROJECTION_CONFIG_PATH", "./projection_config.json")
ROUTING_CONFIG_PATH = os.getenv("ROUTING_CONFIG_PATH", "./routing_config.json")
BRIDGE_API_URL = os.getenv("BRIDGE_API_URL", "http://bridge:8083")
DOCKER_HOST = os.getenv("DOCKER_HOST", "unix:///var/run/docker.sock")

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

class ConfigManager:
    def __init__(self, config_path: str, default_config: dict):
        self.config_path = config_path
        self.default_config = default_config
        self.ensure_config_exists()
    
    def ensure_config_exists(self):
        if not Path(self.config_path).exists():
            self.save_config(self.default_config)
            log(f"[CONFIG] Created default config at {self.config_path}")
    
    def load_config(self) -> Dict[str, Any]:
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            log(f"[CONFIG] Error loading {self.config_path}: {e}")
            return self.default_config.copy()
    
    def save_config(self, config: Dict[str, Any]) -> bool:
        try:
            os.makedirs(os.path.dirname(self.config_path) if os.path.dirname(self.config_path) else ".", exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            log(f"[CONFIG] Saved config to {self.config_path}")
            return True
        except Exception as e:
            log(f"[CONFIG] Error saving {self.config_path}: {e}")
            return False

projection_config = ConfigManager(PROJECTION_CONFIG_PATH, {
    "devices": {},
    "global": {"auto_enable_new_devices": True, "auto_enable_new_tools": True}
})

routing_config = ConfigManager(ROUTING_CONFIG_PATH, {
    "connections": [],
    "updated_at": now_iso()
})
