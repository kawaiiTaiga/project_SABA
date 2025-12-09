# reflex/actions/tool.py
import json
from typing import Dict, Any, Callable
from .base import ActionBase

@ActionBase.register('tool')
class ToolAction(ActionBase):
    """
    Tool을 직접 실행하는 Action
    1개 이상의 tool을 순차적으로 실행
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
        Reflex에서 tool이 적어도 1개 이상인지 검증
        """
        if len(tools) == 0:
            raise ValueError("ToolAction requires at least 1 tool, but none provided")

    async def execute(
        self,
        event: Dict[str, Any],
        state: Dict[str, Any],
        tools: Dict[str, Callable],
        trigger: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Tool 실행 - 선택된 모든 tool을 순차적으로 실행"""
        
        # tool이 하나라도 있는지 확인
        if not tools:
            error_msg = "ToolAction requires at least 1 tool, but none provided"
            print(f"   ❌ {error_msg}")
            return {
                'success': False,
                'error': error_msg,
                'text': f"Error: {error_msg}"
            }
        
        print(f"\n🔧 ToolAction: Executing {len(tools)} tools")
        print(f"   Arguments: {self.arguments}")
        print(f"   Trigger context: {trigger}")
        
        results = []
        all_success = True
        
        # 모든 tool 순차 실행
        for tool_name, tool_func in tools.items():
            print(f"\n   👉 Executing '{tool_name}'...")
            
            try:
                # Arguments에서 event/state/trigger 변수 치환 (각 툴마다 동일 인자 적용)
                resolved_args = self._resolve_arguments(self.arguments, event, state, trigger)
                print(f"      Resolved args: {resolved_args}")
                
                # Tool 실행
                result = await tool_func(**resolved_args)
                
                # 결과를 문자열로 변환
                if isinstance(result, dict):
                    result_text = json.dumps(result, ensure_ascii=False, indent=2)
                else:
                    result_text = str(result)
                
                print(f"      ✅ Success")
                print(f"      📤 Result: {result_text}")
                
                results.append({
                    'tool_name': tool_name,
                    'result': result,
                    'text': result_text,
                    'success': True
                })
                
            except Exception as e:
                error_msg = str(e)
                print(f"      ❌ Failed: {error_msg}")
                all_success = False
                results.append({
                    'tool_name': tool_name,
                    'error': error_msg,
                    'text': f"Error: {error_msg}",
                    'success': False
                })
        
        # 최종 결과 조합
        final_text = "\n\n".join([f"[{r['tool_name']}] {r['text']}" for r in results])
        
        return {
            'success': all_success,
            'results': results, # 상세 결과 리스트
            'text': final_text  # 로그에 기록될 텍스트 (전체 합본)
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            'type': 'tool',
            'arguments': self.arguments
        }

    def __repr__(self):
        return f"ToolAction(arguments={self.arguments})"
