# reflex/core/state.py
from typing import Dict, Any
import asyncio

class WorldState:
    """
    전역 상태 저장소
    
    모든 Reflex가 공유하는 상태
    """
    
    def __init__(self):
        self._state: Dict[str, Any] = {}
        self._lock = asyncio.Lock()
    
    async def set(self, key: str, value: Any):
        """상태 설정"""
        async with self._lock:
            self._state[key] = value
    
    async def get(self, key: str, default=None) -> Any:
        """상태 조회"""
        async with self._lock:
            return self._state.get(key, default)
    
    def get_all(self) -> Dict[str, Any]:
        """모든 상태 반환 (복사본)"""
        return dict(self._state)
    
    async def update(self, updates: Dict[str, Any]):
        """여러 키 한번에 업데이트"""
        async with self._lock:
            self._state.update(updates)
    
    def __repr__(self):
        return f"WorldState({len(self._state)} keys)"