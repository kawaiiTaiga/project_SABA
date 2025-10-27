# reflex/core/engine.py
import asyncio
from typing import Dict, List, Any

from .reflex import Reflex
from .state import WorldState
from ..tools.registry import ToolRegistry
from reflex.triggers.base import TriggerBase
from reflex.actions.base import ActionBase


class ReflexEngine:
    """
    Reflex 실행 엔진

    역할:
    1. Schedule 체크 (1초마다)
    2. Reflex 매칭 & 실행
    3. Lifecycle 관리
    """

    def __init__(self, tool_registry: ToolRegistry, state: WorldState):
        self.tool_registry = tool_registry
        self.state = state
        self.reflexes: Dict[str, Reflex] = {}
        self.running = False

    # =========================
    # Validation helpers
    # =========================
    def _validate_reflex(self, reflex: Reflex) -> List[str]:
        """유효성 검사: 실패 시 메시지 리스트 반환"""
        errors: List[str] = []

        # Trigger 타입 확인
        if not isinstance(reflex.trigger, TriggerBase):
            errors.append(f"Trigger must subclass TriggerBase, got {type(reflex.trigger)}")

        # Action 타입 확인
        if not isinstance(reflex.action, ActionBase):
            errors.append(f"Action must subclass ActionBase, got {type(reflex.action)}")

        # Lifecycle 기본 정합성
        if reflex.lifecycle.type not in ("temporary", "persistent"):
            errors.append(f"Invalid lifecycle.type: {reflex.lifecycle.type}")
        if reflex.lifecycle.type == "temporary":
            if not reflex.lifecycle.ttl_sec or reflex.lifecycle.ttl_sec <= 0:
                errors.append("temporary lifecycle requires ttl_sec > 0")
            if reflex.lifecycle.max_runs is not None and reflex.lifecycle.max_runs <= 0:
                errors.append("max_runs must be > 0 if provided")

        # Tool 존재 여부
        missing = [t for t in reflex.tools if t not in self.tool_registry.tools]
        if missing:
            errors.append(f"Tools not found in registry: {missing}")

        return errors

    # =========================
    # Engine lifecycle
    # =========================
    async def start(self):
        """엔진 시작"""
        self.running = True
        
        # 1. MCP Bridge에 연결
        print("🔌 Connecting to MCP Bridge...")
        if not await self.tool_registry.connect():
            print("❌ Failed to connect to MCP Bridge. Exiting.")
            return
        
        # 2. 툴 로드
        print("📦 Loading tools from MCP Bridge...")
        try:
            await self.tool_registry.load_tools_from_mcp()
        except Exception as e:
            print(f"❌ Failed to load tools: {e}")
            await self.tool_registry.disconnect()
            return
        
        # 3. 툴 로드 완료 후 모든 Reflex 검증
        print("🔍 Validating reflexes...")
        invalid_reflexes = []
        for reflex_id, reflex in list(self.reflexes.items()):
            errors = self._validate_reflex(reflex)
            if errors:
                print(f"❌ Reflex '{reflex.name}' validation failed:")
                for err in errors:
                    print(f"   - {err}")
                invalid_reflexes.append(reflex_id)
        
        # 유효하지 않은 reflex 제거
        for reflex_id in invalid_reflexes:
            del self.reflexes[reflex_id]
        
        if invalid_reflexes:
            print(f"⚠️ Removed {len(invalid_reflexes)} invalid reflex(es)\n")
        
        print("🚀 Reflex Engine started")
        print(f"   Loaded {len(self.reflexes)} reflex(es)")
        print(f"   Available tools: {self.tool_registry.list_tools()}\n")

        try:
            await self._main_loop()
        except KeyboardInterrupt:
            print("\n⚠️ Interrupted by user")
        except Exception as e:
            print(f"\n❌ Engine error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await self.stop()

    async def stop(self):
        """엔진 종료"""
        self.running = False
        
        # MCP Bridge 연결 종료
        await self.tool_registry.disconnect()
        
        print("🛑 Reflex Engine stopped")

    async def _main_loop(self):
        """메인 실행 루프 (1초마다)"""
        print("⏰ Schedule loop started\n")

        while self.running:
            try:
                event = {
                    "type": "schedule_tick",
                    "timestamp": asyncio.get_event_loop().time(),
                }

                for reflex in list(self.reflexes.values()):
                    await self._check_and_execute(reflex, event)

                await self._cleanup_expired()
                await asyncio.sleep(1)

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"❌ Loop error: {e}")
                await asyncio.sleep(1)

    async def _check_and_execute(self, reflex: Reflex, event: Dict[str, Any]):
        """Reflex 체크 & 실행"""
        if not reflex.enabled:
            return

        if reflex.should_expire():
            return

        try:
            current_state = self.state.get_all()
            should_trigger = await reflex.trigger.check(event, current_state)
            if not should_trigger:
                return

            print(f"✨ Reflex '{reflex.name}' triggered!")
            print(f"   ID: {reflex.id}")
            print(f"   Trigger: {reflex.trigger}")

            available_tools = self.tool_registry.get_tools_for_reflex(reflex.tools)
            if not available_tools:
                print(f"   ⚠️ No tools available")
                return

            result = await reflex.action.execute(
                event=event, state=current_state, tools=available_tools
            )

            reflex.increment_runs()

            if reflex.lifecycle.max_runs:
                if reflex.metadata["runs"] >= reflex.lifecycle.max_runs:
                    reflex.enabled = False
                    print(f"   ⏹️ Reached max_runs ({reflex.lifecycle.max_runs}), disabled")

            print(f"   ✅ Executed successfully")
            print(f"   Runs: {reflex.metadata['runs']}")

            if result.get("success"):
                if result.get("tool_calls"):
                    print(f"   Tool calls: {len(result['tool_calls'])}")
            else:
                print(f"   ⚠️ Execution failed: {result.get('error')}")
            print()

        except Exception as e:
            print(f"   ❌ Error: {e}")
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
            print(f"🗑️ Reflex '{reflex.name}' expired and removed")
            del self.reflexes[rid]

    # ============================================
    # Reflex 관리 API
    # ============================================
    def add_reflex(self, reflex: Reflex, validate: bool = False):
        """
        Reflex 추가
        
        Args:
            reflex: 추가할 Reflex
            validate: 즉시 검증할지 여부 (기본: False, start() 시점에 검증)
        """
        if validate:
            errors = self._validate_reflex(reflex)
            if errors:
                print(f"❌ Failed to register reflex '{reflex.name}':")
                for err in errors:
                    print(f"   - {err}")
                print()
                return False

        self.reflexes[reflex.id] = reflex
        print(f"➕ Added reflex: {reflex.name}")
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
            print(f"➖ Removed reflex: {reflex.name}")

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
            print(f"✓ Reflex {reflex_id} enabled")

    def disable_reflex(self, reflex_id: str):
        """Reflex 비활성화"""
        if reflex_id in self.reflexes:
            self.reflexes[reflex_id].enabled = False
            print(f"⏸️ Reflex {reflex_id} disabled")