import threading
from typing import Dict, Any, List, Optional
from .utils import log
from .tool_projection import ToolProjectionStore

class DynamicToolRegistry:
    def __init__(self, projection_store: ToolProjectionStore):
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._registered_funcs: Dict[str, Any] = {}
        self.projection_store = projection_store
    
    def register_device_tools(self, device_id: str, tools: List[Dict[str, Any]], device_name: Optional[str] = None):
        with self._lock:
            old_keys = [k for k in self._tools.keys() if k.endswith(f"_{device_id}")]
            for k in old_keys:
                self._tools.pop(k, None)
                self._registered_funcs.pop(k, None)
            
            self.projection_store.auto_add_device(device_id, device_name, tools)
            device_alias = self.projection_store.get_device_alias(device_id, device_name)
            
            registered_count = 0
            for tool in tools:
                original_tool_name = tool.get("name", "")
                if not original_tool_name:
                    continue
                
                if not self.projection_store.is_tool_enabled(device_id, original_tool_name):
                    log(f"[TOOLS] Skipping disabled tool: {original_tool_name} for device {device_id}")
                    continue
                
                projected_tool = self.projection_store.get_tool_projection(device_id, original_tool_name, tool)
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
            
            log(f"[TOOLS] registered {registered_count}/{len(tools)} projected tools for device {device_id}")
    
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

    def clear_tools(self):
        """Clear all registered tools"""
        with self._lock:
            self._tools.clear()
            self._registered_funcs.clear()
            log("[TOOLS] Registry cleared")
