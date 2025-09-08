# core_server

**What is this?**  
A single Dockerized **core server** that bundles:
- an MQTT **broker** (Mosquitto) and
- the **MCP bridge** (HTTP/SSE server exposing MCP resources/tools, proxying device assets)

It’s the central piece that sits between your LLM and your sensors/actuators.

- MQTT topics (devices ↔ core): `mcp/dev/<device_id>/{announce|status|events|cmd}`
- HTTP API (LLM/operator ↔ core): health, device list, asset proxy
- MCP endpoint (for Claude Desktop via `mcp-remote`): **SSE at `/sse`**

---

## Run

### Prerequisites
- Docker & Docker Compose

### Start
```bash
docker compose up -d --build
```

### Verify
```bash
# Core alive
curl http://localhost:8083/healthz

# Known devices (empty until your device announces)
curl http://localhost:8083/devices

# Container logs
docker logs -f mcp-broker   # mosquitto
docker logs -f mcp-bridge   # MCP bridge
```

> Tip: If your device already runs, hit its `GET /reannounce` (if supported) to republish retained announce.

### Default ports
- MQTT broker: `1883` (host → container)
- Core HTTP/MCP: `8083` (host → container)

Environment variables (optional):
- `MQTT_HOST` (bridge→broker; default: `mcp-broker` inside compose network)
- `MQTT_PORT` (default: `1883`)
- `API_PORT`  (default: `8083`)

---

## Connect to Claude Desktop

Claude Desktop talks MCP over **stdio**, so we use the official **`mcp-remote`** shim to connect stdio ⇄ SSE.

### Option A (recommended): use `npx` (Node.js installed)
**Windows example (absolute path avoids PATH issues):**
```json
{
  "mcpServers": {
    "saba-core": {
      "command": "C:\\Program Files\\nodejs\\npx.cmd",
      "args": ["-y", "@modelcontextprotocol/cli", "http://localhost:8083/sse"]
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
      "args": ["-y", "@modelcontextprotocol/cli", "http://localhost:8083/sse"]
    }
  }
}
```

> The base URL is **`http://localhost:8083/sse`**.  
> `mcp-remote` will use `GET /sse` (event stream) and `POST /sse/messages` under the hood.

### Option B: global install (no npx)
```bash
npm i -g @modelcontextprotocol/cli
```
```json
{
  "mcpServers": {
    "saba-core": {
      "command": "mcp-remote",
      "args": ["http://localhost:8083/sse"]
    }
  }
}
```

---

## Quick usage (sanity checks)

1) **Device shows up**  
   Your device publishes `announce`/`status` to `mcp/dev/<device_id>/...`.
   ```bash
   curl http://localhost:8083/devices
   ```

2) **Tool call (from Claude)**  
   In a Claude chat with `saba-core` enabled, ask it to call:
   - `invoke(device_id="<your_id>", tool="capture_image", args={"quality":"mid","flash":false})`
   - Or the convenience tool `capture_image(...)`

3) **View asset**  
   The tool result includes `result.assets[i].proxy_url`. Open it to see the image proxied by the core server.

---

## Troubleshooting

- **Claude says “transport closed”**  
  Make sure `http://localhost:8083/sse` returns **200** with `Content-Type: text/event-stream` and the connection stays open:
  ```bash
  curl -i http://localhost:8083/sse
  ```
- **No devices in `/devices`**  
  Check broker logs (`docker logs -f mcp-broker`), and verify your device points to the host’s LAN IP: `1883`.  
  Trigger a re-announce on the device if possible.
- **Windows can’t find `npx`**  
  Use the absolute path to `npx.cmd` as shown above, or install `@modelcontextprotocol/cli` globally and use `mcp-remote`.

---

That’s it. Start the core, point your device at MQTT, and connect Claude to `/sse`.
