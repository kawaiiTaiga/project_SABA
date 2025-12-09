# reflex/actions/base.py
from abc import ABC, abstractmethod
from typing import Dict, Any, Callable, Tuple, Optional
import importlib
import inspect
import re
from datetime import datetime


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


class TriggerContext(dict):
    """Trigger context as dict with attribute access"""
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(f"'{type(self).__name__}' has no attribute '{key}'")

class ActionBase(ABC):
    """Action 추상 클래스"""
    
    # 클래스 변수: 등록된 Action 타입들
    _registry: Dict[str, type] = {}
    
    # 메타데이터
    description: str = "Base Action"
    schema: Dict[str, Any] = {}
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.type = config.get('type')
        
        if not self.type:
            raise ValueError("Action config must have 'type' field")
    
    @abstractmethod
    async def execute(
        self, 
        event: Dict[str, Any], 
        state: Dict[str, Any],
        tools: Dict[str, Callable],
        trigger: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute the action.
        
        Args:
            event: Current event data
            state: Current world state
            tools: Available tools
            trigger: Trigger context dict (type, cron, fired_at, etc.)
        """
        pass
    
    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        pass
    
    @classmethod
    def register(cls, action_type: str):
        """
        Decorator로 Action 자동 등록
        
        Usage:
            @ActionBase.register('llm')
            class LLMAction(ActionBase):
                ...
        """
        def decorator(action_class):
            cls._registry[action_type] = action_class
            return action_class
        return decorator
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ActionBase':
        """
        역직렬화 - 자동으로 적절한 클래스 찾기
        """
        action_type = data.get('type')
        
        if not action_type:
            raise ValueError("Action data must have 'type' field")
        
        # Registry에서 찾기
        if action_type in cls._registry:
            action_class = cls._registry[action_type]
            return action_class(data)
        
        # Registry에 없으면 동적 로드 시도
        try:
            module = importlib.import_module(f'.{action_type}', package='reflex.actions')
            
            # 모듈에서 ActionBase 상속한 클래스 찾기
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, cls) and obj is not cls:
                    # 자동 등록
                    cls._registry[action_type] = obj
                    return obj(data)
        except ImportError:
            pass
        
        raise ValueError(f"Unknown action type: {action_type}")
    
    def __repr__(self):
        return f"{self.__class__.__name__}(type='{self.type}')"
    
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
        if not template:
            return template
            
        pattern = r'\{\{(.+?)\}\}'
        
        # 전체 문자열이 {{expr}} 형태인 경우 결과 타입 유지
        full_match = re.fullmatch(pattern, str(template).strip())
        
        def evaluate_expr(expr: str) -> Any:
            ctx = {
                'trigger': _DictWrapper(trigger) if trigger else {},
                'event': _DictWrapper(event) if event else {},
                'state': _DictWrapper(state) if state else {}
            }
            
            try:
                return eval(expr, {"__builtins__": {}}, ctx)
            except Exception as e:
                print(f"   ⚠️ Template eval failed for '{expr}': {e}")
                return f"{{{{{expr}}}}}"  # 실패시 원본 유지
        
        if full_match:
            # 전체가 표현식인 경우 타입 유지
            return evaluate_expr(full_match.group(1).strip())
        
        def replacer(match):
            expr = match.group(1).strip()
            return str(evaluate_expr(expr))
        
        return re.sub(pattern, replacer, str(template))
    
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