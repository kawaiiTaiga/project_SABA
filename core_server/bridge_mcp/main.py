import os
import sys
import socket
import uvicorn
from fastapi import FastAPI, HTTPException
from http import HTTPStatus

from .config import PROJECTION_CONFIG_PATH, ROUTING_CONFIG_PATH, VIRTUAL_TOOLS_CONFIG_PATH, API_PORT, MQTT_HOST, MQTT_PORT, KEEPALIVE
from .utils import log, now_iso
from .tool_projection import ToolProjectionStore
from .tool_registry import DynamicToolRegistry
from .device_store import DeviceStore
from .command import CommandWaiter
from .mqtt import start_mqtt_listener, publish_to_inport, get_mqtt_pub_client
from .ipc import IPCAgent
from .server import BridgeServer
from .virtual_tool import VirtualToolStore, VirtualToolExecutor
from port_routing import PortStore, RoutingMatrix, PortRouter

def pick_free_port(base: int, tries: int) -> int | None:
    for p in range(base, base + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("0.0.0.0", p))
            except OSError:
                continue
            return p
    return None

def main():
    # 1. Initialize Stores
    projection_store = ToolProjectionStore(PROJECTION_CONFIG_PATH)
    tool_registry = DynamicToolRegistry(projection_store)
    device_store = DeviceStore(tool_registry)
    cmd_waiter = CommandWaiter()
    port_store = PortStore()
    routing_matrix = RoutingMatrix(ROUTING_CONFIG_PATH)
    virtual_tool_store = VirtualToolStore(VIRTUAL_TOOLS_CONFIG_PATH)
    
    # 3. Initialize IPC Agent (needed for publisher)
    ipc_agent = IPCAgent(device_store, cmd_waiter, port_store, None) # router passed later
    
    # Define Hybrid Publisher
    def hybrid_publish(device_id: str, port: str, value: float) -> bool:
        d = device_store.get(device_id)
        if d and d.get("protocol") == 'ipc':
            return ipc_agent.send_port_set(device_id, port, value)
        return publish_to_inport(device_id, port, value)

    # 2. Initialize Port Router
    port_router = PortRouter(routing_matrix, hybrid_publish)
    
    # Update IPC Agent with router
    ipc_agent.port_router = port_router
    # CRITICAL: Also update the protocol handler's router (it was created with None!)
    ipc_agent.protocol.port_router = port_router
    
    # 3b. Start IPC Agent (start thread)
    ipc_agent.start()
    
    # 3c. Start MQTT Listener
    start_mqtt_listener(device_store, cmd_waiter, port_store, port_router)
    
    # 4. Initialize Virtual Tool Executor
    virtual_tool_executor = VirtualToolExecutor(
        virtual_tool_store, device_store, cmd_waiter, get_mqtt_pub_client, ipc_agent
    )
    
    # 5. Initialize Bridge Server (MCP)
    server = BridgeServer(
        device_store, 
        projection_store, 
        tool_registry, 
        cmd_waiter, 
        port_store, 
        routing_matrix,
        port_router,
        ipc_agent=ipc_agent,
        virtual_tool_store=virtual_tool_store,
        virtual_tool_executor=virtual_tool_executor
    )
    
    # Register existing devices and virtual tools
    server.register_all_announced_devices()
    server.register_virtual_tools()
    
    # 5. Initialize FastAPI App
    app = FastAPI(title="Bridge MCP (SSE + Port Routing API)")
    
    @app.get("/healthz")
    def healthz():
        return {"ok": True, "ts": now_iso(), "service": "mcp-bridge", "port": API_PORT}

    # ========= API Endpoints for Devices =========
    @app.get("/devices")
    def get_devices_api():
        """Get devices list"""
        return device_store.list()

    @app.get("/devices/{device_id}")
    def get_device_api(device_id: str):
        """Get specific device"""
        d = device_store.get(device_id)
        if not d:
            raise HTTPException(HTTPStatus.NOT_FOUND, "device not found")
        return d

    # ========= API Endpoints for Ports =========
    @app.get("/ports")
    def get_ports_api():
        """Get all ports"""
        return {
            "devices": port_store.list_devices(),
            "outports": port_store.get_all_outports(),
            "inports": port_store.get_all_inports()
        }

    @app.get("/ports/{device_id}")
    def get_device_ports_api(device_id: str):
        """Get ports for a specific device"""
        ports = port_store.get_device_ports(device_id)
        if not ports:
            raise HTTPException(HTTPStatus.NOT_FOUND, "device ports not found")
        return ports

    # ========= API Endpoints for Routing Matrix =========
    @app.get("/routing")
    def get_routing_api():
        """Get routing matrix"""
        return routing_matrix.get_matrix_view(port_store)

    @app.get("/routing/connections")
    def get_connections_api():
        """Get all connections"""
        return routing_matrix.get_all_connections()

    @app.post("/routing/connect")
    def connect_api(data: dict):
        """Create a connection"""
        source = data.get("source")
        target = data.get("target")
        transform = data.get("transform", {})
        enabled = data.get("enabled", True)
        description = data.get("description", "")
        
        if not source or not target:
            raise HTTPException(HTTPStatus.BAD_REQUEST, "source and target required")
        
        conn = routing_matrix.connect(source, target, transform, enabled, description)
        return {"ok": True, "connection": conn}

    @app.post("/routing/disconnect")
    def disconnect_api(data: dict):
        """Remove a connection"""
        source = data.get("source")
        target = data.get("target")
        connection_id = data.get("connection_id")
        
        if connection_id:
            success = routing_matrix.disconnect_by_id(connection_id)
        elif source and target:
            success = routing_matrix.disconnect(source, target)
        else:
            raise HTTPException(HTTPStatus.BAD_REQUEST, "source/target or connection_id required")
        
        return {"ok": success}

    @app.put("/routing/connection/{connection_id}")
    def update_connection_api(connection_id: str, data: dict):
        """Update a connection"""
        conn = routing_matrix.update_connection(connection_id, data)
        if not conn:
            raise HTTPException(HTTPStatus.NOT_FOUND, "connection not found")
        return {"ok": True, "connection": conn}

    @app.post("/management/reload")
    def reload_config_api():
        """Reload configuration and refresh tool definitions"""
        try:
            # 1. Reload raw config from disk
            server.projection_store.reload_config()
            virtual_tool_store.reload_config()
            
            # 2. Reset and Re-register tools
            server.reset_tools()
            server.register_all_announced_devices()
            server.register_virtual_tools()
            
            # 3. Notify MCP clients (optional, if supported)
            # server.mcp.send_notification("notifications/tools/list_changed")
            
            log("[API] Hot reload triggered via /management/reload")
            return {"ok": True, "message": "Configuration reloaded and tools refreshed"}
        except Exception as e:
            log(f"[API] Hot reload failed: {e}")
            raise HTTPException(HTTPStatus.INTERNAL_SERVER_ERROR, f"Reload failed: {e}")

    # ========= Virtual Tools API Endpoints =========
    @app.get("/virtual-tools")
    def get_virtual_tools_api():
        """Get all virtual tools"""
        return virtual_tool_store.get_all_virtual_tools()

    @app.get("/virtual-tools/{name}")
    def get_virtual_tool_api(name: str):
        """Get a specific virtual tool"""
        vt = virtual_tool_store.get_virtual_tool(name)
        if not vt:
            raise HTTPException(HTTPStatus.NOT_FOUND, "virtual tool not found")
        return vt

    @app.post("/virtual-tools")
    def create_virtual_tool_api(data: dict):
        """Create a new virtual tool"""
        name = data.get("name")
        if not name:
            raise HTTPException(HTTPStatus.BAD_REQUEST, "name is required")
        
        tool_def = {
            "description": data.get("description", ""),
            "bindings": data.get("bindings", [])
        }
        success = virtual_tool_store.create_virtual_tool(name, tool_def)
        if success:
            # Re-register virtual tools after creation
            server.register_virtual_tools()
            return {"ok": True, "message": f"Virtual tool '{name}' created"}
        raise HTTPException(HTTPStatus.INTERNAL_SERVER_ERROR, "Failed to create virtual tool")

    @app.put("/virtual-tools/{name}")
    def update_virtual_tool_api(name: str, data: dict):
        """Update a virtual tool"""
        tool_def = {
            "description": data.get("description", ""),
            "bindings": data.get("bindings", [])
        }
        success = virtual_tool_store.update_virtual_tool(name, tool_def)
        if success:
            server.register_virtual_tools()
            return {"ok": True, "message": f"Virtual tool '{name}' updated"}
        raise HTTPException(HTTPStatus.NOT_FOUND, "virtual tool not found")

    @app.delete("/virtual-tools/{name}")
    def delete_virtual_tool_api(name: str):
        """Delete a virtual tool"""
        success = virtual_tool_store.delete_virtual_tool(name)
        if success:
            server.reset_tools()
            server.register_all_announced_devices()
            server.register_virtual_tools()
            return {"ok": True, "message": f"Virtual tool '{name}' deleted"}
        raise HTTPException(HTTPStatus.NOT_FOUND, "virtual tool not found")

    @app.get("/routing/stats")
    def get_routing_stats_api():
        """Get routing statistics"""
        return port_router.get_stats()
    
    # Mount MCP SSE endpoint
    try:
        sse_app = server.mcp.sse_app()
        app.mount("/sse", sse_app)
        log("[MCP] SSE endpoint mounted successfully at /sse")
    except Exception as e:
        log(f"[MCP] Failed to mount SSE endpoint: {e}")
        @app.get("/sse")
        def sse_fallback():
            return {"error": "MCP SSE not available", "details": str(e)}

    # 6. Run Server
    ACTIVE_API_PORT = API_PORT
    if os.getenv("AUTO_PORT_FALLBACK", "1") == "1":
        pf = pick_free_port(API_PORT, 10)
        if pf:
            ACTIVE_API_PORT = pf
            
    log(f"[boot] python={sys.version}")
    log(f"[boot] MQTT_HOST={MQTT_HOST} MQTT_PORT={MQTT_PORT} KEEPALIVE={KEEPALIVE} API_PORT={ACTIVE_API_PORT}")
    log(f"[boot] PROJECTION_CONFIG_PATH={PROJECTION_CONFIG_PATH}")
    log(f"[boot] ROUTING_CONFIG_PATH={ROUTING_CONFIG_PATH}")
    log(f"[boot] MCP SSE endpoint: http://0.0.0.0:{ACTIVE_API_PORT}/sse")
    
    uvicorn.run(app, host="0.0.0.0", port=int(ACTIVE_API_PORT), log_level="warning", access_log=False)

if __name__ == "__main__":
    main()
