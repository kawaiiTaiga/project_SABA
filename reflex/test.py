# test.py - 완전한 테스트
import asyncio
import os
from reflex.core.engine import ReflexEngine
from reflex.core.state import WorldState
from reflex.core.reflex import Reflex
from reflex.core.lifecycle import Lifecycle
from reflex.triggers.schedule import ScheduleTrigger
from reflex.actions.llm import LLMAction
from reflex.tools.registry import ToolManager

async def main():
    print("=" * 60)
    print("🌟 SABA Reflex with ToolManager")
    print("=" * 60)
    print()
    
    # API 키 체크
    if not os.environ.get('ANTHROPIC_API_KEY'):
        print("❌ ANTHROPIC_API_KEY not set!")
        print("   Set it with: export ANTHROPIC_API_KEY='your-key'")
        return
    
    # ToolManager 초기화
    print("🔧 Initializing ToolManager...\n")
    tool_manager = ToolManager()
    
    # MCP 서버들 추가
    tool_manager.add_sse_registry(
        name="saba_bridge",
        url="http://localhost:8083/sse"
    )
    
    tool_manager.add_stdio_registry(
        name="calculator",
        command="python",
        args=["very_simple_mcp.py"]
    )

    # 사용 가능한 툴 확인
    print("=" * 60)
    tool_manager.list_all_tools()
    print("=" * 60)
    
    # WorldState와 Engine 초기화
    state = WorldState()
    engine = ReflexEngine(tool_manager, state)
    
    print("\n📝 Creating reflexes...\n")
    
    # ============================================
    # Reflex 1: Calculator 테스트
    # ============================================
    calculator_reflex = Reflex(
        id="calculator_test",
        name="Calculator Test",
        trigger=ScheduleTrigger({'type': 'schedule', 'cron': '* * * * *'}),  # 매분
        action=LLMAction({
            'type': 'llm',
            'model': 'claude-haiku-4-5-20251001',
            'messages': [
                {
                    'role': 'user',
                    'content': '10과 20을 더해줘. 그리고 5와 7을 곱해줘.'
                }
            ]
        }),
        tools=['calculator.add', 'calculator.multiply'],  # Calculator 툴 사용
        lifecycle=Lifecycle(type='temporary', ttl_sec=300, max_runs=1)
    )
    engine.add_reflex(calculator_reflex)
    print("   ✓ Added: Calculator Test Reflex")
    
    # ============================================
    # Reflex 2: SABA Bridge 테스트
    # ============================================
    saba_reflex = Reflex(
        id="saba_test",
        name="SABA Test",
        trigger=ScheduleTrigger({'type': 'schedule', 'cron': '*/2 * * * *'}),  # 2분마다
        action=LLMAction({
            'type': 'llm',
            'model': 'claude-haiku-4-5-20251001',
            'messages': [
                {
                    'role': 'user',
                    'content': '사용 가능한 디바이스 목록을 조회해줘.'
                }
            ]
        }),
        tools=['saba_bridge.list_devices'],  # SABA Bridge 툴 사용
        lifecycle=Lifecycle(type='temporary', ttl_sec=300, max_runs=1)
    )
    engine.add_reflex(saba_reflex)
    print("   ✓ Added: SABA Test Reflex")
    
    # ============================================
    # Reflex 3: 복합 테스트 (여러 서버의 툴 사용)
    # ============================================
    multi_reflex = Reflex(
        id="multi_test",
        name="Multi Server Test",
        trigger=ScheduleTrigger({'type': 'schedule', 'cron': '*/3 * * * *'}),  # 3분마다
        action=LLMAction({
            'type': 'llm',
            'model': 'claude-sonnet-4-20250514',
            'messages': [
                {
                    'role': 'user',
                    'content': (
                        '다음 작업들을 수행해줘:\n'
                        '1. 100과 50을 더하기\n'
                        '2. "Reflex"에게 인사하기\n'
                        '3. SABA 디바이스 목록 확인하기'
                    )
                }
            ]
        }),
        tools=[
            'calculator.add',
            'calculator.greet',
            'saba_bridge.list_devices'
        ],
        lifecycle=Lifecycle(type='temporary', ttl_sec=300, max_runs=1)
    )
    engine.add_reflex(multi_reflex)
    print("   ✓ Added: Multi Server Test Reflex")
    
    # ============================================
    # Reflex 4: 툴 이름만으로 사용 (registry 지정 안함)
    # ============================================
    simple_reflex = Reflex(
        id="simple_test",
        name="Simple Test",
        trigger=ScheduleTrigger({'type': 'schedule', 'cron': '*/5 * * * *'}),  # 5분마다
        action=LLMAction({
            'type': 'llm',
            'model': 'claude-haiku-4-5-20251001',
            'messages': [
                {
                    'role': 'user',
                    'content': '3과 7을 더해줘.'
                }
            ]
        }),
        tools=['add'],  # registry 없이 툴 이름만 (자동으로 찾음)
        lifecycle=Lifecycle(type='temporary', ttl_sec=300, max_runs=1)
    )
    engine.add_reflex(simple_reflex)
    print("   ✓ Added: Simple Test Reflex")
    
    print("\n" + "=" * 60)
    print("🚀 Starting Reflex Engine...")
    print("=" * 60)
    
    try:
        # 엔진 시작 (여기서 tool_manager.connect() 자동 호출)
        await engine.start()
        
    except KeyboardInterrupt:
        print("\n\n⚠️ Shutting down...")
        
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        # 정리
        print("\n🧹 Cleaning up...")
        try:
            await engine.stop()
        except:
            pass
        
        try:
            await tool_manager.disconnect_all()
        except:
            pass
        
        print("✅ Goodbye!")

if __name__ == "__main__":
    asyncio.run(main())