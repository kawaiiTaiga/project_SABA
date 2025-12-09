from typing import Dict, Any, Tuple
from datetime import datetime
from .base import TriggerBase

@TriggerBase.register("startup")
class StartupTrigger(TriggerBase):
    """
    엔진 시작 시 1회 실행되는 Trigger
    """
    
    description = "Fires once when the engine starts"
    schema = {}

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._fired = False

    async def check(self, event: Dict[str, Any], state: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        if not self._fired:
            self._fired = True
            return True, {
                "type": "startup",
                "fired_at": datetime.now().isoformat()
            }
        
        return False, {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "startup",
            "cooldown_sec": self.cooldown_sec
        }
