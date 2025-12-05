# reflex/core/lifecycle.py
from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

@dataclass
class Lifecycle:
    """
    Reflex 생명주기 관리
    
    Types:
        - temporary: 일정 시간 후 만료
        - persistent: 영구적 (수동 삭제까지)
    """
    type: str  # "temporary" | "persistent"
    ttl_sec: Optional[int] = None  # temporary용 (초)
    max_runs: Optional[int] = None  # 최대 실행 횟수 (None=무제한)
    cooldown_sec: Optional[int] = None  # 실행 간 대기 시간 (초)
    created_at: Optional[str] = None  # ISO datetime
    expire_at: Optional[str] = None  # ISO datetime (자동 계산됨)
    
    def __post_init__(self):
        # 생성 시간 기록
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        
        # temporary면 만료 시간 계산
        if self.type == "temporary" and self.ttl_sec and not self.expire_at:
            expire_time = datetime.now() + timedelta(seconds=self.ttl_sec)
            self.expire_at = expire_time.isoformat()
    
    def expired(self) -> bool:
        """시간상 만료되었는지"""
        if self.type == "persistent":
            return False
        
        if self.expire_at:
            return datetime.now() > datetime.fromisoformat(self.expire_at)
        
        return False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'type': self.type,
            'ttl_sec': self.ttl_sec,
            'max_runs': self.max_runs,
            'cooldown_sec': self.cooldown_sec,
            'created_at': self.created_at,
            'expire_at': self.expire_at
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Lifecycle':
        return cls(**data)