# reflex/core/engine.py
import asyncio
import os
import shutil
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
from .database import DatabaseManager

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich import print as rprint


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
        
        # Initialize Database Manager
        self.db = DatabaseManager(os.path.join(log_dir, "execution_history.db"))
        
        self.console = Console()
        self.logger = logging.getLogger("ReflexEngine")
        self.logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        
        # 병렬 실행을 위한 실행 중인 reflex 추적
        self._running_reflexes: set = set()
        
        fh = logging.FileHandler(os.path.join(log_dir, "engine.log"), encoding='utf-8')
        fh.setFormatter(formatter)
        self.logger.addHandler(fh)
        
        sh = logging.StreamHandler()
        sh.setFormatter(formatter)
        self.logger.addHandler(sh)
        
        # IPC Server for Dashboard Interaction
        from .ipc import IPCServer
        self.ipc = IPCServer()

    def _validate_reflex(self, reflex: Reflex) -> List[str]:
        """유효성 검사"""
        errors: List[str] = []

        if not isinstance(reflex.trigger, TriggerBase):
            errors.append(f"Trigger must subclass TriggerBase, got {type(reflex.trigger)}")

        if not isinstance(reflex.action, ActionBase):
            errors.append(f"Action must subclass ActionBase, got {type(reflex.action)}")

        if reflex.lifecycle.type not in ("temporary", "persistent", "max_runs"):
            errors.append(f"Invalid lifecycle.type: {reflex.lifecycle.type}")
            
        if reflex.lifecycle.type == "temporary":
            if not reflex.lifecycle.ttl_sec or reflex.lifecycle.ttl_sec <= 0:
                errors.append("temporary lifecycle requires ttl_sec > 0")
                
        if reflex.lifecycle.type == "max_runs":
            if not reflex.lifecycle.max_runs or reflex.lifecycle.max_runs <= 0:
                errors.append("max_runs lifecycle requires max_runs > 0")
        
        if reflex.trigger.cooldown_sec < 0:
             errors.append("Trigger cooldown_sec must be >= 0")

        missing = [t for t in reflex.tools if t not in self.tool_manager.tools]
        if missing:
            errors.append(f"Tools not found in registry: {missing}")

        return errors

    async def start(self):
        """엔진 시작"""
        self.running = True
        self.logger.info("Starting Reflex Engine...")
        
        self.load_reflexes()
        
        # Start IPC
        await self.ipc.start()
        
        self.console.print("[bold blue]Connecting to MCP Servers...[/bold blue]")
        
        registries = ConfigManager.load_tools_config()
        for reg in registries:
            if reg['type'] == 'sse':
                self.tool_manager.add_sse_registry(reg['name'], reg['url'])
            elif reg['type'] == 'stdio':
                self.tool_manager.add_stdio_registry(reg['name'], reg['command'], reg['args'], reg.get('env'))
        
        # Load Virtual Tools
        virtual_tools_config = ConfigManager.load_virtual_tools_config()
        if virtual_tools_config:
            self.tool_manager.virtual_registry.load_virtual_tools(virtual_tools_config)
            self.console.print(f"   Loaded [cyan]{len(virtual_tools_config)}[/cyan] virtual tool config(s)")
        
        if not await self.tool_manager.connect():
            self.console.print("[bold red]Failed to connect to MCP Servers. Exiting.[/bold red]")
            self.logger.error("Failed to connect to MCP Servers.")
            self.console.print(f"[yellow]Removed {len(invalid_reflexes)} invalid reflex(es)[/yellow]\n")
        
        self.console.print(Panel(f"[bold green]Reflex Engine started[/bold green]\n   Loaded [cyan]{len(self.reflexes)}[/cyan] reflex(es)\n   Available tools: [cyan]{len(self.tool_manager.list_tools())}[/cyan]", title="System"))
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
        await self.ipc.stop()
        print("Reflex Engine stopped")
        self.logger.info("Engine stopped")

    async def _main_loop(self):
        """메인 실행 루프 (Hot Reload 지원)"""
        self.console.print("[dim]Schedule loop started[/dim]\n")
        
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
                # 이벤트 수집 (스케줄 + IPC)
                # ========================================
                events_to_process = []
                
                # 1. Schedule Tick
                events_to_process.append({
                    "type": "schedule_tick",
                    "timestamp": now,
                })
                
                # 2. IPC Triggers (Drain queue)
                while not self.ipc.trigger_queue.empty():
                    try:
                        msg = self.ipc.trigger_queue.get_nowait()
                        events_to_process.append({
                            "type": "ipc_event",
                            "name": msg.get("name"),
                            "timestamp": now,
                            "payload": msg
                        })
                        self.console.print(f"[magenta]IPC Trigger received: {msg.get('name')}[/magenta]")
                    except asyncio.QueueEmpty:
                        break

                # ========================================
                # Reflex 실행 판정
                # ========================================
                # 병렬로 모든 reflex 체크 및 실행
                tasks = []
                
                # Copy list to avoid modification during iteration if that were possible
                active_reflexes = list(self.reflexes.values())
                
                for event in events_to_process:
                    for reflex in active_reflexes:
                        # 이미 실행 중인 reflex는 건너뛰기 (중복 실행 방지)
                        # TODO: IPC 이벤트의 경우 중복 실행을 허용해야 할 수도 있음 (빠른 연속 trigger)
                        if reflex.id in self._running_reflexes:
                            continue
                            
                        tasks.append(self._check_and_execute(reflex, event))
                
                if tasks:
                    # 모든 태스크 병렬 실행
                    await asyncio.gather(*tasks, return_exceptions=True)

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
            self.console.print(f"\n[bold magenta]🔄 Hot Reload: Detected {len(new_files)} new reflex file(s)[/bold magenta]")
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
                        self.console.print(f"   [red]❌ Validation failed for {f}: {errors}[/red]")
            known_files.update(new_files)
        
        # 삭제된 파일
        removed_files = known_files - current_files
        if removed_files:
            self.console.print(f"\n[bold magenta]🔄 Hot Reload: Detected {len(removed_files)} removed reflex file(s)[/bold magenta]")
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
        """Reflex 체크 & 실행 (병렬 실행 지원)"""
        if not reflex.enabled:
            return

        if reflex.should_expire():
            return

        # Cooldown 체크
        if reflex.is_in_cooldown():
            # Debug log only if verbose? Just silently skip for now or debug print
            # print(f"Skipping {reflex.name} (Cooldown)")
            return

        try:
            current_state = self.state.get_all()
            # check() now returns Tuple[bool, Dict]
            fired, trigger_context = await reflex.trigger.check(event, current_state)
            if not fired:
                return

            # 실행 중으로 마킹 (중복 실행 방지)
            self._running_reflexes.add(reflex.id)

            # 실행 중으로 마킹 (중복 실행 방지)
            self._running_reflexes.add(reflex.id)

            self.console.rule(f"[bold cyan]Reflex Triggered: {reflex.name}[/bold cyan]")
            self.console.print(f"   ID: [cyan]{reflex.id}[/cyan]")
            self.console.print(f"   Trigger: [yellow]{reflex.trigger}[/yellow]")
            # self.console.print(f"   Context: {trigger_context}")
            
            self.logger.info(f"Reflex '{reflex.name}' triggered")
            self._log_reflex(reflex.id, f"Triggered (context: {trigger_context})")

            available_tools = self.tool_manager.get_tools_for_reflex(reflex.tools)
            
            # Only warn if tools were requested but not found. 
            # If no tools were requested (reflex.tools is empty), having no available_tools is expected.
            if reflex.tools and not available_tools:
                self.console.print(f"   [bold yellow]Warning: Requested tools unavailable[/bold yellow]")
                self.logger.warning(f"Reflex '{reflex.name}' requested tools but none available")
                self._log_reflex(reflex.id, "Requested tools unavailable", level="WARNING")
                # We do NOT return here, allowing the action to execute without tools (e.g. ChatAction)

            # Add IPC to context for interactive tools
            trigger_context['ipc'] = self.ipc

            result = await reflex.action.execute(
                event=event, 
                state=current_state, 
                tools=available_tools,
                trigger=trigger_context
            )

            reflex.increment_runs()

            if reflex.should_expire():
                reflex.enabled = False
                self.console.print(f"   [yellow]Reflex expired, disabled (Lifecycle: {reflex.lifecycle.type})[/yellow]")
                self._log_reflex(reflex.id, f"Reflex expired, disabled")

            self.console.print(f"   [bold green]Executed successfully[/bold green]")
            self.console.print(f"   Runs: {reflex.metadata['runs']}")
            self.logger.info(f"Reflex '{reflex.name}' executed successfully")

            # Prepare safe context for DB logging (remove non-serializable objects)
            db_context = trigger_context.copy()
            if 'ipc' in db_context:
                del db_context['ipc']

            if result.get("success"):
                # Log text response (e.g., LLM output or Tool result)
                text_output = result.get("text", "")
                if text_output:
                    self.console.print(Panel(text_output[:500] + ("..." if len(text_output) > 500 else ""), title="[green]Output[/green]", border_style="green"))
                    self._log_reflex(reflex.id, f"Output: {text_output}", level="RESULT")
                
                # Log tool calls and their results
                tool_calls = result.get("tool_calls", [])
                if tool_calls:
                    self.console.print(f"   Tool calls: [bold]{len(tool_calls)}[/bold]")
                    for tc in tool_calls:
                        tool_name = tc.get('tool', 'unknown')
                        tool_result = tc.get('result', tc.get('error', 'no result'))
                        result_str = str(tool_result)[:500]
                        self.console.print(f"   [blue]🔧 {tool_name}[/blue]: {result_str}")
                        self._log_reflex(reflex.id, f"Tool [{tool_name}]: {result_str}", level="RESULT")
                
                self._log_reflex(reflex.id, f"Executed OK. Runs: {reflex.metadata['runs']}")

                # Log to DB (Success)
                self.db.log_execution(
                    reflex_id=reflex.id,
                    reflex_name=reflex.name,
                    trigger_type=reflex.trigger.type,
                    trigger_context=db_context,
                    action_type=reflex.action.type,
                    status="SUCCESS",
                    output=result.get("text", ""),
                    tool_calls=result.get("tool_calls", []),
                    error_message=None
                )
            else:
                error_msg = result.get('error', 'Unknown error')
                self.console.print(f"   [bold red]Execution failed:[/bold red] {error_msg}")
                self.logger.warning(f"Reflex '{reflex.name}' execution failed: {error_msg}")
                self._log_reflex(reflex.id, f"Execution failed: {error_msg}", level="ERROR")
                
                # Log to DB (Failure)
                self.db.log_execution(
                    reflex_id=reflex.id,
                    reflex_name=reflex.name,
                    trigger_type=reflex.trigger.type,
                    trigger_context=db_context,
                    action_type=reflex.action.type,
                    status="ERROR",
                    output=None,
                    tool_calls=None,
                    error_message=error_msg
                )
            print()

        except Exception as e:
            self.console.print(f"   [bold red]Error:[/bold red] {e}")
            self.logger.error(f"Reflex '{reflex.name}' error: {e}")
            self._log_reflex(reflex.id, f"Error: {e}", level="ERROR")
            
            # Prepare safe context for DB logging
            db_context = locals().get('trigger_context', {}).copy()
            if 'ipc' in db_context:
                del db_context['ipc']

            # Log to DB (Exception)
            self.db.log_execution(
                reflex_id=reflex.id,
                reflex_name=reflex.name,
                trigger_type=reflex.trigger.type,
                trigger_context=db_context,
                action_type=reflex.action.type,
                status="ERROR",
                output=None,
                tool_calls=None,
                error_message=str(e)
            )
            import traceback
            traceback.print_exc()
            print()
        finally:
            # 실행 완료 후 마킹 해제
            self._running_reflexes.discard(reflex.id)

    async def _cleanup_expired(self):
        """만료된 Reflex 정리"""
        expired_ids = [
            rid for rid, r in self.reflexes.items() if r.should_expire()
        ]
        
        trash_dir = "trashcan"
        os.makedirs(trash_dir, exist_ok=True)
        
        for rid in expired_ids:
            reflex = self.reflexes[rid]
            self.console.print(f"[yellow]Reflex '{reflex.name}' expired and removed[/yellow]")
            self.logger.info(f"Reflex '{reflex.name}' expired and removed")
            
            # 파일 삭제 (trashcan으로 이동)
            if reflex.source_file and os.path.exists(reflex.source_file):
                try:
                    filename = os.path.basename(reflex.source_file)
                    # timestamp prefix to avoid collisions
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    dest_path = os.path.join(trash_dir, f"{timestamp}_{filename}")
                    
                    shutil.move(reflex.source_file, dest_path)
                    self.console.print(f"   [dim]Moved to {dest_path}[/dim]")
                    self.logger.info(f"Moved reflex file to {dest_path}")
                except Exception as e:
                    self.console.print(f"   [red]Failed to move file: {e}[/red]")
                    self.logger.error(f"Failed to move reflex file: {e}")
            
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
        """Reflex 개별 로그 기록 - .log 파일에만 저장 (YAML 저장 제거됨)"""
        dt = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Save to .log file
        log_file = os.path.join(self.log_dir, f"{reflex_id}.log")
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"[{dt}] [{level}] {message}\n")
        except Exception as e:
            print(f"Failed to write log file: {e}")
            
        # Broadcast to IPC (fire and forget task)
        log_data = {
            "type": "log",
            "reflex_id": reflex_id,
            "time": dt,
            "level": level,
            "message": message
        }
        # We need to run this async
        try:
            asyncio.create_task(self.ipc.broadcast(log_data))
        except:
            pass