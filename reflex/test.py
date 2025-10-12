# main.py
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
    
    # 환경변수 체크
    if not os.environ.get('ANTHROPIC_API_KEY'):
        print("❌ ANTHROPIC_API_KEY not set!")
        print("   export ANTHROPIC_API_KEY=your_key")
        return
    
    # 1. 초기화
    print("🔧 Initializing...")
    tool_registry = ToolRegistry(mcp_bridge_url="http://localhost:8083")
    state = WorldState()
    
    # 2. MCP에서 툴 로드
    try:
        await tool_registry.load_tools_from_mcp()
    except Exception as e:
        print(f"Failed to load tools: {e}")
        return
    
    # 3. 엔진 생성
    engine = ReflexEngine(tool_registry, state)
    
    # 4. 예시 Reflex 생성
    print("📝 Creating reflexes...\n")
    
    # Reflex 1: 매일 9시 식물 체크
    plant_reflex = Reflex(
        id="daily_plant_check",
        name="Daily Plant Care",
        trigger=ScheduleTrigger({
            'type': 'schedule',
            'cron': '0 9 * * *'  # 매일 9시
            # 테스트용: 'cron': '* * * * *'  # 매분
        }),
        action=LLMAction({
            'type': 'llm',
            'api': 'claude',
            'model': 'claude-sonnet-4-20250514',
            'prompt': '''You are a plant care expert.

Check the plant's health and decide if watering is needed.

Consider:
- Soil moisture level
- Weather forecast
- Last watered time
- Plant appearance

Be thoughtful and conservative with watering.
Use the available tools to gather information and take actions.
''',
            'temperature': 0.7
        }),
        tools=[
            # TODO: 실제 디바이스 ID로 교체
            'check_plant_health_esp32-plant-01',
            'get_weather_weather-api',
            'water_plant_esp32-plant-01'
        ],
        lifecycle=Lifecycle(type='persistent')
    )
    
    engine.add_reflex(plant_reflex)
    
    # Reflex 2: 테스트용 (매분 실행)
    test_reflex = Reflex(
        id="test_every_minute",
        name="Test Reflex (Every Minute)",
        trigger=ScheduleTrigger({
            'type': 'schedule',
            'cron': '* * * * *'  # 매분
        }),
        action=LLMAction({
            'type': 'llm',
            'api': 'claude',
            'model': 'claude-sonnet-4-20250514',
            'prompt': '''You are a helpful assistant.

This is a test reflex that runs every minute.
Check what tools are available and use one of them to test.
''',
            'temperature': 0.7
        }),
        tools=tool_registry.list_tools()[:3],  # 처음 3개 툴만
        lifecycle=Lifecycle(
            type='temporary',
            ttl_sec=600,  # 10분 후 만료
            max_runs=5    # 최대 5번 실행
        )
    )
    
    engine.add_reflex(test_reflex)
    
    # 5. 엔진 시작
    print("=" * 60)
    try:
        await engine.start()
    except KeyboardInterrupt:
        print("\n⚠️ Shutting down...")
        await engine.stop()

if __name__ == "__main__":
    asyncio.run(main())