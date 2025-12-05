# reflex/triggers/schedule.py
from typing import Dict, Any, Tuple
from datetime import datetime
from croniter import croniter
from .base import TriggerBase

@TriggerBase.register('schedule')
class ScheduleTrigger(TriggerBase):
    """시간 기반 Trigger"""
    
    description = "Execute task periodically based on cron expression"
    schema = {
        "cron": {
            "type": "text",
            "description": "Cron expression (e.g. '0 9 * * *')",
            "default": "0 9 * * *"
        }
    }
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        config['type'] = 'schedule'
        self.cron = config.get('cron')
        if not self.cron:
            raise ValueError("ScheduleTrigger requires 'cron' field")
        
        try:
            self.cron_iter = croniter(self.cron, datetime.now())
            self.next_run = self.cron_iter.get_next(datetime)
        except Exception as e:
            raise ValueError(f"Invalid cron expression '{self.cron}': {e}")
    
    async def check(self, event: Dict[str, Any], state: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        now = datetime.now()
        
        # Always return context dict (all values as strings)
        context = {
            "type": "schedule",
            "cron": self.cron,
            "next_run": self.next_run.isoformat(),
            "checked_at": now.isoformat()
        }
        
        if now >= self.next_run:
            context["fired_at"] = now.isoformat()
            self.cron_iter = croniter(self.cron, now)
            self.next_run = self.cron_iter.get_next(datetime)
            context["next_run"] = self.next_run.isoformat()
            return (True, context)
        
        return (False, context)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'type': 'schedule',
            'cron': self.cron
        }