# reflex/core/lifecycle.py
from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

@dataclass
class Lifecycle:
    """
    Reflex 생명주기 관리
    
    Types:
        - persistent: 영구적 (수동 삭제까지)
        - temporary: 시간 제한 (TTL)
        - max_runs: 횟수 제한
    """
    type: str  # "persistent" | "temporary" | "max_runs"
    ttl_sec: Optional[int] = None  # temporary용 (초)
    max_runs: Optional[int] = None  # max_runs용 (횟수)
    created_at: Optional[str] = None  # ISO datetime
    expire_at: Optional[str] = None  # ISO datetime (temporary용, 자동 계산됨)
    
    def __post_init__(self):
        # 생성 시간 기록
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        
        # temporary면 만료 시간 계산
        if self.type == "temporary" and self.ttl_sec and not self.expire_at:
            expire_time = datetime.now() + timedelta(seconds=self.ttl_sec)
            self.expire_at = expire_time.isoformat()
    
    def expired(self, runs: int = 0) -> bool:
        """만료 체크 (runs는 현재 실행 횟수)"""
        if self.type == "persistent":
            return False
            
        if self.type == "temporary":
            if self.expire_at:
                return datetime.now() > datetime.fromisoformat(self.expire_at)
            return False
            
        if self.type == "max_runs":
            if self.max_runs is not None:
                return runs >= self.max_runs
            return False
        
        return False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'type': self.type,
            'ttl_sec': self.ttl_sec,
            'max_runs': self.max_runs,
            'created_at': self.created_at,
            'expire_at': self.expire_at
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Lifecycle':
        # 구버전 호환성 처리 (cooldown 제거)
        if 'cooldown_sec' in data:
            del data['cooldown_sec']
        return cls(**data)