# reflex/actions/base.py
from abc import ABC, abstractmethod
from typing import Dict, Any, Callable, Tuple, Optional
import importlib
import inspect
from datetime import datetime

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