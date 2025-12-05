# reflex/triggers/base.py
from abc import ABC, abstractmethod
from typing import Dict, Any, Tuple
import importlib
import inspect
from pathlib import Path

class TriggerBase(ABC):
    """Trigger 추상 클래스"""
    
    # 클래스 변수: 등록된 Trigger 타입들
    _registry: Dict[str, type] = {}
    
    # 메타데이터
    description: str = "Base Trigger"
    schema: Dict[str, Any] = {}
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.type = config.get('type')
        
        if not self.type:
            raise ValueError("Trigger config must have 'type' field")
    
    @abstractmethod
    async def check(self, event: Dict[str, Any], state: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        Check if trigger should fire.
        
        Returns:
            Tuple[bool, Dict[str, Any]]: (fired, context_dict)
            - fired: Whether the trigger fired
            - context_dict: Trigger context (type, cron, fired_at, etc.)
              All values should be strings for template compatibility.
        """
        pass
    
    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        pass
    
    @classmethod
    def register(cls, trigger_type: str):
        """
        Decorator로 Trigger 자동 등록
        
        Usage:
            @TriggerBase.register('schedule')
            class ScheduleTrigger(TriggerBase):
                ...
        """
        def decorator(trigger_class):
            cls._registry[trigger_type] = trigger_class
            return trigger_class
        return decorator
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TriggerBase':
        """
        역직렬화 - 자동으로 적절한 클래스 찾기
        """
        trigger_type = data.get('type')
        
        if not trigger_type:
            raise ValueError("Trigger data must have 'type' field")
        
        # Registry에서 찾기
        if trigger_type in cls._registry:
            trigger_class = cls._registry[trigger_type]
            return trigger_class(data)
        
        # Registry에 없으면 동적 로드 시도
        try:
            module = importlib.import_module(f'.{trigger_type}', package='reflex.triggers')
            
            # 모듈에서 TriggerBase 상속한 클래스 찾기
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, cls) and obj is not cls:
                    # 자동 등록
                    cls._registry[trigger_type] = obj
                    return obj(data)
        except ImportError:
            pass
        
        raise ValueError(f"Unknown trigger type: {trigger_type}")
    
    def __repr__(self):
        return f"{self.__class__.__name__}(type='{self.type}')"