# reflex/core/config.py
import os
import yaml
from typing import Dict, Any, List

TOOLS_CONFIG_FILE = "tools.yaml"

class ConfigManager:
    """Configuration Manager for Reflex"""
    
    @staticmethod
    def load_tools_config() -> List[Dict[str, Any]]:
        """Load tools configuration from tools.yaml"""
        if not os.path.exists(TOOLS_CONFIG_FILE):
            # Default config if not exists
            return [
                {
                    "name": "default_bridge",
                    "type": "sse",
                    "url": "http://localhost:8083"
                }
            ]
            
        try:
            with open(TOOLS_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                return config.get('registries', [])
        except Exception as e:
            print(f"❌ Failed to load tools config: {e}")
            return []

    @staticmethod
    def save_tools_config(registries: List[Dict[str, Any]], virtual_tools: List[Dict[str, Any]] = None):
        """Save tools configuration to tools.yaml"""
        if virtual_tools is None:
            # Try to preserve existing virtual_tools if not provided
            existing = ConfigManager.load_virtual_tools_config()
            virtual_tools = existing

        config = {
            "registries": registries,
            "virtual_tools": virtual_tools or []
        }
        try:
            with open(TOOLS_CONFIG_FILE, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, sort_keys=False, allow_unicode=True)
            print(f"💾 Saved tools config to {TOOLS_CONFIG_FILE}")
        except Exception as e:
            print(f"❌ Failed to save tools config: {e}")

    @staticmethod
    def load_virtual_tools_config() -> List[Dict[str, Any]]:
        """Load virtual tools configuration from tools.yaml"""
        if not os.path.exists(TOOLS_CONFIG_FILE):
            return []
            
        try:
            with open(TOOLS_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                return config.get('virtual_tools', [])
        except Exception as e:
            # print(f"❌ Failed to load virtual tools config: {e}")
            return []

    @staticmethod
    def add_registry(registry_config: Dict[str, Any]):
        """Add a new registry to config"""
        registries = ConfigManager.load_tools_config()
        
        # Check for duplicate names
        for r in registries:
            if r['name'] == registry_config['name']:
                raise ValueError(f"Registry with name '{r['name']}' already exists")
                
        registries.append(registry_config)
        ConfigManager.save_tools_config(registries)

    @staticmethod
    def remove_registry(name: str):
        """Remove a registry from config"""
        registries = ConfigManager.load_tools_config()
        registries = [r for r in registries if r['name'] != name]
        ConfigManager.save_tools_config(registries)
