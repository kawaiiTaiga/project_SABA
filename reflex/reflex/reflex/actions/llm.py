# reflex/actions/llm.py
from typing import Dict, Any, Callable
import os
from anthropic import AsyncAnthropic
from .base import ActionBase


@ActionBase.register('llm')
class LLMAction(ActionBase):
    """LLM 기반 Action (Tool Calling)"""
    
    description = "Use LLM to analyze situation and call tools"
    schema = {
        "system_prompt": {
            "type": "text",
            "description": "System prompt for the LLM",
            "default": "You are a helpful assistant."
        },
        "user_prompt": {
            "type": "text",
            "description": "User prompt/instruction",
            "default": "Execute the task."
        }
    }
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        
        self.api = config.get('api', 'claude')
        self.model = config.get('model', 'claude-sonnet-4-20250514')
        self.messages = config.get('messages', [])
        self.temperature = config.get('temperature', 0.7)
        
        print(f"[DEBUG] LLMAction initialized:")
        print(f"  - config keys: {list(config.keys())}")
        print(f"  - messages: {self.messages}")
        
        # API 클라이언트 초기화
        if self.api == 'claude':
            api_key = os.environ.get('ANTHROPIC_API_KEY')
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY environment variable not set")
            self.client = AsyncAnthropic(api_key=api_key)
        else:
            raise ValueError(f"Unsupported API: {self.api}")
        
        # 툴 이름 매핑 초기화
        self._tool_name_mapping = {}  # {순수이름: 전체이름}
    
    async def execute(
        self, 
        event: Dict[str, Any], 
        state: Dict[str, Any],
        tools: Dict[str, Callable],
        trigger: Dict[str, Any]
    ) -> Dict[str, Any]:
        """LLM에게 판단 맡기고 Tool Calling으로 실행"""
        try:
            # 1. Tool 스펙 준비
            tool_specs = self._prepare_tool_specs(tools)
            
            # 2. 메시지 처리 (템플릿 치환 적용)
            system_content = None
            user_messages = []
            
            for msg in self.messages:
                role = msg.get('role', 'user')
                content = msg.get('content', '')
                
                # 템플릿 치환 적용
                resolved_content = self._resolve_template(content, event, state, trigger)
                
                if role == 'system':
                    system_content = resolved_content
                elif role == 'user':
                    user_messages.append({
                        'role': 'user',
                        'content': resolved_content
                    })
                elif role == 'assistant':
                    user_messages.append({
                        'role': 'assistant',
                        'content': resolved_content
                    })
            
            # user 메시지가 없으면 기본 메시지
            if not user_messages:
                user_messages = [{
                    'role': 'user',
                    'content': 'Please use the available tools as needed.'
                }]
            
            print(f"\n🤖 Calling LLM...")
            print(f"   Model: {self.model}")
            print(f"   Trigger context: {trigger}")
            print(f"   Tools available: {len(tools)}")
            for pure_name, full_name in self._tool_name_mapping.items():
                print(f"      • {pure_name} (internal: {full_name})")
            
            # system 파라미터 준비
            if system_content:
                system_param = [{"type": "text", "text": system_content}]
                print(f"   [DEBUG] System param: {system_param}")
            else:
                print(f"   [DEBUG] No system prompt - will omit parameter")
            
            print(f"   [DEBUG] User messages: {user_messages}")
            print(f"   [DEBUG] About to call API...")
            
            # 3. LLM 호출
            call_params = {
                "model": self.model,
                "max_tokens": 4096,
                "temperature": self.temperature,
                "messages": user_messages,
            }
            
            # system이 있을 때만 추가
            if system_content:
                call_params["system"] = system_param
            
            # tools가 있을 때만 추가
            if tool_specs:
                call_params["tools"] = tool_specs
            
            print(f"   [DEBUG] Call params keys: {list(call_params.keys())}")
            
            response = await self.client.messages.create(**call_params)
            
            print(f"   [DEBUG] API call succeeded!")
            
            # 4. Tool Calling 처리
            tool_results = []
            text_response = ""
            
            for block in response.content:
                if block.type == 'tool_use':
                    pure_tool_name = block.name  # LLM이 호출한 이름 (예: 'add')
                    tool_args = block.input
                    
                    # 순수 이름 -> 전체 이름으로 변환
                    full_tool_name = self._tool_name_mapping.get(pure_tool_name, pure_tool_name)
                    
                    print(f"   🔧 LLM calls: {pure_tool_name} -> {full_tool_name}({tool_args})")
                    
                    # 전체 이름으로 툴 찾기
                    if full_tool_name in tools:
                        try:
                            result = await tools[full_tool_name](**tool_args)
                            tool_results.append({
                                'tool': full_tool_name,
                                'args': tool_args,
                                'result': result
                            })
                            print(f"      ✓ Result: {result}")
                        except Exception as e:
                            print(f"      ✗ Error: {e}")
                            tool_results.append({
                                'tool': full_tool_name,
                                'args': tool_args,
                                'error': str(e)
                            })
                    else:
                        print(f"      ⚠️ Tool not available: {full_tool_name}")
                
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
            print(f"   [DEBUG] Error type: {type(e)}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'error': str(e)
            }
    
    def _prepare_tool_specs(self, tools: Dict[str, Callable]) -> list:
        """
        Tool을 Anthropic API 형식으로 변환
        
        'calculator.add' -> 'add'로 변환하여 LLM에 전달
        """
        specs = []
        self._tool_name_mapping.clear()  # 매핑 초기화
        
        for full_tool_name, tool_func in tools.items():
            # 순수 툴 이름 추출 (마지막 점 이후)
            pure_tool_name = full_tool_name.split('.')[-1] if '.' in full_tool_name else full_tool_name
            
            # 매핑 저장
            self._tool_name_mapping[pure_tool_name] = full_tool_name
            
            # 함수에 붙어있는 MCP 스키마 가져오기
            mcp_schema = getattr(tool_func, '_mcp_schema', None)
            
            if mcp_schema:
                # MCP 스키마가 있으면 그대로 사용 (단, 이름은 순수 이름)
                description = mcp_schema.get('description', f"Execute {pure_tool_name}")
                parameters = mcp_schema.get('parameters', {})
                
                spec = {
                    "name": pure_tool_name,
                    "description": description,
                    "input_schema": parameters
                }
            else:
                # 스키마가 없으면 기본 스펙
                doc = getattr(tool_func, '__doc__', f"Execute {pure_tool_name}")
                
                spec = {
                    "name": pure_tool_name,
                    "description": doc.strip() if doc else f"Execute {pure_tool_name}",
                    "input_schema": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            
            specs.append(spec)
        
        return specs
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'type': 'llm',
            'api': self.api,
            'model': self.model,
            'messages': self.messages,
            'temperature': self.temperature
        }
    
    def __repr__(self):
        return f"LLMAction(api='{self.api}', model='{self.model}', {len(self.messages)} messages)"