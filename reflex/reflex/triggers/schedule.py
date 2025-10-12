# reflex/triggers/schedule.py
from typing import Dict, Any
from datetime import datetime
from croniter import croniter
from .base import TriggerBase

@TriggerBase.register('schedule')  # ← 자동 등록!
class ScheduleTrigger(TriggerBase):
    """시간 기반 Trigger"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        
        self.cron = config.get('cron')
        if not self.cron:
            raise ValueError("ScheduleTrigger requires 'cron' field")
        
        try:
            self.cron_iter = croniter(self.cron, datetime.now())
            self.next_run = self.cron_iter.get_next(datetime)
        except Exception as e:
            raise ValueError(f"Invalid cron expression '{self.cron}': {e}")
    
    async def check(self, event: Dict[str, Any], state: Dict[str, Any]) -> bool:
        now = datetime.now()
        
        if now >= self.next_run:
            self.cron_iter = croniter(self.cron, now)
            self.next_run = self.cron_iter.get_next(datetime)
            return True
        
        return False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'type': 'schedule',
            'cron': self.cron
        }