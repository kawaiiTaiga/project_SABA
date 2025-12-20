"""
Virtual Tool Module for SABA Bridge

가상 툴(Virtual Tool)은 여러 개의 실제 툴 호출을 하나의 툴 인터페이스로 묶어
병렬로 실행하는 메타 툴입니다.

파라미터 처리:
- 기본적으로 가상 툴의 파라미터는 각 바인딩된 툴에 자동으로 전달됩니다.
- 동일한 이름의 파라미터가 여러 툴에 있을 경우, 툴 이름을 접미사로 붙입니다.
  예: emotion -> emotion, emotion(ExpressEmotion), emotion(PlaySound)
"""

import json
import asyncio
import threading
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from concurrent.futures import ThreadPoolExecutor
from .utils import log


class VirtualToolStore:
    """가상 툴 설정을 저장하고 관리"""
    
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.config: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self.load_config()
    
    def load_config(self):
        """Load virtual tool configuration from JSON file"""
        try:
            if Path(self.config_path).exists():
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
                log(f"[VIRTUAL_TOOL] Loaded config from {self.config_path}")
            else:
                self.config = {
                    "virtual_tools": {},
                    "global": {
                        "default_timeout_ms": 10000
                    }
                }
                self.save_config()
                log(f"[VIRTUAL_TOOL] Created default config at {self.config_path}")
        except Exception as e:
            log(f"[VIRTUAL_TOOL] Error loading config: {e}")
            self.config = {"virtual_tools": {}, "global": {"default_timeout_ms": 10000}}
    
    def save_config(self):
        """Save current configuration to file"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            log(f"[VIRTUAL_TOOL] Error saving config: {e}")
            return False
    
    def reload_config(self):
        """Reload configuration from disk"""
        self.load_config()
    
    def get_all_virtual_tools(self) -> Dict[str, Any]:
        """Get all virtual tool definitions"""
        with self._lock:
            return self.config.get("virtual_tools", {})
    
    def get_virtual_tool(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a specific virtual tool definition"""
        with self._lock:
            return self.config.get("virtual_tools", {}).get(name)
    
    def create_virtual_tool(self, name: str, tool_def: Dict[str, Any]) -> bool:
        """Create a new virtual tool"""
        with self._lock:
            if "virtual_tools" not in self.config:
                self.config["virtual_tools"] = {}
            self.config["virtual_tools"][name] = tool_def
            result = self.save_config()
            if result:
                log(f"[VIRTUAL_TOOL] Created virtual tool: {name}")
            return result
    
    def update_virtual_tool(self, name: str, tool_def: Dict[str, Any]) -> bool:
        """Update an existing virtual tool"""
        with self._lock:
            if name not in self.config.get("virtual_tools", {}):
                return False
            self.config["virtual_tools"][name] = tool_def
            result = self.save_config()
            if result:
                log(f"[VIRTUAL_TOOL] Updated virtual tool: {name}")
            return result
    
    def delete_virtual_tool(self, name: str) -> bool:
        """Delete a virtual tool"""
        with self._lock:
            if name in self.config.get("virtual_tools", {}):
                del self.config["virtual_tools"][name]
                result = self.save_config()
                if result:
                    log(f"[VIRTUAL_TOOL] Deleted virtual tool: {name}")
                return result
            return False
    
    def build_virtual_tool_schema(self, name: str, device_store) -> Optional[Dict[str, Any]]:
        """
        가상 툴의 JSON Schema를 동적으로 생성합니다.
        
        각 바인딩된 툴의 파라미터를 수집하고, 이름이 충돌하면 툴 이름을 접미사로 추가합니다.
        """
        vt = self.get_virtual_tool(name)
        if not vt:
            return None
        
        bindings = vt.get("bindings", [])
        if not bindings:
            return {
                "type": "object",
                "properties": {},
                "required": []
            }
        
        # 파라미터 수집: {param_name: [(device_id, tool_name, param_schema), ...]}
        param_sources: Dict[str, List[Tuple[str, str, Dict]]] = {}
        
        for binding in bindings:
            device_id = binding.get("device_id")
            tool_name = binding.get("tool")
            
            device = device_store.get(device_id) if device_store else None
            if not device:
                continue
            
            # 디바이스의 툴 찾기
            device_tools = device.get("tools", [])
            tool_info = next((t for t in device_tools if t.get("name") == tool_name), None)
            if not tool_info:
                continue
            
            # 툴의 파라미터 스키마 추출
            params_schema = tool_info.get("parameters", {})
            properties = params_schema.get("properties", {})
            
            for param_name, param_schema in properties.items():
                if param_name not in param_sources:
                    param_sources[param_name] = []
                param_sources[param_name].append((device_id, tool_name, param_schema))
        
        # 최종 스키마 구성
        final_properties = {}
        final_required = []
        
        for param_name, sources in param_sources.items():
            if len(sources) == 1:
                # 단일 소스: 그대로 사용
                _, _, schema = sources[0]
                final_properties[param_name] = schema.copy()
            else:
                # 다중 소스: 공통 파라미터 + 개별 파라미터(툴명 접미사)
                # 공통 파라미터 (모든 툴에 동일하게 전달)
                _, _, first_schema = sources[0]
                final_properties[param_name] = first_schema.copy()
                final_properties[param_name]["description"] = (
                    first_schema.get("description", "") + 
                    f" (applies to all: {', '.join(s[1] for s in sources)})"
                )
        
        return {
            "type": "object",
            "properties": final_properties,
            "required": final_required
        }


class VirtualToolExecutor:
    """가상 툴 실행을 담당"""
    
    def __init__(self, virtual_tool_store: VirtualToolStore, 
                 device_store, cmd_waiter, mqtt_client_getter, ipc_agent=None):
        self.store = virtual_tool_store
        self.device_store = device_store
        self.cmd_waiter = cmd_waiter
        self.mqtt_client_getter = mqtt_client_getter
        self.ipc_agent = ipc_agent
        self._executor = ThreadPoolExecutor(max_workers=10)
    
    def set_ipc_agent(self, ipc_agent):
        """IPC agent setter for late initialization"""
        self.ipc_agent = ipc_agent
    
    def execute_sync(self, virtual_tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        가상 툴을 동기적으로 실행합니다.
        ThreadPoolExecutor를 사용하여 모든 바인딩된 툴을 병렬로 실행합니다.
        """
        from .command import publish_cmd
        from concurrent.futures import as_completed
        
        vt = self.store.get_virtual_tool(virtual_tool_name)
        if not vt:
            return {
                "ok": False,
                "error": f"Virtual tool '{virtual_tool_name}' not found"
            }
        
        bindings = vt.get("bindings", [])
        if not bindings:
            return {
                "ok": True,
                "results": [],
                "message": "No bindings configured for this virtual tool"
            }
        
        log(f"[VIRTUAL_TOOL] Executing '{virtual_tool_name}' with {len(bindings)} bindings")
        
        # 각 바인딩에 대한 future 생성
        futures = {}
        skipped = []  # Offline devices
        
        for binding in bindings:
            device_id = binding.get("device_id")
            tool_name = binding.get("tool")
            
            # Skip offline devices
            device = self.device_store.get(device_id)
            if not device or not device.get("online", False):
                log(f"[VIRTUAL_TOOL] Skipping offline device: {device_id}")
                skipped.append({
                    "device_id": device_id,
                    "tool": tool_name,
                    "ok": False,
                    "error": "Device is offline",
                    "skipped": True
                })
                continue
            
            # Get the tool's expected parameters from device's tool schema
            tool_params = None  # None means no schema found
            device_tools = device.get("tools", [])
            tool_info = next((t for t in device_tools if t.get("name") == tool_name), None)
            if tool_info:
                schema = tool_info.get("parameters", {})
                # Set even if empty - an empty set means tool takes no params
                tool_params = set(schema.get("properties", {}).keys())
            
            # args_map이 있으면 적용, 없으면 자동 전달 (filtered)
            args_map = binding.get("args_map")
            if args_map:
                mapped_args = {}
                for target_param, source_param in args_map.items():
                    if source_param in args:
                        mapped_args[target_param] = args[source_param]
            elif tool_params is not None:
                # Filter args to only include parameters the tool accepts
                # If tool_params is empty set, this results in empty dict (correct for no-param tools)
                mapped_args = {k: v for k, v in args.items() if k in tool_params}
                log(f"[VIRTUAL_TOOL] Filtered args for {device_id}/{tool_name}: {list(mapped_args.keys())}")
            else:
                # No schema info at all, pass all args (fallback)
                mapped_args = args.copy()
                log(f"[VIRTUAL_TOOL] No schema found for {device_id}/{tool_name}, passing all args")
            
            # Submit to thread pool
            def execute_tool(dev_id, t_name, t_args):
                return publish_cmd(
                    self.device_store, 
                    self.cmd_waiter, 
                    self.mqtt_client_getter(), 
                    dev_id, 
                    t_name, 
                    t_args,
                    ipc_agent=self.ipc_agent
                )
            
            future = self._executor.submit(execute_tool, device_id, tool_name, mapped_args)
            futures[future] = (device_id, tool_name)
        
        # 결과 수집
        results = []
        for future in as_completed(futures):
            device_id, tool_name = futures[future]
            try:
                ok, resp = future.result(timeout=30)
                results.append({
                    "device_id": device_id,
                    "tool": tool_name,
                    "ok": ok,
                    "response": resp
                })
            except Exception as e:
                results.append({
                    "device_id": device_id,
                    "tool": tool_name,
                    "ok": False,
                    "error": str(e)
                })
        
        # Add skipped offline devices to results
        results.extend(skipped)
        
        # 결과 요약
        success_count = sum(1 for r in results if r.get("ok"))
        skipped_count = len(skipped)
        
        return {
            "ok": success_count == len(results) - skipped_count,
            "virtual_tool": virtual_tool_name,
            "total": len(results),
            "success": success_count,
            "failed": len(results) - success_count - skipped_count,
            "skipped": skipped_count,
            "results": results
        }
