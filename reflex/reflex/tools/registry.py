# reflex/tools/registry.py
from typing import Dict, Any, Callable, List
from contextlib import AsyncExitStack
from mcp import ClientSession
from mcp.client.sse import sse_client
import httpx
import logging

logger = logging.getLogger(__name__)

class ToolRegistry:
    """
    MCP 툴 레지스트리
    
    SABA MCP Bridge에 SSE로 연결해서 툴 관리
    """
    
    def __init__(self, mcp_bridge_url: str = "http://localhost:8083\sse"):
        self.mcp_bridge_url = mcp_bridge_url
        self.sse_url = f"{mcp_bridge_url}/sse"  # SSE 엔드포인트
        self.tools: Dict[str, Callable] = {}
        self.tool_schemas: Dict[str, Dict] = {}
        self.session: ClientSession = None
        self.exit_stack = AsyncExitStack()
    
    async def connect(self):
        """MCP Bridge에 SSE로 연결"""
        try:
            print(f"🔌 Connecting to MCP Bridge via SSE...")
            print(f"   URL: {self.sse_url}")
            
            # SSE 클라이언트로 연결
            streams_context = sse_client(url=self.sse_url)
            streams = await self.exit_stack.enter_async_context(streams_context)
            
            # ClientSession 생성
            self.session = ClientSession(
                read_stream=streams[0],
                write_stream=streams[1]
            )
            await self.exit_stack.enter_async_context(self.session)
            
            # Initialize
            await self.session.initialize()
            
            print(f"   ✅ Connected to MCP Bridge\n")
            return True
            
        except Exception as e:
            print(f"   ❌ Failed to connect: {e}\n")
            return False
    
    async def disconnect(self):
        """연결 종료"""
        await self.exit_stack.aclose()
        print("🔌 Disconnected from MCP Bridge")
    
    async def load_tools_from_mcp(self):
        """
        MCP Bridge에서 사용 가능한 툴 목록 로드
        """
        print("📦 Loading tools from MCP Bridge...")
        
        if not self.session:
            print("   ⚠️ Not connected. Call connect() first.")
            return
        
        try:
            # MCP Session으로 툴 목록 가져오기
            tools_result = await self.session.list_tools()
            mcp_tools = tools_result.tools
            
            print(f"   Found {len(mcp_tools)} tool(s) from MCP")
            
            # 각 툴 등록
            for tool in mcp_tools:
                tool_name = tool.name
                
                print(f"      ✓ {tool_name}")
                
                # 툴 함수 생성
                tool_func = self._create_tool_function(tool_name, tool)
                
                # 등록
                self.tools[tool_name] = tool_func
                self.tool_schemas[tool_name] = {
                    'name': tool.name,
                    'description': tool.description,
                    'parameters': tool.inputSchema if hasattr(tool, 'inputSchema') else {}
                }
            
            print(f"\n✅ Loaded {len(self.tools)} tool(s) total\n")
            
        except Exception as e:
            print(f"   ❌ Error loading tools: {e}\n")
            raise
    
    def _create_tool_function(self, tool_name: str, tool_info: Any) -> Callable:
        """
        MCP 툴 호출 함수 생성 (클로저)
        
        이 함수가 실제로 MCP Session을 통해 툴을 호출함
        """
        async def tool_func(**kwargs):
            """Call MCP tool via SSE session"""
            if not self.session:
                return {
                    'success': False,
                    'error': 'Not connected to MCP Bridge'
                }
            
            try:
                # MCP Session으로 tool 호출
                result = await self.session.call_tool(tool_name, arguments=kwargs)
                
                # 결과 처리
                if result.isError:
                    return {
                        'success': False,
                        'error': str(result.content)
                    }
                
                # 성공 시 content 반환
                content_list = []
                for content in result.content:
                    if hasattr(content, 'text'):
                        content_list.append(content.text)
                    elif hasattr(content, 'data'):
                        content_list.append(content.data)
                
                return {
                    'success': True,
                    'result': content_list[0] if len(content_list) == 1 else content_list
                }
                
            except Exception as e:
                return {
                    'success': False,
                    'error': str(e)
                }
        
        # Docstring 설정 (LLM이 이걸 봄)
        tool_func.__doc__ = tool_info.description or f"Call {tool_name}"
        
        # 스키마를 함수 attribute로 추가 (LLMAction이 이걸 사용)
        tool_func._mcp_schema = {
            'name': tool_info.name,
            'description': tool_info.description,
            'parameters': tool_info.inputSchema if hasattr(tool_info, 'inputSchema') else {}
        }
        
        return tool_func
    
    def get_tools_for_reflex(self, tool_names: List[str]) -> Dict[str, Callable]:
        """
        Reflex가 사용할 툴들만 반환
        
        Args:
            tool_names: ['check_plant_health', ...]
        
        Returns:
            {tool_name: tool_function, ...}
        """
        selected = {}
        
        for name in tool_names:
            if name in self.tools:
                selected[name] = self.tools[name]
            else:
                print(f"      ⚠️ Tool '{name}' not found in registry")
        
        return selected
    
    def list_tools(self) -> List[str]:
        """사용 가능한 툴 목록"""
        return list(self.tools.keys())
    
    def get_tool_schema(self, tool_name: str) -> Dict[str, Any]:
        """툴 스키마 조회"""
        return self.tool_schemas.get(tool_name, {})