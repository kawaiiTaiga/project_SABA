# Project Saba - MCP Core Server

**What is this?**  
A Dockerized **IoT-to-MCP bridge system** that connects your physical devices to AI assistants like Claude Desktop through the Model Context Protocol (MCP).

The system consists of:
- **MQTT broker** (Mosquitto) for device communication
- **MCP bridge** (HTTP/SSE server) exposing MCP resources/tools and proxying device assets
- **Projection Manager** (web interface) for configuring which device tools are exposed to MCP clients

It's the central hub that sits between your LLM and your sensors/actuators, with intelligent tool projection and filtering capabilities.

**Communication flows:**
- MQTT topics (devices ↔ core): `mcp/dev/<device_id>/{announce|status|events|cmd}`
- HTTP API (LLM/operator ↔ core): health, device list, asset proxy
- MCP endpoint (for Claude Desktop via `mcp-remote`): **SSE at `/sse`**
- Web Management (projection control): **http://localhost:8084**

---

## Architecture

```
┌─────────────────┐    MQTT     ┌─────────────────┐    MCP/SSE    ┌─────────────────┐
│   IoT Devices   │ ◄─────────► │   Core Server   │ ◄───────────► │  Claude Desktop │
│  (ESP32, etc.)  │   1883      │ (Bridge+Broker) │     8083      │   (mcp-remote)  │
└─────────────────┘             └─────────────────┘               └─────────────────┘
                                         │
                                    HTTP │ 8084
                                         ▼
                                ┌─────────────────┐
                                │ Projection Mgr  │
                                │  (Web Interface)│
                                └─────────────────┘
```

## Key Features

- **Tool Projection**: Selectively expose device capabilities to MCP clients
- **Dynamic Tool Registration**: Automatically register device tools with proper MCP schemas
- **Asset Proxying**: Handle images and files from devices through HTTP proxy
- **Web Management**: User-friendly interface for configuring device and tool visibility
- **Real-time Configuration**: Update tool projections without restarting services
- **Multi-language Support**: Web interface supports Korean/English

---

## Run

### Prerequisites
- Docker & Docker Compose

### Start
```bash
docker compose up -d --build
```

This will start:
- **mcp-broker** (port 1883): MQTT broker for device communication
- **mcp-bridge** (port 8083): MCP bridge server with SSE endpoint
- **mcp-projection-manager** (port 8084): Web management interface

### Verify
```bash
# Core alive
curl http://localhost:8083/healthz

# Known devices (empty until your device announces)
curl http://localhost:8083/devices

# Projection management interface
open http://localhost:8084

# Container logs
docker logs -f mcp-broker              # mosquitto
docker logs -f mcp-bridge              # MCP bridge
docker logs -f mcp-projection-manager  # web interface
```

> **Tip**: If your device is already running, hit its `GET /reannounce` endpoint (if supported) to republish retained announce messages.

### Default ports
- **MQTT broker**: `1883` (device communication)
- **MCP bridge**: `8083` (Claude Desktop connection)  
- **Projection Manager**: `8084` (web management interface)

### Environment variables (optional):
- `MQTT_HOST` (default: `mcp-broker`)
- `MQTT_PORT` (default: `1883`)
- `API_PORT` (bridge: `8083`, manager: `8084`)
- `PROJECTION_CONFIG_PATH` (default: `./config/projection_config.json`)

---

## Tool Projection Management

### Web Interface (Recommended)
1. Open **http://localhost:8084** in your browser
2. **Project Saba MCP Manager** provides:
   - Real-time device status monitoring
   - Enable/disable devices and individual tools
   - Set custom aliases for devices and tools
   - Override tool descriptions
   - Language switching (Korean/English)

### Important: Tool Naming Rules
When setting tool aliases, follow MCP naming conventions:
- **Allowed**: Letters (a-z, A-Z), numbers (0-9), underscore (_), hyphen (-)
- **Not allowed**: Spaces, special characters, non-ASCII characters (including Korean/Chinese)
- **Examples**: 
  - ✅ `take_photo`, `camera-shot`, `sensor_read`
  - ❌ `take photo`, `사진촬영`, `capture(image)`

### Configuration File
Projection settings are stored in `./config/projection_config.json`:
```json
{
  "devices": {
    "esp32-cam-01": {
      "enabled": true,
      "device_alias": "living_room_camera",
      "tools": {
        "capture_image": {
          "enabled": true,
          "alias": "take_photo",
          "description": "Take a photo with the living room camera"
        },
        "start_recording": {
          "enabled": false,
          "alias": null,
          "description": null
        }
      }
    }
  },
  "global": {
    "auto_enable_new_devices": true,
    "auto_enable_new_tools": true
  }
}
```

---

## Connect to Claude Desktop

Claude Desktop uses MCP over **stdio**, so we use the official **`mcp-remote`** shim to bridge stdio ↔ SSE.

### Option A (recommended): use `npx` 
**Windows example:**
```json
{
  "mcpServers": {
    "saba-core": {
      "command": "C:\\Program Files\\nodejs\\npx.cmd",
      "args": ["-y", "@modelcontextprotocol/cli", "http://localhost:8083/sse/sse"]
    }
  }
}
```

**macOS/Linux example:**
```json
{
  "mcpServers": {
    "saba-core": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/cli", "http://localhost:8083/sse/sse"]
    }
  }
}
```

### Option B: global install
```bash
npm i -g @modelcontextprotocol/cli
```
```json
{
  "mcpServers": {
    "saba-core": {
      "command": "mcp-remote",
      "args": ["http://localhost:8083/sse/sse"]
    }
  }
}
```

> **Base URL**: `http://localhost:8083/sse`  
> `mcp-remote` automatically handles `GET /sse` (event stream) and `POST /sse/messages`

---

## Quick Usage

### 1. Device Registration
When your IoT device starts, it should publish an announce message:
```json
// Topic: mcp/dev/esp32-cam-01/announce
{
  "name": "ESP32 Camera - Living Room",
  "version": "1.0.0",
  "tools": [
    {
      "name": "capture_image",
      "description": "Capture an image with configurable quality and flash",
      "parameters": {
        "type": "object",
        "properties": {
          "quality": {"type": "string", "enum": ["low", "mid", "high"]},
          "flash": {"type": "boolean"}
        }
      }
    }
  ]
}
```

### 2. Configure Tool Projection
1. Open http://localhost:8084
2. Find your device in the list
3. Enable/disable tools as needed
4. Set user-friendly aliases (following naming rules)
5. Save configuration

### 3. Test from Claude Desktop
In a Claude chat with `saba-core` enabled:
- **Generic call**: `invoke(device_id="esp32-cam-01", tool="capture_image", args={"quality":"high","flash":true})`
- **Projected tool**: `take_photo_esp32_cam_01(quality="high", flash=true)` (if you set alias to "take_photo")

### 4. View Assets
Device responses with images/files include `proxy_url` fields:
```json
{
  "result": {
    "text": "Image captured successfully",
    "assets": [
      {
        "kind": "image",
        "mime": "image/jpeg",
        "url": "http://device-ip/image.jpg",
        "proxy_url": "http://localhost:8083/assets/req_abc123/0"
      }
    ]
  }
}
```

---

## Troubleshooting

### Claude Desktop Connection Issues
- **"Transport closed" error**:
  ```bash
  curl -i http://localhost:8083/sse
  # Should return 200 with Content-Type: text/event-stream
  ```
- **Tool naming errors**: Check projection manager for invalid aliases (spaces, special chars, etc.)
- **Windows npx issues**: Use absolute path to `npx.cmd` as shown above

### Device Communication Issues  
- **No devices in `/devices`**: 
  - Check broker logs: `docker logs -f mcp-broker`
  - Verify device MQTT settings point to host LAN IP:1883
  - Trigger device re-announce if supported
- **Tools not appearing**: Check projection manager - tools might be disabled

### Configuration Issues
- **Projection changes not applying**: Use "Restart Bridge" button in web interface
- **Config file corruption**: Delete `./config/projection_config.json` to regenerate defaults
- **Port conflicts**: Modify docker-compose.yml ports as needed

### Performance Issues
- **Slow asset loading**: Assets are proxied through the bridge - check device HTTP performance
- **Memory usage**: Restart containers periodically if handling many large assets

---

## Development

### Adding New Device Types
1. Implement MCP-compatible MQTT protocol in your device
2. Announce tools with proper JSON Schema parameters
3. Handle commands via `mcp/dev/<device_id>/cmd` topic
4. Return results with assets to `mcp/dev/<device_id>/events`

### Extending Projection Features
- Modify `projection_manager.py` for new UI features
- Update `bridge_mcp.py` for new projection logic
- Configuration schema is in `ProjectionConfigManager` class

### Custom Tool Schemas
Ensure your device tools use proper JSON Schema:
```json
{
  "type": "object",
  "properties": {
    "param_name": {
      "type": "string|number|boolean|array|object",
      "enum": ["value1", "value2"],  // optional
      "description": "Parameter description"
    }
  },
  "required": ["required_param"]
}
```

---

That's it! Start the core, connect your devices via MQTT, configure projections via the web interface, and connect Claude Desktop to the SSE endpoint.
