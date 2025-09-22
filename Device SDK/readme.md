# Project SABA - Hardware SDK

**Build LLM-native IoT devices with semantic function design.**

The Hardware SDK is a lightweight framework for creating intelligent devices that speak naturally to AI assistants. Instead of exposing hardware primitives like "rotate motor X degrees," you define semantic functions like "open door" or "adjust lighting"—letting LLMs understand *what* your device does, not *how* it works.

This SDK handles all the complexity of network provisioning, MQTT communication, and protocol compliance, so you can focus on building meaningful device capabilities that AI can naturally understand and orchestrate.

---

## Design Philosophy

Traditional IoT development forces you to think like hardware: define pins, set parameters, manage protocols. The SABA Hardware SDK flips this paradigm—you think like an AI assistant would.

**Instead of this:**
```cpp
motor.rotate(50, CLOCKWISE, 100);  // How many degrees for a door?
led.setRGB(255, 200, 150);         // What LED is this for?
sensor.readValue();                // Value for what purpose?
```

**You define this:**
```cpp
openLivingRoomDoor();             // Clear location and intent
setCinematicLighting(255, 200, 150);           // Specific use case context
checkRoomComfort();               // Meaningful purpose
```

The key insight: **function names are the interface**. When an LLM sees `createWarmAmbiance()`, it immediately understands the capability. When it sees `setRGB(r, g, b)`, it has to become a lighting engineer.

---

## Key Features

- **Automatic Network Provisioning**: First boot creates a setup AP—users configure Wi-Fi and MQTT through any web browser
- **Semantic Tool Framework**: Define device capabilities as meaningful functions using the `ITool` interface
- **Zero-Configuration Discovery**: Devices automatically announce their capabilities to the SABA Core Server
- **Robust Runtime Environment**: Built-in HTTP server for status monitoring and MQTT client for reliable communication
- **Standardized Results**: All tool outputs follow consistent JSON schemas that LLMs can easily interpret

---

## Quick Start

### Development Environment
- **Framework**: [PlatformIO](https://platformio.org/) (only tested environment)
- **Hardware**: Any Wi-Fi capable microcontroller (ESP32 recommended)
- **Dependencies**: Minimal—just ArduinoJson and PubSubClient

### Setup
1. **Add Dependencies** to your `platformio.ini`:
   ```ini
   lib_deps =
       bblanchon/ArduinoJson@^7.0.4
       knolleary/PubSubClient@^2.8
   ```

2. **Clone the SDK** as your PlatformIO project base

3. **Define Your Device Capabilities** by implementing the `ITool` interface

---

## Building Your First Tool

Creating new device functionality requires modifying just three files:

### 1. Implement Logic (`modules/my_tool.cpp`)
```cpp
#include "my_tool.h"

JsonDocument MyTool::getSchema() {
    JsonDocument schema;
    schema["type"] = "object";
    schema["properties"]["intensity"]["type"] = "string";
    schema["properties"]["intensity"]["enum"] = JsonArray({"gentle", "normal", "bright"});
    return schema;
}

JsonDocument MyTool::execute(const JsonDocument& args) {
    String intensity = args["intensity"] | "normal";
    
    // Your hardware logic here
    if (intensity == "gentle") {
        analogWrite(LED_PIN, 64);
    } else if (intensity == "bright") {
        analogWrite(LED_PIN, 255);
    } else {
        analogWrite(LED_PIN, 128);
    }
    
    JsonDocument result;
    result["text"] = "Lighting adjusted to " + intensity + " intensity";
    return result;
}
```

### 2. Declare Interface (`modules/my_tool.h`)
```cpp
#pragma once
#include "ITool.h"

class MyTool : public ITool {
public:
    JsonDocument getSchema() override;
    JsonDocument execute(const JsonDocument& args) override;
};
```

### 3. Register Tool (`modules/tool_register.cpp`)
```cpp
#include "tool_register.h"
#include "my_tool.h"

void register_tools(ToolRegistry& reg, const ToolConfig& cfg) {
    reg.addTool("adjust_lighting", std::make_unique<MyTool>());
    // Add other tools here...
}
```

**Critical**: The `register_tools` function signature must be maintained exactly as shown and defined only once per project.

---

## Deployment & Configuration

### Initial Setup
1. **Build and Upload** your project to the microcontroller
2. **Connect to Setup Network**: Device creates `MCP-SETUP-XXXX` Wi-Fi AP on first boot
3. **Configure via Browser**: Connect to the AP and enter your Wi-Fi credentials and MQTT server details
4. **Automatic Operation**: Device reboots and connects to your network, announcing capabilities

### Runtime Management
Once operational, your device provides:
- **Status Web Interface**: Check device health and configuration
- **MQTT Communication**: Automatic announce/status publishing and command handling
- **Factory Reset**: Web-based reset option for reconfiguration
- **Retained Message Cleanup**: Clear persistent MQTT messages when needed

---

## Design Guidelines

### Semantic Function Naming
- **Include location context**: `openLivingRoomDoor()` vs `openDoor()`
- **Specify use case**: `setCinematicLighting()` vs `setWarmLight()`
- **Think user intent**: `checkRoomComfort()` vs `readTemperature()`
- **Embed purpose**: `prepareMovieNight()` vs `dimLights()`

When a user says "open the living room door," the LLM should immediately recognize `openLivingRoomDoor()`. When they say "set up for filming," it should find `setCinematicLighting()`. The function name should be the natural bridge between human language and device capability.

### Result Structure
Always return meaningful feedback:
```cpp
JsonDocument result;
result["text"] = "Living room door opened successfully";
result["assets"] = JsonArray();  // For images, files, etc.
return result;
```

---

## Integration with SABA Ecosystem

### Automatic Discovery
Your device automatically integrates with the SABA Core Server:
1. **Announces capabilities** via MQTT on startup
2. **Appears in Projection Manager** for configuration
3. **Becomes available** to Claude Desktop and other MCP clients

### Tool Projection
The Core Server's Projection Manager lets users:
- Enable/disable specific device functions
- Set user-friendly aliases for tools
- Control which capabilities are exposed to AI assistants
- Override descriptions for better LLM understanding

---

## Examples & Templates

The SDK includes example implementations for common device types:
- **Sensor Devices**: Temperature, humidity, motion detection
- **Actuator Devices**: Motors, servos, relays
- **Camera Devices**: Image capture with configurable parameters
- **Composite Devices**: Multi-function devices combining sensors and actuators

Each example demonstrates semantic function design and best practices for LLM-native hardware development.

---

## Development Status

### Current Version: v0.1
- Core framework with provisioning and runtime systems
- Tool registry and MQTT communication
- Basic examples and templates
- Web-based configuration interface

### Planned Enhancements
- Enhanced security with TLS/SSL support
- Circuit breaker patterns for resilience
- Extended sensor/actuator library
- Advanced power management features
- Comprehensive documentation and tutorials

---

## Philosophy: Beyond Traditional IoT

This SDK embodies a fundamental shift in how we think about smart devices. Instead of building remote controls for hardware, we're building semantic interfaces for artificial intelligence.

Every design decision prioritizes **AI comprehension** over human convenience. This means clear function names, meaningful parameters, and consistent result formats that let LLMs naturally reason about and combine device capabilities.

The result is hardware that doesn't just connect to the internet—it connects to intelligence.

---

## License

Licensed under the **Apache License 2.0**. See the [LICENSE](../LICENSE) file for complete details.

---

*Build hardware that speaks AI.*

