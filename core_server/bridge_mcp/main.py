import os
import sys
import socket
import uvicorn
from fastapi import FastAPI, HTTPException
from http import HTTPStatus

from .config import PROJECTION_CONFIG_PATH, ROUTING_CONFIG_PATH, API_PORT, MQTT_HOST, MQTT_PORT, KEEPALIVE
from .utils import log, now_iso
from .tool_projection import ToolProjectionStore
from .tool_registry import DynamicToolRegistry
from .device_store import DeviceStore
from .command import CommandWaiter
from .mqtt import start_mqtt_listener, publish_to_inport
from .server import BridgeServer
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
    
    # 2. Initialize Port Router
    port_router = PortRouter(routing_matrix, publish_to_inport)
    
    # 3. Start MQTT Listener
    start_mqtt_listener(device_store, cmd_waiter, port_store, port_router)
    
    # 4. Initialize Bridge Server (MCP)
    server = BridgeServer(
        device_store, 
        projection_store, 
        tool_registry, 
        cmd_waiter, 
        port_store, 
        routing_matrix,
        port_router
    )
    
    # Register existing devices
    server.register_all_announced_devices()
    
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
