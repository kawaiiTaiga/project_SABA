# Project SABA - Your First LLM Peripheral
> 📄 [이 문서를 한국어로 보기 (Read this document in Korean)](README.ko.md)
---

### What now?

<img src="https://github.com/kawaiiTaiga/project_SABA/blob/main/IMAGE1.PNG" alt="Current Interaction" width="1000">

Until now, **humans** have used peripherals like keyboards to interact with **LLMs**.
In turn, **LLMs** have used digital tools like code interpreters, search engines, and databases via the Model Context Protocol (MCP).

---

### What we do?

<img src="https://github.com/kawaiiTaiga/project_SABA/blob/main/IMAGE2.PNG" alt="SABA Interaction" width="1000">

Project SABA is a new kind of **peripheral for the LLM itself**.
Our goal is to provide the tools that allow an **LLM to directly interact with the real world** and **'use'** the physical environment.

---

### What for?

LLMs are the most powerful, convenient, and easy-to-learn tools in history. Project SABA aims for the **'democratization of physical AI agents,'** empowering everyone to harness the power of this technology in the real world. Our goal is to empower anyone to **bring intelligence to their own physical spaces.**

---

## Core Principles

#### 1. Work as a Tool
SABA's peripherals are not just passive sensors that feed information to an LLM. They are active **'Tools'** that the LLM autonomously uses during its reasoning process. It functions just like using a software tool via MCP—perhaps even more easily.

#### 2. Plug & Play
The complex and cumbersome process of connecting cameras or sensors to an LLM is a thing of the past. SABA is designed to be as simple as **'Plug & Play,'** much like connecting a mouse to a computer. (Currently, it requires a core server installation and a one-time device provisioning.) Once connected, the LLM can instantly control the device through **SABA's CORE SERVER**.

#### 3. No Schema
Existing smart home ecosystems were trapped by predefined standards (Schemas). How many potential features were blocked in the name of standardization? The only requirement for SABA is: **'Can it be described in natural language?'** Through an **LLM-Native** design, you can implement limitless functionalities beyond any fixed schema.

#### 4. Intent over Function
A single motor can perform tens of thousands of tasks. What's crucial for an LLM is not the function, like 'rotate motor,' but the **'Intent,'** such as 'open the window' or 'press the washing machine button.' SABA's layered architecture allows you to easily redefine a component's role, helping the LLM better understand the context and execute tasks accurately. **This also means that the complexity of the device is completely irrelevant to the LLM.**

#### 5. Scalability & Versatility
SABA's approach has the potential to integrate any device, from simple motors and sensors to complex robotic arms with embedded intelligence. This allows for customized solutions perfectly tailored to a user's specific context, whether it's a smart home, smart farm, factory automation, or restaurant management.

---

## Limitations & Future

Project SABA is currently at the proof-of-concept stage. To achieve a higher level of completeness, we are developing it based on the following roadmap:

1.  **Performance Optimization**
    The current software on the embedded devices is focused on functionality, requiring further optimization for performance and resource usage.

2.  **Security Enhancement**
    Security is critical for a system that directly controls the physical world. The current version does not yet include essential security features like communication encryption or device authentication, making it a top priority.

3.  **User Experience (UX) Innovation**
    To achieve SABA's core vision of 'democratization,' an intuitive UX is essential. We plan to improve the current tech-centric setup process to create a system where non-experts can intuitively build their own agents.

4.  **Event-Driven Architecture**
    A true physical agent must do more than just execute commands; it must react proactively to changes in its environment. We plan to introduce an event-driven architecture where real-world 'events' (e.g., a sensor detection) can initiate interaction with the LLM. SABA aims to democratize the process of designing this agent logic as well.

5.  **Physical Tool Usage Research**
    Beyond simply connecting physical tools, we will research and present methodologies for how an LLM can utilize each tool to its maximum potential. This includes exploring effective prompting and methods for clearly defining a tool's capabilities and limitations.

6.  **UX/DX for LLMs**
    A key philosophy of SABA is to consider not only 'UX for Humans' but also 'UX for LLMs.' We plan to systematically document and evolve the principles for designing and naming functions so that an LLM can clearly understand and use a tool's intent without confusion.

---

## About me

Project SABA is currently a one-person side project. Any kind of help is needed for this project to grow.
I welcome any ideas, technical questions, or collaboration proposals about Project Saba. Please feel free to reach out anytime.

- **Email**: gyeongmingim478@gmail.com
- **Instagram**: gyeongmin116

---
### Version History
**v0.0**
* A

**v0.1 (Current)**
* This is the initial version with the project's foundational structure.
* It focuses on the core functionalities of the Core Server and Device SDK.
---
### License
This project is licensed under the Apache License 2.0. See the LICENSE file for more details.
