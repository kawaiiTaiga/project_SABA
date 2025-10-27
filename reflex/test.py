# main.py - 채팅 템플릿 방식
import asyncio
import os
from reflex.core.engine import ReflexEngine
from reflex.core.state import WorldState
from reflex.core.reflex import Reflex
from reflex.core.lifecycle import Lifecycle
from reflex.triggers.schedule import ScheduleTrigger
from reflex.actions.llm import LLMAction
from reflex.tools.registry import ToolRegistry

async def main():
    print("=" * 60)
    print("🌟 SABA Reflex MVP")
    print("=" * 60)
    print()
    
    if not os.environ.get('ANTHROPIC_API_KEY'):
        print("❌ ANTHROPIC_API_KEY not set!")
        return
    
    # 초기화
    tool_registry = ToolRegistry(mcp_bridge_url="http://localhost:8083/sse")
    state = WorldState()
    engine = ReflexEngine(tool_registry, state)
    
    print("📝 Creating reflexes...\n")
    
    # ============================================
    # 예시 1: 간단한 명령 (system 없이)
    # ============================================
    simple_reflex = Reflex(
        id="simple_test",
        name="Simple Test",
        trigger=ScheduleTrigger({'type': 'schedule', 'cron': '* * * * *'}),
        action=LLMAction({
            'type': 'llm',
            'model': 'claude-haiku-4-5-20251001',
            'messages': [
        {'role': 'user', 'content': '작업 수행해줘.'}
    ]
        }),
        tools=['Motor'],
        lifecycle=Lifecycle(type='temporary', ttl_sec=300, max_runs=3)
    )
    engine.add_reflex(simple_reflex)
    

    print("=" * 60)
    try:
        await engine.start()
    except KeyboardInterrupt:
        print("\n⚠️ Shutting down...")

if __name__ == "__main__":
    asyncio.run(main())