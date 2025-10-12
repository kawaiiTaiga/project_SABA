# reflex/tools/registry.py
from typing import Dict, Any, Callable, List
import httpx

class ToolRegistry:
    """
    MCP 툴 레지스트리
    
    SABA MCP Bridge에서 툴 목록을 가져와서 관리
    """
    
    def __init__(self, mcp_bridge_url: str = "http://localhost:8083"):
        self.mcp_bridge_url = mcp_bridge_url
        self.tools: Dict[str, Callable] = {}
        self.tool_schemas: Dict[str, Dict] = {}
    
    async def load_tools_from_mcp(self):
        """
        MCP Bridge에서 사용 가능한 툴 목록 로드
        """
        print("📦 Loading tools from MCP Bridge...")
        print(f"   URL: {self.mcp_bridge_url}")
        
        try:
            async with httpx.AsyncClient() as client:
                # 디바이스 목록 가져오기
                resp = await client.get(
                    f"{self.mcp_bridge_url}/devices",
                    timeout=10.0
                )
                resp.raise_for_status()
                devices = resp.json()
                
                print(f"   Found {len(devices)} device(s)")
                
                # 각 디바이스의 툴 등록
                for device in devices:
                    device_id = device.get('device_id')
                    tools = device.get('tools', [])
                    
                    print(f"\n   Device: {device_id}")
                    
                    for tool in tools:
                        tool_name = tool.get('name')
                        
                        # 전역 툴 이름 생성
                        # 예: check_plant_health_esp32-plant-01
                        global_name = f"{tool_name}_{device_id}"
                        
                        # 툴 함수 생성
                        tool_func = self._create_tool_function(device_id, tool_name)
                        
                        # 등록
                        self.tools[global_name] = tool_func
                        self.tool_schemas[global_name] = tool
                        
                        print(f"      ✓ {global_name}")
                
                print(f"\n✅ Loaded {len(self.tools)} tool(s) total\n")
                
        except httpx.ConnectError:
            print(f"   ❌ Cannot connect to MCP Bridge at {self.mcp_bridge_url}")
            print(f"   Make sure MCP Bridge is running!\n")
            raise
        except Exception as e:
            print(f"   ❌ Error loading tools: {e}\n")
            raise
    
    def _create_tool_function(self, device_id: str, tool_name: str) -> Callable:
        """
        MCP 툴 호출 함수 생성 (클로저)
        
        이 함수가 실제로 MCP Bridge를 통해 디바이스 툴을 호출함
        """
        async def tool_func(**kwargs):
            """Call MCP tool via bridge"""
            async with httpx.AsyncClient() as client:
                try:
                    # MCP Bridge의 invoke 엔드포인트 호출
                    resp = await client.post(
                        f"{self.mcp_bridge_url}/invoke",
                        json={
                            'device_id': device_id,
                            'tool': tool_name,
                            'args': kwargs
                        },
                        timeout=30.0
                    )
                    resp.raise_for_status()
                    return resp.json()
                    
                except Exception as e:
                    return {
                        'success': False,
                        'error': str(e)
                    }
        
        # Docstring 설정 (LLM이 이걸 봄)
        schema = self.tool_schemas.get(f"{tool_name}_{device_id}", {})
        tool_func.__doc__ = schema.get('description', f"Call {tool_name} on {device_id}")
        
        return tool_func
    
    def get_tools_for_reflex(self, tool_names: List[str]) -> Dict[str, Callable]:
        """
        Reflex가 사용할 툴들만 반환
        
        Args:
            tool_names: ['check_plant_health_esp32-plant-01', ...]
        
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