# Project Saba
<img src="https://github.com/kawaiiTaiga/project_SABA/blob/main/sabachan.png" alt="Project Saba Mascot" width="150">

LLMs are powerful, but they're still trapped in software. We wanted to make the process of connecting LLMs to actual hardware simpler and more open.

Project SABA is an experimental framework that lets you plug-and-play real-world sensors and actuators into an LLM via the Model Context Protocol (MCP).

Through this work, we aim to create **the most convenient intelligence**, where technology naturally blends into the background.

---

### What's Inside

* **Core Server**: The integrated server (MQTT broker, MCP bridge) that handles communication between the LLM and devices.
* **Device SDK**: A client library for microcontrollers (e.g., ESP32) to easily connect and communicate with the Core Server.

---

### Key Questions We're Exploring

We are trying to answer the following technical questions as we build this tool:

* How can we move beyond the request-response model and build an event-driven structure where the LLM can react to events?
* What is the best way to connect various hardware in a consistent and efficient manner?
* What prompt and MCP structures are needed for an LLM to best control physical devices?

---

### Version History
**v0.0**
* A

**v0.1 (Current)**
* This is the initial version with the project's foundational structure.
* It focuses on the core functionalities of the Core Server and Device SDK.

---

### Contact

This is currently a solo project.
I welcome any ideas, technical questions, or collaboration proposals about Project Saba. Please feel free to reach out anytime.

* **Email**: `gyeongmingim478@gmail.com`
* **Instagram** : 'gyeongmin116'
---
### License
This project is licensed under the Apache License 2.0. See the LICENSE file for more details.
