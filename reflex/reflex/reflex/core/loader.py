# reflex/core/loader.py
import yaml
import os
from typing import List, Dict, Any, Optional
from .reflex import Reflex
from .lifecycle import Lifecycle
from ..triggers.base import TriggerBase
from ..actions.base import ActionBase

# Ensure all action/trigger subclasses are loaded
import reflex.triggers
import reflex.actions

class ReflexLoader:
    """
    YAML 파일에서 Reflex를 로드하는 클래스
    """
    
    @staticmethod
    def load_from_file(file_path: str) -> Optional[Reflex]:
        """YAML 파일에서 단일 Reflex 로드"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                
            return ReflexLoader._parse_reflex_data(data, file_path)
        except Exception as e:
            print(f"❌ Failed to load reflex from {file_path}: {e}")
            return None

    @staticmethod
    def load_all(directory: str) -> List[Reflex]:
        """디렉토리의 모든 YAML 파일에서 Reflex 로드"""
        reflexes = []
        if not os.path.exists(directory):
            return reflexes

        for filename in os.listdir(directory):
            if filename.endswith('.yaml') or filename.endswith('.yml'):
                file_path = os.path.join(directory, filename)
                reflex = ReflexLoader.load_from_file(file_path)
                if reflex:
                    reflexes.append(reflex)
        return reflexes

    @staticmethod
    def _parse_reflex_data(data: Dict[str, Any], file_path: str) -> Reflex:
        """Dict 데이터를 Reflex 객체로 변환"""
        
        # ID가 없으면 파일명(확장자 제외) 사용
        if 'id' not in data:
            data['id'] = os.path.splitext(os.path.basename(file_path))[0]
            
        # Trigger 파싱 - from_dict 사용으로 모든 타입 지원
        trigger_data = data.get('trigger', {})
        trigger = TriggerBase.from_dict(trigger_data)

        # Action 파싱 - from_dict 사용으로 모든 타입 지원
        action_data = data.get('action', {})
        action = ActionBase.from_dict(action_data)

        # Lifecycle 파싱
        lifecycle_data = data.get('lifecycle', {'type': 'persistent'})
        lifecycle = Lifecycle.from_dict(lifecycle_data)

        return Reflex(
            id=data['id'],
            name=data.get('name', data['id']),
            trigger=trigger,
            action=action,
            tools=data.get('tools', []),
            lifecycle=lifecycle,
            enabled=data.get('enabled', True),
            metadata=data.get('metadata', {}),
            source_file=file_path
        )

