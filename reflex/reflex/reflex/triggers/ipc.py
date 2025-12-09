
from typing import Dict, Any
from .base import TriggerBase

class IPCTrigger(TriggerBase):
    """
    Triggered by specific IPC events.
    """
    
    description = "Triggered by IPC messages (e.g. Wakeword)"
    schema = {
        "event_name": {
            "type": "text",
            "description": "Name of the IPC event to listen for (e.g., 'wakeword')",
            "default": "wakeword"
        }
    }
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.event_name = config.get('event_name', 'wakeword')

    def matches(self, event: Dict[str, Any]) -> bool:
        if event.get('type') != 'ipc_event':
            return False
            
        # Check event name
        return event.get('name') == self.event_name
