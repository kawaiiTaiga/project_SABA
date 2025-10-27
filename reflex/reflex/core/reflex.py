# reflex/core/reflex.py
from dataclasses import dataclass, field
from typing import Dict, Any, List
from datetime import datetime
from .lifecycle import Lifecycle
from ..triggers.base import TriggerBase
from ..actions.base import ActionBase

@dataclass
class Reflex:
    """
    단일 자동화 규칙
    
    Reflex = Trigger + Action + Tools + Lifecycle
    """
    id: str
    name: str
    trigger: TriggerBase
    action: ActionBase
    tools: List[str]  # tool 이름 리스트
    lifecycle: Lifecycle
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        # 메타데이터 초기화
        if 'created_at' not in self.metadata:
            self.metadata['created_at'] = datetime.now().isoformat()
        if 'runs' not in self.metadata:
            self.metadata['runs'] = 0
    
    def increment_runs(self):
        """실행 횟수 증가"""
        self.metadata['runs'] += 1
        self.metadata['last_run'] = datetime.now().isoformat()
    
    def should_expire(self) -> bool:
        """만료 체크"""
        # 시간 만료
        if self.lifecycle.expired():
            return True
        
        # 실행 횟수 만료
        if self.lifecycle.max_runs:
            if self.metadata['runs'] >= self.lifecycle.max_runs:
                return True
        
        return False
    
    def to_dict(self) -> Dict[str, Any]:
        """직렬화"""
        return {
            'id': self.id,
            'name': self.name,
            'enabled': self.enabled,
            'trigger': self.trigger.to_dict(),
            'action': self.action.to_dict(),
            'tools': self.tools,
            'lifecycle': self.lifecycle.to_dict(),
            'metadata': self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Reflex':
        """역직렬화"""
        return cls(
            id=data['id'],
            name=data['name'],
            enabled=data['enabled'],
            trigger=TriggerBase.from_dict(data['trigger']),
            action=ActionBase.from_dict(data['action']),
            tools=data['tools'],
            lifecycle=Lifecycle.from_dict(data['lifecycle']),
            metadata=data['metadata']
        )
    
    def __repr__(self):
        return f"Reflex(id='{self.id}', name='{self.name}', enabled={self.enabled})"
    
    