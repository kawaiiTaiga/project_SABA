# reflex/actions/tool.py
import json
import re
from typing import Dict, Any, Callable
from .base import ActionBase

@ActionBase.register('tool')
class ToolAction(ActionBase):
    """
    Tool을 직접 실행하는 Action
    Reflex에서 정확히 1개의 tool만 사용 가능
    """
    
    description = "Execute exactly one tool with JSON arguments"
    schema = {
        "arguments": {
            "type": "json",
            "description": "JSON string of arguments to pass to the tool",
            "default": "{}"
        }
    }

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        
        # arguments 파싱 (JSON string 또는 dict)
        args = config.get('arguments', {})
        if isinstance(args, str):
            try:
                self.arguments = json.loads(args)
            except json.JSONDecodeError:
                self.arguments = {}
        else:
            self.arguments = args

    @staticmethod
    def validate_tools(tools: list) -> None:
        """
        Reflex에서 tool이 정확히 1개인지 검증
        이 메서드는 Reflex 로드 시점에 호출됨
        """
        if len(tools) == 0:
            raise ValueError("ToolAction requires exactly 1 tool, but none provided")
        if len(tools) > 1:
            raise ValueError(f"ToolAction requires exactly 1 tool, but {len(tools)} provided: {tools}")

    async def execute(
        self,
        event: Dict[str, Any],
        state: Dict[str, Any],
        tools: Dict[str, Callable],
        trigger: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Tool 실행 - tools dict에서 유일한 tool 실행"""
        
        # tools가 정확히 1개인지 확인
        if len(tools) != 1:
            error_msg = f"ToolAction requires exactly 1 tool, got {len(tools)}: {list(tools.keys())}"
            print(f"   ❌ {error_msg}")
            return {
                'success': False,
                'error': error_msg,
                'text': f"Error: {error_msg}"
            }
        
        # 유일한 tool 가져오기
        tool_name = list(tools.keys())[0]
        tool_func = tools[tool_name]
        
        print(f"\n🔧 ToolAction: Executing '{tool_name}'")
        print(f"   Arguments: {self.arguments}")
        print(f"   Trigger context: {trigger}")
        
        try:
            # Arguments에서 event/state/trigger 변수 치환
            resolved_args = self._resolve_arguments(self.arguments, event, state, trigger)
            print(f"   Resolved args: {resolved_args}")
            
            # Tool 실행
            result = await tool_func(**resolved_args)
            
            # 결과를 문자열로 변환
            if isinstance(result, dict):
                result_text = json.dumps(result, ensure_ascii=False, indent=2)
            else:
                result_text = str(result)
            
            print(f"   ✅ Tool executed successfully")
            print(f"   📤 Result: {result_text}")
            
            return {
                'success': True,
                'tool_name': tool_name,
                'result': result,
                'text': result_text  # 로그에 기록될 텍스트
            }
        except Exception as e:
            error_msg = str(e)
            print(f"   ❌ Tool execution failed: {error_msg}")
            return {
                'success': False,
                'tool_name': tool_name,
                'error': error_msg,
                'text': f"Error: {error_msg}"
            }
    
    def _resolve_arguments(
        self, 
        args: Dict[str, Any], 
        event: Dict[str, Any], 
        state: Dict[str, Any],
        trigger: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Arguments에서 템플릿 변수 치환
        예: "{{event.data.content}}" -> event['data']['content'] 값
        """
        resolved = {}
        for key, value in args.items():
            if isinstance(value, str):
                resolved[key] = self._resolve_template(value, event, state, trigger)
            elif isinstance(value, dict):
                resolved[key] = self._resolve_arguments(value, event, state, trigger)
            else:
                resolved[key] = value
        return resolved
    
    def _resolve_template(
        self, 
        template: str, 
        event: Dict[str, Any], 
        state: Dict[str, Any],
        trigger: Dict[str, Any]
    ) -> Any:
        """
        템플릿 문자열 치환 - Python 표현식 지원
        예: "{{trigger.cron}}", "{{trigger.content[1:3]}}", "{{', '.join(event.keys())}}"
        """
        pattern = r'\{\{(.+?)\}\}'
        
        # 전체 문자열이 {{expr}} 형태인 경우 결과 타입 유지
        full_match = re.fullmatch(pattern, template.strip())
        
        def evaluate_expr(expr: str) -> Any:
            ctx = {
                'event': event,
                'state': state,
                'trigger': type('TriggerContext', (), trigger)() if trigger else None
            }
            # dict를 attribute access 가능하게 변환
            ctx['trigger'] = _DictWrapper(trigger) if trigger else {}
            ctx['event'] = _DictWrapper(event) if event else {}
            ctx['state'] = _DictWrapper(state) if state else {}
            
            try:
                return eval(expr, {"__builtins__": {}}, ctx)
            except Exception as e:
                print(f"   ⚠️ Template eval failed for '{expr}': {e}")
                return f"{{{{expr}}}}"  # 실패시 원본 유지
        
        if full_match:
            # 전체가 표현식인 경우 타입 유지
            return evaluate_expr(full_match.group(1).strip())
        
        def replacer(match):
            expr = match.group(1).strip()
            return str(evaluate_expr(expr))
        
        return re.sub(pattern, replacer, template)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'type': 'tool',
            'arguments': self.arguments
        }

    def __repr__(self):
        return f"ToolAction(arguments={self.arguments})"


class _DictWrapper:
    """Dict를 attribute access 가능하게 래핑"""
    def __init__(self, data: Dict[str, Any]):
        self._data = data
    
    def __getattr__(self, key):
        if key.startswith('_'):
            return super().__getattribute__(key)
        try:
            val = self._data[key]
            if isinstance(val, dict):
                return _DictWrapper(val)
            return val
        except KeyError:
            raise AttributeError(f"No attribute '{key}'")
    
    def __getitem__(self, key):
        val = self._data[key]
        if isinstance(val, dict):
            return _DictWrapper(val)
        return val
    
    def __repr__(self):
        return repr(self._data)
    
    def keys(self):
        return self._data.keys()
    
    def values(self):
        return self._data.values()
    
    def items(self):
        return self._data.items()
