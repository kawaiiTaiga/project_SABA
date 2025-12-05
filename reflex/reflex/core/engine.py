# reflex/core/engine.py
import asyncio
import os
import logging
import yaml
from typing import Dict, List, Any
from datetime import datetime

from .reflex import Reflex
from .state import WorldState
from ..tools.registry import ToolManager
from reflex.triggers.base import TriggerBase
from reflex.actions.base import ActionBase
from .loader import ReflexLoader
from .config import ConfigManager


class ReflexEngine:
    """
    Reflex 실행 엔진

    역할:
    1. Schedule 체크 (1초마다)
    2. Reflex 매칭 & 실행
    3. Lifecycle 관리
    4. Hot Reload 지원
    """

    def __init__(self, tool_manager: ToolManager, state: WorldState, reflex_dir: str = "reflexes", log_dir: str = "logs"):
        self.tool_manager = tool_manager
        self.state = state
        self.reflexes: Dict[str, Reflex] = {}
        self.running = False
        self.reflex_dir = reflex_dir
        self.log_dir = log_dir
        
        os.makedirs(reflex_dir, exist_ok=True)
        os.makedirs(log_dir, exist_ok=True)
        
        self.logger = logging.getLogger("ReflexEngine")
        self.logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        
        fh = logging.FileHandler(os.path.join(log_dir, "engine.log"), encoding='utf-8')
        fh.setFormatter(formatter)
        self.logger.addHandler(fh)
        
        sh = logging.StreamHandler()
        sh.setFormatter(formatter)
        self.logger.addHandler(sh)

    def _validate_reflex(self, reflex: Reflex) -> List[str]:
        """유효성 검사"""
        errors: List[str] = []

        if not isinstance(reflex.trigger, TriggerBase):
            errors.append(f"Trigger must subclass TriggerBase, got {type(reflex.trigger)}")

        if not isinstance(reflex.action, ActionBase):
            errors.append(f"Action must subclass ActionBase, got {type(reflex.action)}")

        if reflex.lifecycle.type not in ("temporary", "persistent"):
            errors.append(f"Invalid lifecycle.type: {reflex.lifecycle.type}")
        if reflex.lifecycle.type == "temporary":
            if not reflex.lifecycle.ttl_sec or reflex.lifecycle.ttl_sec <= 0:
                errors.append("temporary lifecycle requires ttl_sec > 0")
            if reflex.lifecycle.max_runs is not None and reflex.lifecycle.max_runs <= 0:
                errors.append("max_runs must be > 0 if provided")

        missing = [t for t in reflex.tools if t not in self.tool_manager.tools]
        if missing:
            errors.append(f"Tools not found in registry: {missing}")

        return errors

    async def start(self):
        """엔진 시작"""
        self.running = True
        self.logger.info("Starting Reflex Engine...")
        
        self.load_reflexes()
        
        print("Connecting to MCP Servers...")
        
        registries = ConfigManager.load_tools_config()
        for reg in registries:
            if reg['type'] == 'sse':
                self.tool_manager.add_sse_registry(reg['name'], reg['url'])
            elif reg['type'] == 'stdio':
                self.tool_manager.add_stdio_registry(reg['name'], reg['command'], reg['args'], reg.get('env'))
        
        if not await self.tool_manager.connect():
            print("Failed to connect to MCP Servers. Exiting.")
            self.logger.error("Failed to connect to MCP Servers.")
            return
        
        print("Validating reflexes...")
        invalid_reflexes = []
        for reflex_id, reflex in list(self.reflexes.items()):
            errors = self._validate_reflex(reflex)
            if errors:
                print(f"Reflex '{reflex.name}' validation failed:")
                self.logger.warning(f"Reflex '{reflex.name}' validation failed: {errors}")
                for err in errors:
                    print(f"   - {err}")
                invalid_reflexes.append(reflex_id)
        
        for reflex_id in invalid_reflexes:
            del self.reflexes[reflex_id]
        
        if invalid_reflexes:
            print(f"Removed {len(invalid_reflexes)} invalid reflex(es)\n")
        
        print("Reflex Engine started")
        print(f"   Loaded {len(self.reflexes)} reflex(es)")
        print(f"   Available tools: {self.tool_manager.list_tools()}\n")
        self.logger.info(f"Engine started with {len(self.reflexes)} reflexes.")

        try:
            await self._main_loop()
        except KeyboardInterrupt:
            print("\nInterrupted by user")
            self.logger.info("Interrupted by user")
        except Exception as e:
            print(f"\nEngine error: {e}")
            self.logger.error(f"Engine error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await self.stop()

    async def stop(self):
        """엔진 종료"""
        self.running = False
        await self.tool_manager.disconnect()
        print("Reflex Engine stopped")
        self.logger.info("Engine stopped")

    async def _main_loop(self):
        """메인 실행 루프 (Hot Reload 지원)"""
        print("Schedule loop started\n")
        
        # Hot reload 설정
        REFLEX_RELOAD_INTERVAL = 10  # 10초마다 reflex 체크
        TOOL_REFRESH_INTERVAL = 30   # 30초마다 tool 새로고침 (SABA 등 동적 tool 지원)
        
        last_reflex_reload = asyncio.get_event_loop().time()
        last_tool_refresh = asyncio.get_event_loop().time()
        known_reflex_files = set(self._get_reflex_files())

        while self.running:
            try:
                now = asyncio.get_event_loop().time()
                
                # ========================================
                # Hot Reload: Reflex 파일 감지
                # ========================================
                if now - last_reflex_reload > REFLEX_RELOAD_INTERVAL:
                    await self._hot_reload_reflexes(known_reflex_files)
                    last_reflex_reload = now
                
                # ========================================
                # Tool Refresh: SABA 등 동적 tool 지원
                # ========================================
                if now - last_tool_refresh > TOOL_REFRESH_INTERVAL:
                    await self._refresh_tools()
                    last_tool_refresh = now

                # ========================================
                # 기존 스케줄 체크
                # ========================================
                event = {
                    "type": "schedule_tick",
                    "timestamp": now,
                }

                for reflex in list(self.reflexes.values()):
                    await self._check_and_execute(reflex, event)

                await self._cleanup_expired()
                await asyncio.sleep(1)

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Loop error: {e}")
                self.logger.error(f"Loop error: {e}")
                await asyncio.sleep(1)
    
    def _get_reflex_files(self) -> set:
        """reflexes 디렉토리의 YAML 파일 목록 반환"""
        files = set()
        if os.path.exists(self.reflex_dir):
            for f in os.listdir(self.reflex_dir):
                if f.endswith('.yaml') or f.endswith('.yml'):
                    files.add(f)
        return files
    
    async def _hot_reload_reflexes(self, known_files: set):
        """새 reflex 파일 감지 및 로드"""
        current_files = self._get_reflex_files()
        
        # 새로 추가된 파일
        new_files = current_files - known_files
        if new_files:
            print(f"\n🔄 Hot Reload: Detected {len(new_files)} new reflex file(s)")
            for f in new_files:
                file_path = os.path.join(self.reflex_dir, f)
                reflex = ReflexLoader.load_from_file(file_path)
                if reflex:
                    # 검증 후 추가
                    errors = self._validate_reflex(reflex)
                    if not errors:
                        self.add_reflex(reflex)
                        self.logger.info(f"Hot loaded reflex: {reflex.name}")
                    else:
                        print(f"   ❌ Validation failed for {f}: {errors}")
            known_files.update(new_files)
        
        # 삭제된 파일
        removed_files = known_files - current_files
        if removed_files:
            print(f"\n🔄 Hot Reload: Detected {len(removed_files)} removed reflex file(s)")
            for f in removed_files:
                reflex_id = os.path.splitext(f)[0]
                if reflex_id in self.reflexes:
                    self.remove_reflex(reflex_id)
                    self.logger.info(f"Hot removed reflex: {reflex_id}")
            known_files -= removed_files
    
    async def _refresh_tools(self):
        """
        Tool 새로고침 (SABA처럼 동적으로 tool이 생기고 사라지는 경우)
        기존 연결 유지하면서 tool 목록만 새로고침
        """
        try:
            old_tool_count = len(self.tool_manager.list_tools())
            
            # 각 레지스트리에서 tool 목록 새로고침
            for name, registry in self.tool_manager.registries.items():
                if registry._connected and registry.session:
                    try:
                        # 기존 tool 목록 백업
                        old_tools = set(registry.tools.keys())
                        
                        # MCP에서 현재 tool 목록 가져오기
                        tools_result = await registry.session.list_tools()
                        current_tools = {t.name for t in tools_result.tools}
                        
                        # 새로 추가된 tool
                        new_tools = current_tools - old_tools
                        if new_tools:
                            print(f"\n🔄 Tool Refresh [{name}]: +{len(new_tools)} new tool(s)")
                            for tool in tools_result.tools:
                                if tool.name in new_tools:
                                    registry.tools[tool.name] = registry._create_tool_function(tool.name, tool)
                                    registry.tool_schemas[tool.name] = {
                                        'name': tool.name,
                                        'description': tool.description,
                                        'parameters': tool.inputSchema if hasattr(tool, 'inputSchema') else {}
                                    }
                                    print(f"   + {tool.name}")
                        
                        # 삭제된 tool
                        removed_tools = old_tools - current_tools
                        if removed_tools:
                            print(f"\n🔄 Tool Refresh [{name}]: -{len(removed_tools)} removed tool(s)")
                            for tool_name in removed_tools:
                                del registry.tools[tool_name]
                                if tool_name in registry.tool_schemas:
                                    del registry.tool_schemas[tool_name]
                                print(f"   - {tool_name}")
                    except Exception as e:
                        # 개별 레지스트리 에러는 무시
                        pass
            
            new_tool_count = len(self.tool_manager.list_tools())
            if old_tool_count != new_tool_count:
                print(f"   Tools: {old_tool_count} → {new_tool_count}")
                self.logger.info(f"Tool refresh: {old_tool_count} → {new_tool_count}")
                
        except Exception as e:
            # 전체 에러도 무시 (엔진 안정성)
            pass

    async def _check_and_execute(self, reflex: Reflex, event: Dict[str, Any]):
        """Reflex 체크 & 실행"""
        if not reflex.enabled:
            return

        if reflex.should_expire():
            return

        try:
            current_state = self.state.get_all()
            # check() now returns Tuple[bool, Dict]
            fired, trigger_context = await reflex.trigger.check(event, current_state)
            if not fired:
                return

            print(f"Reflex '{reflex.name}' triggered!")
            print(f"   ID: {reflex.id}")
            print(f"   Trigger: {reflex.trigger}")
            print(f"   Trigger Context: {trigger_context}")
            self.logger.info(f"Reflex '{reflex.name}' triggered")
            self._log_reflex(reflex.id, f"Triggered (context: {trigger_context})")

            available_tools = self.tool_manager.get_tools_for_reflex(reflex.tools)
            if not available_tools:
                print(f"   No tools available")
                self.logger.warning(f"Reflex '{reflex.name}' triggered but no tools available")
                self._log_reflex(reflex.id, "No tools available", level="WARNING")
                return

            result = await reflex.action.execute(
                event=event, 
                state=current_state, 
                tools=available_tools,
                trigger=trigger_context
            )

            reflex.increment_runs()

            if reflex.lifecycle.max_runs:
                if reflex.metadata["runs"] >= reflex.lifecycle.max_runs:
                    reflex.enabled = False
                    print(f"   Reached max_runs ({reflex.lifecycle.max_runs}), disabled")
                    self._log_reflex(reflex.id, f"Reached max_runs ({reflex.lifecycle.max_runs}), disabled")

            print(f"   Executed successfully")
            print(f"   Runs: {reflex.metadata['runs']}")
            self.logger.info(f"Reflex '{reflex.name}' executed successfully")

            if result.get("success"):
                # Log text response (e.g., LLM output or Tool result)
                text_output = result.get("text", "")
                if text_output:
                    print(f"   Output: {text_output[:200]}...")
                    self._log_reflex(reflex.id, f"Output: {text_output}", level="RESULT")
                
                # Log tool calls and their results
                tool_calls = result.get("tool_calls", [])
                if tool_calls:
                    print(f"   Tool calls: {len(tool_calls)}")
                    for tc in tool_calls:
                        tool_name = tc.get('tool', 'unknown')
                        tool_result = tc.get('result', tc.get('error', 'no result'))
                        result_str = str(tool_result)[:500]
                        self._log_reflex(reflex.id, f"Tool [{tool_name}]: {result_str}", level="RESULT")
                
                self._log_reflex(reflex.id, f"Executed OK. Runs: {reflex.metadata['runs']}")
            else:
                error_msg = result.get('error', 'Unknown error')
                print(f"   Execution failed: {error_msg}")
                self.logger.warning(f"Reflex '{reflex.name}' execution failed: {error_msg}")
                self._log_reflex(reflex.id, f"Execution failed: {error_msg}", level="ERROR")
            print()

        except Exception as e:
            print(f"   Error: {e}")
            self.logger.error(f"Reflex '{reflex.name}' error: {e}")
            self._log_reflex(reflex.id, f"Error: {e}", level="ERROR")
            import traceback
            traceback.print_exc()
            print()

    async def _cleanup_expired(self):
        """만료된 Reflex 정리"""
        expired_ids = [
            rid for rid, r in self.reflexes.items() if r.should_expire()
        ]
        for rid in expired_ids:
            reflex = self.reflexes[rid]
            print(f"Reflex '{reflex.name}' expired and removed")
            self.logger.info(f"Reflex '{reflex.name}' expired and removed")
            del self.reflexes[rid]

    def add_reflex(self, reflex: Reflex, validate: bool = False):
        """Reflex 추가"""
        if validate:
            errors = self._validate_reflex(reflex)
            if errors:
                print(f"Failed to register reflex '{reflex.name}':")
                for err in errors:
                    print(f"   - {err}")
                print()
                return False

        self.reflexes[reflex.id] = reflex
        print(f"Added reflex: {reflex.name}")
        print(f"   ID: {reflex.id}")
        print(f"   Trigger: {reflex.trigger}")
        print(f"   Action: {reflex.action}")
        print(f"   Tools: {reflex.tools}")
        print(f"   Lifecycle: {reflex.lifecycle.type}\n")
        return True

    def remove_reflex(self, reflex_id: str):
        """Reflex 제거"""
        if reflex_id in self.reflexes:
            reflex = self.reflexes[reflex_id]
            del self.reflexes[reflex_id]
            print(f"Removed reflex: {reflex.name}")

    def get_reflex(self, reflex_id: str) -> Reflex:
        """Reflex 조회"""
        return self.reflexes.get(reflex_id)

    def list_reflexes(self) -> List[Dict[str, Any]]:
        """Reflex 목록"""
        return [
            {
                "id": r.id,
                "name": r.name,
                "enabled": r.enabled,
                "runs": r.metadata.get("runs", 0),
                "type": r.trigger.type,
            }
            for r in self.reflexes.values()
        ]

    def enable_reflex(self, reflex_id: str):
        """Reflex 활성화"""
        if reflex_id in self.reflexes:
            self.reflexes[reflex_id].enabled = True
            print(f"Reflex {reflex_id} enabled")
            self.logger.info(f"Reflex {reflex_id} enabled")

    def disable_reflex(self, reflex_id: str):
        """Reflex 비활성화"""
        if reflex_id in self.reflexes:
            self.reflexes[reflex_id].enabled = False
            print(f"Reflex {reflex_id} disabled")
            self.logger.info(f"Reflex {reflex_id} disabled")

    def load_reflexes(self):
        """파일에서 Reflex 로드"""
        print(f"Loading reflexes from {self.reflex_dir}...")
        loaded_reflexes = ReflexLoader.load_all(self.reflex_dir)
        for reflex in loaded_reflexes:
            self.add_reflex(reflex)
        self.logger.info(f"Loaded {len(loaded_reflexes)} reflexes from file.")

    def _log_reflex(self, reflex_id: str, message: str, level: str = "INFO"):
        """Reflex 개별 로그 기록 - .log 파일과 YAML 모두에 저장"""
        dt = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Save to .log file
        log_file = os.path.join(self.log_dir, f"{reflex_id}.log")
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"[{dt}] [{level}] {message}\n")
        except Exception as e:
            print(f"Failed to write log file: {e}")
        
        # Save to reflex YAML
        yaml_path = os.path.join(self.reflex_dir, f"{reflex_id}.yaml")
        if os.path.exists(yaml_path):
            try:
                with open(yaml_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
                
                if 'logs' not in data:
                    data['logs'] = []
                
                data['logs'].append({
                    'time': dt,
                    'status': level,
                    'message': message
                })
                
                # Keep only last 50 logs
                data['logs'] = data['logs'][-50:]
                
                # Update metadata
                if 'metadata' not in data:
                    data['metadata'] = {}
                data['metadata']['last_run'] = dt
                
                with open(yaml_path, 'w', encoding='utf-8') as f:
                    yaml.dump(data, f, sort_keys=False, allow_unicode=True)
            except Exception as e:
                print(f"Failed to write YAML log: {e}")