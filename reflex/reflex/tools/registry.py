# reflex/tools/registry.py
from typing import Dict, Any, Callable, List, Literal, Optional
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client, StdioServerParameters
import asyncio
import logging

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    MCP 툴 레지스트리
    
    SSE 또는 STDIO로 MCP 서버에 연결해서 툴 관리
    """
    
    def __init__(
        self, 
        connection_type: Literal["sse", "stdio"] = "sse",
        # SSE 방식
        mcp_bridge_url: str = "http://localhost:8083",
        # STDIO 방식
        command: str = None,
        args: List[str] = None,
        env: Dict[str, str] = None
    ):
        """
        Args:
            connection_type: "sse" 또는 "stdio"
            mcp_bridge_url: SSE 방식일 때 브리지 URL
            command: STDIO 방식일 때 실행할 명령어 (예: "npx", "python")
            args: STDIO 방식일 때 명령어 인자
            env: STDIO 방식일 때 환경 변수
        """
        self.connection_type = connection_type
        
        # SSE 설정
        self.mcp_bridge_url = mcp_bridge_url
        self.sse_url = f"{mcp_bridge_url}/sse"
        
        # STDIO 설정
        self.command = command
        self.args = args or []
        self.env = env
        
        # 공통
        self.tools: Dict[str, Callable] = {}
        self.tool_schemas: Dict[str, Dict] = {}
        self.session: Optional[ClientSession] = None
        
        # Context managers를 직접 저장
        self._sse_context = None
        self._stdio_context = None
        self._session_context = None
        self._connected = False
    
    async def connect(self):
        """MCP 서버에 연결 (SSE 또는 STDIO)"""
        if self._connected:
            print(f"   ⚠️ Already connected ({self.connection_type})")
            return True
        
        try:
            if self.connection_type == "sse":
                result = await self._connect_sse()
            elif self.connection_type == "stdio":
                result = await self._connect_stdio()
            else:
                print(f"   ❌ Unknown connection type: {self.connection_type}")
                return False
            
            if result:
                self._connected = True
            return result
                
        except Exception as e:
            print(f"   ❌ Failed to connect: {e}\n")
            import traceback
            traceback.print_exc()
            return False
    
    async def _connect_sse(self):
        """SSE 방식으로 연결"""
        print(f"🔌 Connecting to MCP Server via SSE...")
        print(f"   URL: {self.sse_url}")
        
        # SSE 클라이언트로 연결
        self._sse_context = sse_client(url=self.sse_url)
        streams = await self._sse_context.__aenter__()
        
        # ClientSession 생성
        self.session = ClientSession(
            read_stream=streams[0],
            write_stream=streams[1]
        )
        self._session_context = self.session
        await self._session_context.__aenter__()
        
        # Initialize
        await self.session.initialize()
        
        print(f"   ✅ Connected via SSE\n")
        return True
    
    async def _connect_stdio(self):
        """STDIO 방식으로 연결"""
        print(f"🔌 Connecting to MCP Server via STDIO...")
        print(f"   Command: {self.command} {' '.join(self.args)}")
        
        # StdioServerParameters 생성
        server_params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=self.env
        )
        
        # STDIO 클라이언트로 연결
        self._stdio_context = stdio_client(server_params)
        streams = await self._stdio_context.__aenter__()
        
        # ClientSession 생성
        self.session = ClientSession(
            read_stream=streams[0],
            write_stream=streams[1]
        )
        self._session_context = self.session
        await self._session_context.__aenter__()
        
        # Initialize
        await self.session.initialize()
        
        print(f"   ✅ Connected via STDIO\n")
        return True
    
    async def disconnect(self):
        """연결 종료 - 모든 에러 무시"""
        if not self._connected:
            return
        
        # Session 종료 시도
        if self._session_context:
            try:
                await asyncio.wait_for(
                    self._session_context.__aexit__(None, None, None),
                    timeout=1.0
                )
            except:
                pass
            finally:
                self._session_context = None
                self.session = None
        
        # SSE context 종료 시도
        if self._sse_context:
            try:
                await asyncio.wait_for(
                    self._sse_context.__aexit__(None, None, None),
                    timeout=1.0
                )
            except:
                pass
            finally:
                self._sse_context = None
        
        # STDIO context 종료 시도
        if self._stdio_context:
            try:
                await asyncio.wait_for(
                    self._stdio_context.__aexit__(None, None, None),
                    timeout=1.0
                )
            except:
                pass
            finally:
                self._stdio_context = None
        
        self._connected = False
        print(f"🔌 Disconnected from MCP Server ({self.connection_type})")
    
    async def load_tools_from_mcp(self):
        """MCP 서버에서 사용 가능한 툴 목록 로드"""
        print("📦 Loading tools from MCP Server...")
        
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
            """Call MCP tool via session"""
            if not self.session:
                return {
                    'success': False,
                    'error': 'Not connected to MCP Server'
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


class ToolManager:
    """여러 MCP 서버를 통합 관리하는 매니저"""
    
    def __init__(self):
        self.registries: Dict[str, ToolRegistry] = {}
        self._connected = False
    
    @property
    def tools(self) -> Dict[str, Callable]:
        """
        모든 레지스트리의 툴을 하나로 합쳐서 반환
        형식: {registry_name}.{tool_name} 만 사용
        """
        all_tools = {}
        
        for registry_name, registry in self.registries.items():
            for tool_name, tool_func in registry.tools.items():
                # ✅ registry.tool_name 형식만 저장
                full_name = f"{registry_name}.{tool_name}"
                all_tools[full_name] = tool_func
        
        return all_tools
    
    @property
    def tool_schemas(self) -> Dict[str, Dict]:
        """
        모든 레지스트리의 툴 스키마를 하나로 합쳐서 반환
        """
        all_schemas = {}
        
        for registry_name, registry in self.registries.items():
            for tool_name, schema in registry.tool_schemas.items():
                # ✅ registry.tool_name 형식만 저장
                full_name = f"{registry_name}.{tool_name}"
                all_schemas[full_name] = schema
        
        return all_schemas
    
    def add_sse_registry(self, name: str, url: str):
        """SSE 방식 레지스트리 추가"""
        self.registries[name] = ToolRegistry(
            connection_type="sse",
            mcp_bridge_url=url
        )
        print(f"   ✓ Added SSE registry: {name}")
    
    def add_stdio_registry(self, name: str, command: str, args: List[str], env: Dict[str, str] = None):
        """STDIO 방식 레지스트리 추가"""
        self.registries[name] = ToolRegistry(
            connection_type="stdio",
            command=command,
            args=args,
            env=env
        )
        print(f"   ✓ Added STDIO registry: {name}")
    
    async def connect(self):
        """
        모든 레지스트리 연결 (ReflexEngine 호환)
        반드시 True/False 반환
        """
        if self._connected:
            print("   ⚠️ Already connected to all MCP servers")
            return True
        
        result = await self.connect_all()
        return result
    
    async def disconnect(self):
        """
        모든 레지스트리 연결 종료 (ReflexEngine 호환)
        """
        await self.disconnect_all()
    
    async def load_tools_from_mcp(self):
        """
        모든 레지스트리의 툴 로드 (ReflexEngine 호환)
        connect_all()에서 이미 로드되므로 여기서는 pass
        """
        pass
    
    async def connect_all(self):
        """
        모든 레지스트리 연결
        성공/실패 여부 반환
        """
        if self._connected:
            print("   ⚠️ Already connected to all MCP servers")
            return True
        
        print("\n🔌 Connecting to all MCP servers...")
        
        success_count = 0
        total_count = len(self.registries)
        
        for name, registry in self.registries.items():
            print(f"\n[{name}]")
            success = await registry.connect()
            if success:
                await registry.load_tools_from_mcp()
                success_count += 1
        
        print()
        
        # 하나라도 연결 성공하면 True
        if success_count > 0:
            self._connected = True
            print(f"✅ Connected to {success_count}/{total_count} MCP servers\n")
            return True
        else:
            print(f"❌ Failed to connect to any MCP servers\n")
            return False
    
    async def disconnect_all(self):
        """모든 레지스트리 연결 종료 - 모든 에러 무시"""
        if not self._connected:
            return
        
        print("\n🔌 Disconnecting from all MCP servers...")
        
        # 각 레지스트리를 독립적으로 종료
        for name, registry in self.registries.items():
            try:
                await registry.disconnect()
            except:
                # 모든 에러 완전히 무시
                pass
        
        self._connected = False
        print("✅ All disconnected")
    
    def get_all_tools(self) -> Dict[str, Callable]:
        """모든 레지스트리의 툴을 하나로 합침"""
        return self.tools
    
    def get_tools_by_registry(self, registry_name: str) -> Dict[str, Callable]:
        """특정 레지스트리의 툴만 가져오기"""
        if registry_name in self.registries:
            return self.registries[registry_name].tools
        return {}
    
    def get_tools_for_reflex(self, tool_names: List[str]) -> Dict[str, Callable]:
        """
        Reflex가 요청한 툴들 반환
        
        Args:
            tool_names: ['add', 'calculator.add', 'saba_bridge.invoke', ...]
        
        Returns:
            {full_tool_name: tool_function}
        """
        selected = {}
        
        for tool_name in tool_names:
            # 형식 1: registry_name.tool_name (명시적)
            if '.' in tool_name:
                if tool_name in self.tools:
                    selected[tool_name] = self.tools[tool_name]
                else:
                    print(f"      ⚠️ Tool '{tool_name}' not found")
            
            # 형식 2: tool_name만 (모든 레지스트리에서 검색)
            else:
                found = False
                for registry_name, registry in self.registries.items():
                    if tool_name in registry.tools:
                        # ✅ full name으로 저장
                        full_name = f"{registry_name}.{tool_name}"
                        selected[full_name] = registry.tools[tool_name]
                        found = True
                        break  # 첫 번째 매치만
                
                if not found:
                    print(f"      ⚠️ Tool '{tool_name}' not found in any registry")
        
        return selected
    
    def list_all_tools(self):
        """모든 툴 목록 출력"""
        print("\n📋 All Available Tools:")
        for name, registry in self.registries.items():
            tools = registry.list_tools()
            if tools:
                print(f"\n[{name}] ({len(tools)} tools)")
                for tool_name in tools:
                    schema = registry.get_tool_schema(tool_name)
                    desc = schema.get('description', 'No description')
                    print(f"   • {tool_name}: {desc}")
            else:
                print(f"\n[{name}] (no tools)")
    
    def list_tools(self) -> List[str]:
        """
        모든 툴 이름 반환 (registry.tool_name 형식만)
        """
        all_tool_names = []
        for registry_name, registry in self.registries.items():
            for tool_name in registry.list_tools():
                full_name = f"{registry_name}.{tool_name}"
                all_tool_names.append(full_name)
        
        return all_tool_names