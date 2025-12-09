import sqlite3
import json
import os
from datetime import datetime
from typing import Optional, Dict, Any

class DatabaseManager:
    """Reflex 실행 기록을 관리하는 데이터베이스 매니저 (SQLite)"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """데이터베이스 및 테이블 초기화"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 실행 로그 테이블 생성
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS execution_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    reflex_id TEXT NOT NULL,
                    reflex_name TEXT,
                    trigger_type TEXT,
                    trigger_context TEXT,
                    action_type TEXT,
                    status TEXT,
                    output TEXT,
                    tool_calls TEXT,
                    error_message TEXT
                )
            ''')
            
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"❌ Database initialization failed: {e}")

    def log_execution(
        self,
        reflex_id: str,
        reflex_name: str,
        trigger_type: str,
        trigger_context: Dict[str, Any],
        action_type: str,
        status: str,
        output: Optional[str] = None,
        tool_calls: Optional[list] = None,
        error_message: Optional[str] = None
    ):
        """실행 기록 저장"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # JSON 직렬화
            trigger_ctx_json = json.dumps(trigger_context, ensure_ascii=False) if trigger_context else "{}"
            tool_calls_json = json.dumps(tool_calls, ensure_ascii=False) if tool_calls else "[]"
            
            cursor.execute('''
                INSERT INTO execution_log (
                    timestamp, reflex_id, reflex_name, trigger_type, 
                    trigger_context, action_type, status, output, 
                    tool_calls, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                datetime.now().isoformat(),
                reflex_id,
                reflex_name,
                trigger_type,
                trigger_ctx_json,
                action_type,
                status,
                output,
                tool_calls_json,
                error_message
            ))
            
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"❌ Failed to log execution to DB: {e}")
