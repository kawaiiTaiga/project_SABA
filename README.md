# Project SABA
> 📄 [(Korean)](README.ko.md)

An open-source framework for connecting LLM's peripherals.

### Demo Video

[![Project SABA Demo](https://img.youtube.com/vi/rwOtaaQY_-Q/0.jpg)](https://www.youtube.com/watch?v=rwOtaaQY_-Q)

---

### The Problem

<img src="https://github.com/kawaiiTaiga/project_SABA/blob/main/images/llm_tools.PNG" alt="Current Interaction" width="1000">

LLMs can use digital tools (code interpreters, search engines, databases) via the Model Context Protocol (MCP).
But connecting them to physical hardware—cameras, motors, sensors—is complicated.

---

### The Solution

<img src="https://github.com/kawaiiTaiga/project_SABA/blob/main/images/llm_peripherals.PNG" alt="SABA Interaction" width="1000">

SABA provides a simple way for LLMs to control physical devices.
Define your hardware's purpose in natural language, and the LLM figures out the rest.

---

### Why SABA?

**Plug & Play.** Configure Wi-Fi once, and your device is ready.
**No schemas.** Just describe what your device does in natural language.
**Intent-based.** Instead of "rotate motor 50°," you define "open_living_room_curtain."
**LLM-native.** Works seamlessly with Claude, GPT, and other LLMs via MCP.

---

## How It Works

#### 1. Hardware as Tools
Your devices become tools that LLMs can autonomously use during conversations—just like they use code interpreters or search engines.

#### 2. Simple Setup
Connect your device, configure Wi-Fi/MQTT once, and it's ready. The LLM can immediately understand and control it through SABA's core server.

#### 3. Semantic Function Design
A motor can do thousands of things. What matters is the intent:
- `water_plant` (not "activate pump for 3 seconds")
- `open_curtain` (not "rotate motor 90 degrees")
- `press_coffee_button` (not "extend actuator 2cm")

The LLM understands the purpose from the name. No complex configurations needed.

#### 4. Works with Any Hardware
From simple motors and sensors to cameras and complex actuators. ESP32-based for affordability, with plans to support more platforms.

---

## Current Status

**Version 0** A

**Version 0.1** - Proof of concept

What works:
- ✅ ESP32 device SDK with automatic provisioning
- ✅ MCP bridge server for Claude Desktop integration
- ✅ Camera, motor, sensor, and LED control examples
- ✅ Web-based projection manager

What's next:
- Security (TLS/encryption)
- Performance optimization
- Better documentation and tutorials
- Event-driven architecture for proactive agents
- More example projects

---

## Get Started

**Hardware:** [Device SDK](https://github.com/kawaiiTaiga/project_SABA/tree/main/Device%20SDK)  
**Server:** [Core Server](https://github.com/kawaiiTaiga/project_SABA/tree/main/core_server)

---

## About

Any help, ideas, and collaborations are welcome.

Contact me
- **Email**: gyeongmingim478@gmail.com
- **Instagram**: gyeongmin116

---

### License
Apache License 2.0 - See LICENSE file for details.
