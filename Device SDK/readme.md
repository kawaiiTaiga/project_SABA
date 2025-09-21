# Project SABA

<img src="https://github.com/kawaiiTaiga/project_SABA/blob/main/sabachan.png" alt="Project Saba Mascot" width="150">

**Bridging the gap between AI and the physical world.**

LLMs are transformative, but they remain confined to the digital realm. Project SABA is an experimental framework designed to break down this barrier, creating **a plug-and-play ecosystem where anyone can connect LLMs to real-world hardware** through the Model Context Protocol (MCP).

Our vision is simple: just plug in your device, and it becomes instantly accessible to AI assistants. No complex setup, no deep technical knowledge required—just seamless integration between artificial intelligence and physical sensors, actuators, and IoT devices.

---

## The Vision

We're building **the most accessible LLM-hardware ecosystem**—one where connecting a temperature sensor, camera, or smart light to an AI assistant is as simple as plugging in a USB device. Through standardized protocols and intuitive tools, we aim to democratize the creation of intelligent, responsive environments.

**What makes this different:**
- **Zero-configuration hardware integration** via automatic device discovery
- **LLM-native design philosophy** that prioritizes semantic meaning over low-level control  
- **Visual management interface** for non-technical users
- **Standardized communication protocols** that work across different device types

### LLM-Native Hardware Design

Traditional IoT focuses on hardware-centric control: "rotate motor 50 degrees" or "set LED brightness to 75%". These schemas were designed for human developers, not AI reasoning.

Project SABA takes a fundamentally different approach. Instead of exposing hardware primitives, we expose **semantic functions**: "open door", "adjust lighting", "check temperature". This allows LLMs to:

- **Understand intent** rather than memorize commands
- **Combine capabilities** in ways we never programmed
- **Adapt to context** without rigid conditional logic
- **Reason about outcomes** instead of just executing instructions

The key insight: **naming matters more than parameters**. A well-named function like `create_cozy_ambiance()` tells the LLM everything it needs to know, while `set_rgb_values(r, g, b)` requires the LLM to become a lighting engineer.

This semantic abstraction enables true AI-hardware integration, where the artificial intelligence can naturally reason about and orchestrate physical systems.

---

## What's Inside

### 🏗️ **Core Server**
The central hub that orchestrates everything. It includes an integrated MQTT broker and MCP bridge that handles seamless communication between AI assistants and your physical devices. Features include:

- Real-time device discovery and registration
- Web-based projection management for controlling device visibility
- Asset proxying for handling images, files, and sensor data
- Multi-language support and intuitive configuration


### 🔧 **Device SDK**
A lightweight, PlatformIO-based library for microcontrollers (ESP32, etc.) that makes connecting hardware incredibly simple. The SDK provides:

- Automatic Wi-Fi provisioning through setup AP mode
- Built-in tool registry system for defining device capabilities
- Standardized MQTT communication with the Core Server
- Clean abstractions for sensors, actuators, and custom hardware


---

## Key Research Questions

As we develop this framework, we're exploring fundamental questions about LLM-native hardware design:

- **Semantic Hardware Abstraction**: How do we design device interfaces that communicate *purpose* rather than *mechanism*? What makes a function name instantly comprehensible to an LLM?

- **Contextual Device Orchestration**: How can LLMs naturally combine multiple devices to achieve complex goals without explicit programming? What abstractions enable emergent behaviors?

- **Adaptive Hardware Reasoning**: How do we move beyond conditional logic to systems where LLMs can reason about physical constraints, environmental context, and user intent simultaneously?

- **Scalable Semantic Protocols**: What communication patterns allow diverse hardware to present unified, meaningful interfaces that LLMs can intuitively understand and combine?

---

## Getting Started

### Quick Setup
1. **Deploy the Core Server** using Docker Compose
2. **Build your first device** with the Hardware SDK
3. **Configure device visibility** through the web interface
4. **Connect Claude Desktop** to start interacting with your hardware

The entire process takes just minutes, not hours.

### Example Use Cases
- **Smart home automation** with natural language control
- **IoT sensor networks** with AI-driven analysis and responses  
- **Robotics projects** with conversational control interfaces
- **Environmental monitoring** with intelligent alert systems
- **Educational projects** demonstrating AI-hardware integration

---

## Development Status

### **v0.1** (Current Release)
- ✅ Core Server with MQTT broker and MCP bridge
- ✅ Web-based projection management interface
- ✅ Hardware SDK with automatic provisioning
- ✅ Tool registry system and standardized protocols
- ✅ Asset proxying and real-time device discovery

### **Upcoming Features**
- 🔄 Enhanced security with TLS/SSL support
- 🔄 Advanced event routing and filtering
- 🔄 Plugin system for custom integrations
- 🔄 Mobile companion app for device management
- 🔄 Cloud deployment options and scaling guides

---

## Philosophy

We believe the future of AI lies not just in better models, but in better **integration** with the physical world. Project SABA represents our attempt to make that integration as natural and accessible as possible.

Every design decision is guided by a simple principle: **if you can plug it in, AI should be able to use it.** This means prioritizing ease of use, clear abstractions, and reliable protocols over complex configurations or specialized knowledge requirements.

---

## Community & Contribution

This is currently a solo research project, but we welcome collaborators, feedback, and contributions from anyone interested in AI-hardware integration.

**Ways to get involved:**
- Test the framework with your own hardware projects
- Share feedback on the developer experience
- Contribute to documentation and examples
- Propose new features or architectural improvements

### Contact
- **Email**: `gyeongmingim478@gmail.com`
- **Instagram**: `gyeongmin116`

---

## License

This project is licensed under the **Apache License 2.0**. See the [LICENSE](./LICENSE) file for complete details.

---



