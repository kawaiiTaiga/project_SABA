import os
import sqlite3
import json
import sys

# Add current directory to path so we can import reflex
sys.path.append(os.getcwd())

from reflex.core.database import DatabaseManager

def test_db_logging():
    db_path = "test_execution.db"
    if os.path.exists(db_path):
        os.remove(db_path)
        
    print(f"Testing DatabaseManager with {db_path}...")
    db = DatabaseManager(db_path)
    
    # Test Data
    reflex_id = "test_reflex"
    reflex_name = "Test Reflex"
    trigger_type = "schedule"
    trigger_context = {"timestamp": 1234567890}
    action_type = "log"
    status = "SUCCESS"
    output = "Test Output"
    tool_calls = [{"tool": "test", "result": "ok"}]
    
    print("Logging execution...")
    db.log_execution(
        reflex_id=reflex_id,
        reflex_name=reflex_name,
        trigger_type=trigger_type,
        trigger_context=trigger_context,
        action_type=action_type,
        status=status,
        output=output,
        tool_calls=tool_calls
    )
    
    print("Verifying database...")
    if not os.path.exists(db_path):
        print("❌ DB file not created!")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM execution_log")
    row = cursor.fetchone()
    conn.close()
    
    if row:
        print("[OK] Log found!")
        # row schema: 
        # 0: id, 1: timestamp, 2: reflex_id, 3: reflex_name, 
        # 4: trigger_type, 5: trigger_context, 6: action_type, 
        # 7: status, 8: output, 9: tool_calls, 10: error_message
        
        print(f"   Row: {row}")
        
        if row[2] == reflex_id and row[8] == output:
            print("[OK] Data matches!")
        else:
            print(f"[FAIL] Data mismatch!")
    else:
        print("[FAIL] No log found!")

    # Cleanup
    if os.path.exists(db_path):
        os.remove(db_path)
        print("Cleaned up test DB.")

if __name__ == "__main__":
    test_db_logging()
