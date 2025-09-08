# MCP-BRIDGE

A lightweight MQTT ↔ MCP Bridge for Project Saba. This gateway server connects LLMs with real-world sensors and actuators.

---

## Overview

MCP-BRIDGE acts as a translator between two worlds:

-   **MQTT Broker**: It communicates with IoT devices by collecting events and routing commands.
-   **MCP Server**: It exposes a standardized interface for LLMs (like Claude Desktop) to interact with the physical world.
-   **HTTP API**: It provides a FastAPI-based API for health checks, status monitoring, and serving assets.

## Architecture

```mermaid
flowchart LR
  subgraph LLM_Side[LLM Side]
    LLM[LLM Client<br/>(e.g., Claude Desktop)]
  end

  subgraph Bridge[MCP-BRIDGE (This Server)]
    MCP[MCP Server<br/>(Tools & Resources)]
    API[HTTP API<br/>(/healthz, /assets)]
  end

  subgraph Broker[MQTT Broker]
    MQ[(mosquitto)]
  end

  subgraph Devices[Physical Devices]
    D1[ESP32-CAM]
    D2[Sensor/Actuator]
  end

  LLM <--> MCP
  MCP <--> API
  MCP <--> MQ
  MQ <--> D1
  MQ <--> D2
  API -- proxy_url for images/assets --> LLM
LLM ↔ MCP-BRIDGE: Communication follows the MCP standard for calling tools and looking up resources.

MCP-BRIDGE ↔ MQTT Broker: The bridge and devices exchange messages on announce, status, events, and cmd topics.

HTTP API: Large payloads like images are proxied through a simple HTTP URL to be accessible by the LLM.

Core Features
Device Registry: Collects announce/status messages to cache a list of available devices and their online status.

Command Routing: Matches an LLM's tool call to an MQTT command and pairs the eventual response using a request_id.

Asset Proxy: Proxies device-generated assets (e.g., camera images) over HTTP at /assets/{request_id}.

MCP Server: Exposes standardized tools and resources for any MCP-compatible client.

Quick Start
Prerequisites
Python 3.9+ (or Docker)

A running Mosquitto MQTT Broker (listening on port 1883)

Running Locally
Start the MQTT Broker (if you don't have one running):

Bash

docker run -it --rm -p 1883:1883 eclipse-mosquitto:2
Start the Bridge Server:

Bash

pip install -r requirements.txt
python bridge_mcp.py
Check Health Status:

Bash

curl http://localhost:8080/healthz
Note: If port 8080 is in use, the bridge will automatically attempt to use the next available port (8081, 8082, etc.).

API Endpoints
GET /healthz: Returns the server's health status.

GET /devices: Returns a list of all registered devices.

GET /devices/{device_id}: Returns the details for a single device.

GET /assets/{request_id}: Proxies the first (or only) asset from a device's response.

GET /assets/{request_id}/{index}: Proxies an asset by its specific index.

MCP Integration
An LLM can use the following tools and resources provided by this server.

Tools
invoke(device_id, tool, args): A general-purpose invoker for any device tool.

capture_image(device_id, quality, flash): An example tool for capturing an image from a camera device.

Resources
bridge://devices: A list of all available devices.

bridge://device/<id>: Detailed information about a specific device.

bridge://asset/<request_id>: The result of an event, including any associated assets.

Usage Scenario
An ESP32-CAM connects to the MQTT broker and publishes an announce message.

MCP-BRIDGE receives the message and registers the camera in its device list.

The LLM calls the capture_image tool (e.g., with quality=mid, flash=false).

The bridge publishes a command to the appropriate MQTT cmd topic.

The ESP32-CAM captures an image and publishes the result to the events topic.

The bridge receives the event, matches it to the original request, and returns a response to the LLM that includes a proxy_url for the captured image.

Roadmap
[ ] Dynamic Tool Discovery: Automatically expose device tools to the LLM based on announce messages.

[ ] Persistence: Save device and event history to a database.

[ ] Security: Implement robust authentication and ACL for MQTT and MCP.

[ ] Dashboard: A web UI for monitoring, orchestration, and workflow management.

Relation to Project Saba
MCP-BRIDGE is a core component of Project Saba's Core Server, acting as the primary gateway that connects LLMs to physical sensors and actuators.
