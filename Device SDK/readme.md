
# Project SABA Hardware SDK

A lightweight SDK for the hardware devices of `project_SABA`.

This SDK is the core framework that enables hardware devices to operate on commands received via the MCP. Based on Wi-Fi and MQTT communication, it executes registered `Tool`s and reports the results in a standardized JSON format.

<br>

## Key Features

* **Easy Initial Setup**: On the first boot, the device automatically enters Access Point (AP) mode. Users can easily connect to it and configure Wi-Fi and MQTT server settings through a web browser. Once configured, the device reboots and connects to the network automatically.

* **Robust Runtime Environment**:
    * **HTTP Server**: Provides a web interface to check the device's status, perform a factory reset, or clear retained MQTT messages.
    * **MQTT Client**: Publishes `announce` (device info), `status`, and `events` (results) topics, while subscribing to the `command` topic to receive remote instructions.

* **Flexible Tool Framework**: Easily add new hardware functionalities (like sensors or actuators) by inheriting the `ITool` interface. The results from any `Tool` are always published as a standard `observation` event, ensuring consistency.

<br>

## Implementing Your Own Tool

Adding new hardware functionality is very straightforward. You only need to modify three files:

1.  **`modules/my_tool.cpp`**
    * Implement the actual logic here (e.g., reading a sensor, controlling a motor).
2.  **`modules/my_tool.h`**
    * Declare your class, ensuring it inherits from the `ITool` interface.
3.  **`modules/tool_register.cpp`**
    * Register your newly created `Tool` with the `ToolRegistry`.

> **Important**: The function signature for `register_tools` within `tool_register.cpp` must be maintained and defined only once within the project.
>
> ```cpp
> void register_tools(ToolRegistry& reg, const ToolConfig& cfg);
> ```

<br>

## Getting Started

### **Development Environment**

* **Framework**: [PlatformIO](https://platformio.org/) (This is the only environment tested.)
* **Hardware**: Any microcontroller board with Wi-Fi capability.

### **Library Dependencies**

Add the following libraries to your `platformio.ini` file:

```ini
lib_deps =
    bblanchon/ArduinoJson@^7.0.4
    knolleary/PubSubClient@^2.8
````

### **How to Use**

1.  **Clone the Repository**: Use this SDK repository as a PlatformIO project.
2.  **Implement a Tool**: Following the examples in the `modules/` folder, write and register your new `Tool`.
3.  **Build & Upload**: Select your target board in PlatformIO, then build and upload the project.
4.  **Initial Setup**:
      * On its first boot, the device will create a Wi-Fi AP named `MCP-SETUP-XXXX`.
      * Connect to this network and use a web browser to enter your Wi-Fi and MQTT credentials.
5.  **Verify Operation**: After setup, the device will automatically reboot into runtime mode. You can confirm it's working by checking the MQTT broker for `announce`, `status`, and `events` topics.

<br>

## Status & Roadmap

  * **Current Version**: `v0.1`
      * [✔] Core framework complete: Provisioning, runtime, MQTT/HTTP, and Tool system.
      * [✔] Basic `Tool` example included.
  * **Future Plans**:
      * [ ] Add more examples for various sensors and actuators.
      * [ ] Introduce security enhancements (e.g., secure provisioning, MQTT over TLS).
      * [ ] Implement the Circuit Breaker pattern for system resilience.
      * [ ] Enhance documentation and user guides.
      * [ ] Focus on stability and code optimization.


<br>

## 📜 License

This project is licensed under the **Apache License 2.0**. Please see the `LICENSE` file for more details.





