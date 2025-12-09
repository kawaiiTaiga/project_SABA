# simple_mcp_server.py
"""
초간단 MCP 서버 - 계산기 3종 세트
"""
import asyncio
import sys
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# MCP 서버 생성
app = Server("simple-calculator")

@app.list_tools()
async def list_tools() -> list[Tool]:
    """사용 가능한 툴 목록"""
    return [
        Tool(
            name="add",
            description="두 숫자를 더합니다",
            inputSchema={
                "type": "object",
                "properties": {
                    "a": {"type": "string", "description": "첫 번째 숫자"},
                    "b": {"type": "string", "description": "두 번째 숫자"}
                },
                "required": ["a", "b"]
            }
        ),
        Tool(
            name="multiply",
            description="두 숫자를 곱합니다",
            inputSchema={
                "type": "object",
                "properties": {
                    "a": {"type": "string", "description": "첫 번째 숫자"},
                    "b": {"type": "string", "description": "두 번째 숫자"}
                },
                "required": ["a", "b"]
            }
        ),
        Tool(
            name="greet",
            description="이름을 받아서 인사합니다",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "인사할 이름"}
                },
                "required": ["name"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """툴 실행"""
    
    if name == "add":
        a = float(arguments.get("a", 0))
        b = float(arguments.get("b", 0))
        result = a + b
        return [TextContent(
            type="text",
            text=f"{a} + {b} = {result}"
        )]
    
    elif name == "multiply":
        a = float(arguments.get("a", 1))
        b = float(arguments.get("b", 1))
        result = a * b
        return [TextContent(
            type="text",
            text=f"{a} × {b} = {result}"
        )]
    
    elif name == "greet":
        name_arg = arguments.get("name", "World")
        return [TextContent(
            type="text",
            text=f"안녕하세요, {name_arg}님! 🎉"
        )]
    
    else:
        return [TextContent(
            type="text",
            text=f"Unknown tool: {name}"
        )]

async def main():
    """서버 실행"""
    # 디버그 로그는 stderr로 출력 (stdout은 MCP 통신용)
    print("Starting simple-calculator MCP server...", file=sys.stderr)
    
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