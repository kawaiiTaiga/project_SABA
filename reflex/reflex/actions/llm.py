# reflex/actions/llm.py
from typing import Dict, Any, Callable
import os
from anthropic import AsyncAnthropic
from .base import ActionBase

@ActionBase.register('llm')
class LLMAction(ActionBase):
    """
    LLM 기반 Action (Tool Calling)
    
    Config:
        type: "llm" (필수)
        api: "claude" (현재 claude만 지원)
        model: "claude-sonnet-4-20250514"
        prompt: 시스템 프롬프트
        temperature: 0.0~1.0 (기본: 0.7)
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        
        self.api = config.get('api', 'claude')
        self.model = config.get('model', 'claude-sonnet-4-20250514')
        self.prompt = config.get('prompt', '')
        self.temperature = config.get('temperature', 0.7)
        
        # API 클라이언트 초기화
        if self.api == 'claude':
            api_key = os.environ.get('ANTHROPIC_API_KEY')
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY environment variable not set")
            self.client = AsyncAnthropic(api_key=api_key)
        else:
            raise ValueError(f"Unsupported API: {self.api}")
    
    async def execute(
        self, 
        event: Dict[str, Any], 
        state: Dict[str, Any],
        tools: Dict[str, Callable]
    ) -> Dict[str, Any]:
        """LLM에게 판단 맡기고 Tool Calling으로 실행"""
        try:
            # 1. Tool 스펙 준비
            tool_specs = self._prepare_tool_specs(tools)
            
            # 2. 사용자 메시지 구성
            user_message = self._build_user_message(event, state)
            
            print(f"\n🤖 Calling LLM...")
            print(f"   Model: {self.model}")
            print(f"   Tools: {list(tools.keys())}")
            
            # 3. LLM 호출
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                temperature=self.temperature,
                system=self.prompt,
                messages=[{
                    "role": "user",
                    "content": user_message
                }],
                tools=tool_specs if tool_specs else None
            )
            
            # 4. Tool Calling 처리
            tool_results = []
            text_response = ""
            
            for block in response.content:
                if block.type == 'tool_use':
                    tool_name = block.name
                    tool_args = block.input
                    
                    print(f"   🔧 LLM calls: {tool_name}({tool_args})")
                    
                    if tool_name in tools:
                        try:
                            result = await tools[tool_name](**tool_args)
                            tool_results.append({
                                'tool': tool_name,
                                'args': tool_args,
                                'result': result
                            })
                            print(f"      ✓ Result: {result}")
                        except Exception as e:
                            print(f"      ✗ Error: {e}")
                            tool_results.append({
                                'tool': tool_name,
                                'args': tool_args,
                                'error': str(e)
                            })
                    else:
                        print(f"      ⚠️ Tool not available")
                
                elif block.type == 'text':
                    text_response = block.text
                    print(f"   💬 LLM: {text_response}")
            
            return {
                'success': True,
                'tool_calls': tool_results,
                'text': text_response,
                'raw_response': response
            }
            
        except Exception as e:
            print(f"   ❌ LLM execution error: {e}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'error': str(e)
            }
    
    def _prepare_tool_specs(self, tools: Dict[str, Callable]) -> list:
        """Tool을 Anthropic API 형식으로 변환"""
        specs = []
        
        for tool_name, tool_func in tools.items():
            # 기본 스펙
            doc = getattr(tool_func, '__doc__', f"Execute {tool_name}")
            
            spec = {
                "name": tool_name,
                "description": doc.strip() if doc else f"Execute {tool_name}",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
            
            specs.append(spec)
        
        return specs
    
    def _build_user_message(self, event: Dict[str, Any], state: Dict[str, Any]) -> str:
        """컨텍스트를 포함한 사용자 메시지 구성"""
        lines = ["Current situation:\n"]
        
        # 이벤트 정보
        lines.append(f"Event: {event}\n")
        
        # 상태 정보
        if state:
            lines.append("\nCurrent state:")
            for key, value in state.items():
                lines.append(f"  - {key}: {value}")
        
        lines.append("\n\nPlease decide what actions to take.")
        
        return '\n'.join(lines)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'type': 'llm',
            'api': self.api,
            'model': self.model,
            'prompt': self.prompt,
            'temperature': self.temperature
        }
    
    def __repr__(self):
        return f"LLMAction(api='{self.api}', model='{self.model}')"