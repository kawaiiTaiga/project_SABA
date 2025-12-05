# reflex_mcp_server.py
"""
SABA Reflex MCP Server - LLM 친화적인 Reflex 관리 도구

Reflex Engine이 별도로 실행 중일 때, 이 MCP 서버를 통해
reflexes를 생성/수정/삭제할 수 있습니다.
"""
import asyncio
import sys
import os
import yaml
import shutil
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
import json

# 디렉토리 설정
REFLEX_DIR = "reflexes"
TRASH_DIR = "trashcan"

# MCP 서버 생성
app = Server("reflex-manager")


def _ensure_dirs():
    """필요한 디렉토리 생성"""
    os.makedirs(REFLEX_DIR, exist_ok=True)
    os.makedirs(TRASH_DIR, exist_ok=True)


def _get_reflex_path(name: str) -> str | None:
    """reflex 파일 경로 찾기"""
    for ext in ['.yaml', '.yml']:
        path = os.path.join(REFLEX_DIR, f"{name}{ext}")
        if os.path.exists(path):
            return path
    return None


def _get_trash_path(name: str) -> str | None:
    """휴지통 파일 경로 찾기"""
    for ext in ['.yaml', '.yml']:
        path = os.path.join(TRASH_DIR, f"{name}{ext}")
        if os.path.exists(path):
            return path
    return None


def _load_reflex(name: str) -> dict | None:
    """reflex 로드"""
    path = _get_reflex_path(name)
    if path:
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    return None


def _save_reflex(name: str, data: dict) -> str:
    """reflex 저장"""
    _ensure_dirs()
    path = os.path.join(REFLEX_DIR, f"{name}.yaml")
    with open(path, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, sort_keys=False, allow_unicode=True)
    return path


def _list_reflexes() -> list[dict]:
    """모든 reflex 목록"""
    if not os.path.exists(REFLEX_DIR):
        return []
    
    result = []
    for filename in os.listdir(REFLEX_DIR):
        if filename.endswith('.yaml') or filename.endswith('.yml'):
            name = os.path.splitext(filename)[0]
            path = os.path.join(REFLEX_DIR, filename)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                    result.append({
                        "name": name,
                        "display_name": data.get('name', name),
                        "trigger_type": data.get('trigger', {}).get('type', 'unknown'),
                        "action_type": data.get('action', {}).get('type', 'unknown'),
                        "enabled": data.get('enabled', True),
                        "lifecycle": data.get('lifecycle', {}).get('type', 'persistent')
                    })
            except Exception:
                result.append({"name": name, "error": "failed to load"})
    return result


def _get_triggers_info() -> dict:
    """사용 가능한 트리거 정보"""
    return {
        "schedule": {
            "description": "시간 기반 실행 (cron expression 사용)",
            "schema": {
                "cron": {
                    "type": "string",
                    "description": "Cron expression (예: '0 9 * * *' = 매일 오전 9시, '*/5 * * * *' = 5분마다)",
                    "required": True,
                    "examples": [
                        "0 9 * * *    # 매일 오전 9시",
                        "*/5 * * * *  # 5분마다",
                        "0 0 * * 1    # 매주 월요일 자정",
                        "* * * * *    # 매 분마다"
                    ]
                }
            }
        }
    }


def _get_actions_info() -> dict:
    """사용 가능한 액션 정보"""
    return {
        "llm": {
            "description": "LLM을 호출하여 텍스트 생성/처리",
            "schema": {
                "messages": {
                    "type": "array",
                    "description": "대화 메시지 배열 [{role: 'system'|'user', content: '...'}]",
                    "required": True
                }
            },
            "example": {
                "type": "llm",
                "messages": [
                    {"role": "system", "content": "당신은 도움이 되는 어시스턴트입니다."},
                    {"role": "user", "content": "오늘의 날씨를 알려주세요."}
                ]
            }
        },
        "tool": {
            "description": "MCP 도구를 직접 호출",
            "schema": {
                "arguments": {
                    "type": "string",
                    "description": "도구 인자 (JSON 문자열, 템플릿 변수 사용 가능)",
                    "required": False
                }
            },
            "example": {
                "type": "tool",
                "arguments": '{"a": "{{trigger.fired_at[14:16]}}", "b": "5"}'
            },
            "note": "tools 필드에 사용할 도구를 지정해야 합니다 (예: ['simple.add'])"
        },
        "meow": {
            "description": "테스트용 고양이 울음소리 출력",
            "schema": {},
            "example": {"type": "meow"}
        }
    }


def _json_response(success: bool, message: str = None, data: dict = None, error: str = None) -> str:
    """일관된 JSON 응답 생성"""
    response = {"success": success}
    if message:
        response["message"] = message
    if data:
        response["data"] = data
    if error:
        response["error"] = error
    return json.dumps(response, ensure_ascii=False, indent=2)


@app.list_tools()
async def list_tools() -> list[Tool]:
    """사용 가능한 도구 목록"""
    return [
        # === 조회 도구 ===
        Tool(
            name="list_reflexes",
            description="현재 등록된 모든 reflex 목록을 조회합니다. 각 reflex의 이름, 트리거 타입, 액션 타입, 활성화 상태를 반환합니다.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_reflex",
            description="특정 reflex의 상세 정보를 조회합니다. 전체 설정과 최근 실행 로그를 포함합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "reflex 이름 (파일명, 확장자 제외)"}
                },
                "required": ["name"]
            }
        ),
        Tool(
            name="get_triggers_info",
            description="사용 가능한 트리거 타입과 각 타입의 설정 스키마를 조회합니다. reflex 생성 전 이 도구로 가능한 트리거 옵션을 확인하세요.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_actions_info",
            description="사용 가능한 액션 타입과 각 타입의 설정 스키마를 조회합니다. reflex 생성 전 이 도구로 가능한 액션 옵션을 확인하세요.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        
        # === 생성/수정 도구 ===
        Tool(
            name="create_reflex",
            description="새로운 reflex를 생성합니다. 트리거와 액션 설정이 필요합니다. 먼저 get_triggers_info와 get_actions_info로 가능한 옵션을 확인하세요.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "reflex 이름 (영문, 언더스코어 권장. 예: morning_reminder)"},
                    "display_name": {"type": "string", "description": "표시 이름 (한글 가능. 예: 아침 알림)"},
                    "trigger_type": {"type": "string", "description": "트리거 타입 (schedule 등)"},
                    "trigger_config": {"type": "object", "description": "트리거 설정 (예: {cron: '0 9 * * *'})"},
                    "action_type": {"type": "string", "description": "액션 타입 (llm, tool, meow 등)"},
                    "action_config": {"type": "object", "description": "액션 설정 (type 제외한 추가 설정)"},
                    "tools": {"type": "array", "items": {"type": "string"}, "description": "사용할 도구 목록 (예: ['simple.add'])"},
                    "lifecycle_type": {"type": "string", "description": "생명주기 (persistent: 영구, temporary: 임시)", "default": "persistent"},
                    "ttl_sec": {"type": "integer", "description": "temporary일 때 만료 시간(초)"},
                    "max_runs": {"type": "integer", "description": "최대 실행 횟수 (선택)"},
                    "cooldown_sec": {"type": "integer", "description": "실행 간 대기 시간(초) (선택)"},
                    "enabled": {"type": "boolean", "description": "활성화 여부", "default": True}
                },
                "required": ["name", "trigger_type", "trigger_config", "action_type", "action_config"]
            }
        ),
        Tool(
            name="update_reflex",
            description="기존 reflex를 수정합니다. 변경하려는 필드만 전달하면 됩니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "수정할 reflex 이름"},
                    "display_name": {"type": "string", "description": "새 표시 이름"},
                    "trigger_type": {"type": "string", "description": "새 트리거 타입"},
                    "trigger_config": {"type": "object", "description": "새 트리거 설정"},
                    "action_type": {"type": "string", "description": "새 액션 타입"},
                    "action_config": {"type": "object", "description": "새 액션 설정"},
                    "tools": {"type": "array", "items": {"type": "string"}, "description": "새 도구 목록"},
                    "lifecycle_type": {"type": "string", "description": "새 생명주기"},
                    "ttl_sec": {"type": "integer", "description": "새 만료 시간"},
                    "max_runs": {"type": "integer", "description": "새 최대 실행 횟수"},
                    "cooldown_sec": {"type": "integer", "description": "새 대기 시간"},
                    "enabled": {"type": "boolean", "description": "활성화 여부"}
                },
                "required": ["name"]
            }
        ),
        
        # === 상태 제어 도구 ===
        Tool(
            name="enable_reflex",
            description="reflex를 활성화합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "활성화할 reflex 이름"}
                },
                "required": ["name"]
            }
        ),
        Tool(
            name="disable_reflex",
            description="reflex를 비활성화합니다. 비활성화된 reflex는 트리거가 발동해도 실행되지 않습니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "비활성화할 reflex 이름"}
                },
                "required": ["name"]
            }
        ),
        
        # === 삭제/복원 도구 ===
        Tool(
            name="delete_reflex",
            description="reflex를 삭제합니다 (휴지통으로 이동). restore_reflex로 복원 가능합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "삭제할 reflex 이름"}
                },
                "required": ["name"]
            }
        ),
        Tool(
            name="restore_reflex",
            description="휴지통에서 reflex를 복원합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "복원할 reflex 이름"}
                },
                "required": ["name"]
            }
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """도구 실행"""
    
    try:
        # === 조회 도구 ===
        if name == "list_reflexes":
            reflexes = _list_reflexes()
            if not reflexes:
                return [TextContent(type="text", text=_json_response(
                    True, "등록된 reflex가 없습니다.", {"reflexes": [], "count": 0}
                ))]
            return [TextContent(type="text", text=_json_response(
                True, f"{len(reflexes)}개의 reflex가 있습니다.", {"reflexes": reflexes, "count": len(reflexes)}
            ))]
        
        elif name == "get_reflex":
            reflex_name = arguments.get("name")
            if not reflex_name:
                return [TextContent(type="text", text=_json_response(False, error="name 파라미터가 필요합니다."))]
            
            data = _load_reflex(reflex_name)
            if not data:
                return [TextContent(type="text", text=_json_response(
                    False, error=f"'{reflex_name}' reflex를 찾을 수 없습니다."
                ))]
            
            return [TextContent(type="text", text=_json_response(
                True, f"'{reflex_name}' reflex 정보", {"reflex": data}
            ))]
        
        elif name == "get_triggers_info":
            return [TextContent(type="text", text=_json_response(
                True, "사용 가능한 트리거 타입", {"triggers": _get_triggers_info()}
            ))]
        
        elif name == "get_actions_info":
            return [TextContent(type="text", text=_json_response(
                True, "사용 가능한 액션 타입", {"actions": _get_actions_info()}
            ))]
        
        # === 생성/수정 도구 ===
        elif name == "create_reflex":
            reflex_name = arguments.get("name")
            if not reflex_name:
                return [TextContent(type="text", text=_json_response(False, error="name 파라미터가 필요합니다."))]
            
            # 이미 존재하는지 확인
            if _get_reflex_path(reflex_name):
                return [TextContent(type="text", text=_json_response(
                    False, error=f"'{reflex_name}' reflex가 이미 존재합니다. update_reflex를 사용하세요."
                ))]
            
            # 트리거 설정
            trigger_type = arguments.get("trigger_type")
            trigger_config = arguments.get("trigger_config", {})
            if not trigger_type:
                return [TextContent(type="text", text=_json_response(False, error="trigger_type이 필요합니다."))]
            
            trigger = {"type": trigger_type, **trigger_config}
            
            # 액션 설정
            action_type = arguments.get("action_type")
            action_config = arguments.get("action_config", {})
            if not action_type:
                return [TextContent(type="text", text=_json_response(False, error="action_type이 필요합니다."))]
            
            action = {"type": action_type, **action_config}
            
            # 생명주기 설정
            lifecycle_type = arguments.get("lifecycle_type", "persistent")
            lifecycle = {"type": lifecycle_type}
            if lifecycle_type == "temporary":
                if arguments.get("ttl_sec"):
                    lifecycle["ttl_sec"] = arguments["ttl_sec"]
            if arguments.get("max_runs"):
                lifecycle["max_runs"] = arguments["max_runs"]
            if arguments.get("cooldown_sec"):
                lifecycle["cooldown_sec"] = arguments["cooldown_sec"]
            
            # reflex 데이터 생성
            reflex_data = {
                "id": reflex_name,
                "name": arguments.get("display_name", reflex_name.replace("_", " ").title()),
                "trigger": trigger,
                "action": action,
                "tools": arguments.get("tools", []),
                "lifecycle": lifecycle,
                "enabled": arguments.get("enabled", True)
            }
            
            path = _save_reflex(reflex_name, reflex_data)
            return [TextContent(type="text", text=_json_response(
                True, f"'{reflex_name}' reflex가 생성되었습니다.", {"path": path, "reflex": reflex_data}
            ))]
        
        elif name == "update_reflex":
            reflex_name = arguments.get("name")
            if not reflex_name:
                return [TextContent(type="text", text=_json_response(False, error="name 파라미터가 필요합니다."))]
            
            data = _load_reflex(reflex_name)
            if not data:
                return [TextContent(type="text", text=_json_response(
                    False, error=f"'{reflex_name}' reflex를 찾을 수 없습니다."
                ))]
            
            # 업데이트 적용
            if arguments.get("display_name"):
                data["name"] = arguments["display_name"]
            
            if arguments.get("trigger_type") or arguments.get("trigger_config"):
                trigger = data.get("trigger", {})
                if arguments.get("trigger_type"):
                    trigger["type"] = arguments["trigger_type"]
                if arguments.get("trigger_config"):
                    trigger.update(arguments["trigger_config"])
                data["trigger"] = trigger
            
            if arguments.get("action_type") or arguments.get("action_config"):
                action = data.get("action", {})
                if arguments.get("action_type"):
                    action["type"] = arguments["action_type"]
                if arguments.get("action_config"):
                    action.update(arguments["action_config"])
                data["action"] = action
            
            if arguments.get("tools") is not None:
                data["tools"] = arguments["tools"]
            
            if arguments.get("lifecycle_type") or arguments.get("ttl_sec") or arguments.get("max_runs") or arguments.get("cooldown_sec"):
                lifecycle = data.get("lifecycle", {})
                if arguments.get("lifecycle_type"):
                    lifecycle["type"] = arguments["lifecycle_type"]
                if arguments.get("ttl_sec"):
                    lifecycle["ttl_sec"] = arguments["ttl_sec"]
                if arguments.get("max_runs"):
                    lifecycle["max_runs"] = arguments["max_runs"]
                if arguments.get("cooldown_sec"):
                    lifecycle["cooldown_sec"] = arguments["cooldown_sec"]
                data["lifecycle"] = lifecycle
            
            if "enabled" in arguments:
                data["enabled"] = arguments["enabled"]
            
            path = _save_reflex(reflex_name, data)
            return [TextContent(type="text", text=_json_response(
                True, f"'{reflex_name}' reflex가 업데이트되었습니다.", {"path": path, "reflex": data}
            ))]
        
        # === 상태 제어 도구 ===
        elif name == "enable_reflex":
            reflex_name = arguments.get("name")
            if not reflex_name:
                return [TextContent(type="text", text=_json_response(False, error="name 파라미터가 필요합니다."))]
            
            data = _load_reflex(reflex_name)
            if not data:
                return [TextContent(type="text", text=_json_response(
                    False, error=f"'{reflex_name}' reflex를 찾을 수 없습니다."
                ))]
            
            if data.get("enabled", True):
                return [TextContent(type="text", text=_json_response(
                    True, f"'{reflex_name}'은(는) 이미 활성화 상태입니다."
                ))]
            
            data["enabled"] = True
            _save_reflex(reflex_name, data)
            return [TextContent(type="text", text=_json_response(
                True, f"'{reflex_name}' reflex가 활성화되었습니다."
            ))]
        
        elif name == "disable_reflex":
            reflex_name = arguments.get("name")
            if not reflex_name:
                return [TextContent(type="text", text=_json_response(False, error="name 파라미터가 필요합니다."))]
            
            data = _load_reflex(reflex_name)
            if not data:
                return [TextContent(type="text", text=_json_response(
                    False, error=f"'{reflex_name}' reflex를 찾을 수 없습니다."
                ))]
            
            if not data.get("enabled", True):
                return [TextContent(type="text", text=_json_response(
                    True, f"'{reflex_name}'은(는) 이미 비활성화 상태입니다."
                ))]
            
            data["enabled"] = False
            _save_reflex(reflex_name, data)
            return [TextContent(type="text", text=_json_response(
                True, f"'{reflex_name}' reflex가 비활성화되었습니다."
            ))]
        
        # === 삭제/복원 도구 ===
        elif name == "delete_reflex":
            reflex_name = arguments.get("name")
            if not reflex_name:
                return [TextContent(type="text", text=_json_response(False, error="name 파라미터가 필요합니다."))]
            
            src = _get_reflex_path(reflex_name)
            if not src:
                return [TextContent(type="text", text=_json_response(
                    False, error=f"'{reflex_name}' reflex를 찾을 수 없습니다."
                ))]
            
            _ensure_dirs()
            filename = os.path.basename(src)
            dst = os.path.join(TRASH_DIR, filename)
            shutil.move(src, dst)
            
            return [TextContent(type="text", text=_json_response(
                True, f"'{reflex_name}' reflex가 휴지통으로 이동되었습니다. restore_reflex로 복원할 수 있습니다."
            ))]
        
        elif name == "restore_reflex":
            reflex_name = arguments.get("name")
            if not reflex_name:
                return [TextContent(type="text", text=_json_response(False, error="name 파라미터가 필요합니다."))]
            
            src = _get_trash_path(reflex_name)
            if not src:
                return [TextContent(type="text", text=_json_response(
                    False, error=f"휴지통에서 '{reflex_name}' reflex를 찾을 수 없습니다."
                ))]
            
            _ensure_dirs()
            filename = os.path.basename(src)
            dst = os.path.join(REFLEX_DIR, filename)
            
            # 이미 존재하면 에러
            if os.path.exists(dst):
                return [TextContent(type="text", text=_json_response(
                    False, error=f"'{reflex_name}' reflex가 이미 존재합니다. 먼저 삭제하거나 다른 이름으로 복원하세요."
                ))]
            
            shutil.move(src, dst)
            return [TextContent(type="text", text=_json_response(
                True, f"'{reflex_name}' reflex가 복원되었습니다."
            ))]
        
        else:
            return [TextContent(type="text", text=_json_response(
                False, error=f"알 수 없는 도구: {name}"
            ))]
    
    except Exception as e:
        return [TextContent(type="text", text=_json_response(
            False, error=f"오류 발생: {str(e)}"
        ))]


async def main():
    """서버 실행"""
    print("Starting reflex-manager MCP server...", file=sys.stderr)
    
    async with stdio_server() as (read_stream, write_stream):
        print("STDIO server initialized, running...", file=sys.stderr)
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    # Windows에서 asyncio 이벤트 루프 정책 설정
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    asyncio.run(main())
