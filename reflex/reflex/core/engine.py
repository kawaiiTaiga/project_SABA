# reflex/core/engine.py
import asyncio
from typing import Dict, List, Any
from .reflex import Reflex
from .state import WorldState
from ..tools.registry import ToolRegistry

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
    
    async def start(self):
        """엔진 시작"""
        self.running = True
        print("🚀 Reflex Engine started")
        print(f"   Loaded {len(self.reflexes)} reflex(es)\n")
        
        # 메인 루프 시작
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
        print("🛑 Reflex Engine stopped")
    
    async def _main_loop(self):
        """메인 실행 루프 (1초마다)"""
        print("⏰ Schedule loop started\n")
        
        while self.running:
            try:
                # 현재 시간으로 이벤트 생성
                event = {
                    'type': 'schedule_tick',
                    'timestamp': asyncio.get_event_loop().time()
                }
                
                # 모든 Reflex 체크
                for reflex in list(self.reflexes.values()):
                    await self._check_and_execute(reflex, event)
                
                # Lifecycle 관리 (만료된 Reflex 정리)
                await self._cleanup_expired()
                
                # 1초 대기
                await asyncio.sleep(1)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"❌ Loop error: {e}")
                await asyncio.sleep(1)
    
    async def _check_and_execute(self, reflex: Reflex, event: Dict[str, Any]):
        """Reflex 체크 & 실행"""
        
        # 비활성화되어 있으면 스킵
        if not reflex.enabled:
            return
        
        # 만료되었으면 스킵
        if reflex.should_expire():
            return
        
        try:
            # 1. Trigger 체크
            current_state = self.state.get_all()
            should_trigger = await reflex.trigger.check(event, current_state)
            
            if not should_trigger:
                return
            
            print(f"✨ Reflex '{reflex.name}' triggered!")
            print(f"   ID: {reflex.id}")
            print(f"   Trigger: {reflex.trigger}")
            
            # 2. 도구 준비
            available_tools = self.tool_registry.get_tools_for_reflex(reflex.tools)
            
            if not available_tools:
                print(f"   ⚠️ No tools available")
                return
            
            # 3. Action 실행
            result = await reflex.action.execute(
                event=event,
                state=current_state,
                tools=available_tools
            )
            
            # 4. 실행 카운트 증가
            reflex.increment_runs()
            
            # 5. max_runs 체크
            if reflex.lifecycle.max_runs:
                if reflex.metadata['runs'] >= reflex.lifecycle.max_runs:
                    reflex.enabled = False
                    print(f"   ⏹️ Reached max_runs ({reflex.lifecycle.max_runs}), disabled")
            
            print(f"   ✅ Executed successfully")
            print(f"   Runs: {reflex.metadata['runs']}")
            
            if result.get('success'):
                if result.get('tool_calls'):
                    print(f"   Tool calls: {len(result['tool_calls'])}")
            else:
                print(f"   ⚠️ Execution failed: {result.get('error')}")
            
            print()  # 빈 줄
            
        except Exception as e:
            print(f"   ❌ Error: {e}")
            import traceback
            traceback.print_exc()
            print()
    
    async def _cleanup_expired(self):
        """만료된 Reflex 정리"""
        expired_ids = []
        
        for reflex_id, reflex in self.reflexes.items():
            if reflex.should_expire():
                expired_ids.append(reflex_id)
        
        for reflex_id in expired_ids:
            reflex = self.reflexes[reflex_id]
            print(f"🗑️ Reflex '{reflex.name}' expired and removed")
            del self.reflexes[reflex_id]
    
    # ============================================
    # Reflex 관리 API
    # ============================================
    
    def add_reflex(self, reflex: Reflex):
        """Reflex 추가"""
        self.reflexes[reflex.id] = reflex
        print(f"➕ Added reflex: {reflex.name}")
        print(f"   ID: {reflex.id}")
        print(f"   Trigger: {reflex.trigger}")
        print(f"   Action: {reflex.action}")
        print(f"   Tools: {reflex.tools}")
        print(f"   Lifecycle: {reflex.lifecycle.type}")
        print()
    
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
                'id': r.id,
                'name': r.name,
                'enabled': r.enabled,
                'runs': r.metadata.get('runs', 0),
                'type': r.trigger.type
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