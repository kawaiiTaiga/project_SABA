from typing import Dict, Any, Callable
from .base import ActionBase

@ActionBase.register('meow')
class MeowAction(ActionBase):
    """그냥 'meow' 출력하는 테스트용 액션"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.message = config.get('message', 'meow 🐾')

    async def execute(
        self,
        event: Dict[str, Any],
        state: Dict[str, Any],
        tools: Dict[str, Callable]
    ) -> Dict[str, Any]:
        print(f"😺 MeowAction triggered! Event={event}")
        print(self.message)
        return {
            'success': True,
            'text': self.message
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            'type': 'meow',
            'message': self.message
        }

    def __repr__(self):
        return f"MeowAction(message='{self.message}')"
