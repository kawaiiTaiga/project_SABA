# 📸 Tool Example: ESP32-CAM (AI-Thinker)

This is a tool implementation example for the `MCP-Lite Hardware SDK`. It provides the functionality to capture and remotely control images using the popular and affordable **ESP32-CAM (AI-Thinker model)** board.

This code has been fully tested by uploading and running it on an actual ESP32-CAM board using the PlatformIO environment.

<br>

## 💻 Requirements

  * **Required Hardware**: **ESP32-CAM (AI-Thinker model)**
  * **Uploader**: An external FTDI (USB-to-Serial) programmer is required to upload code, as the ESP32-CAM does not have a built-in USB port.

<br>

## ✨ Key Features

  * **Image Capture**: Takes a picture via a remote command.
  * **Quality Control**: Adjusts image quality (resolution, JPEG compression) in three levels: `low`, `mid`, `high`.
  * **Flash Control**: Toggles the onboard LED flash `on`/`off`.
  * **HTTP Server**: Serves the last captured image via the `/last.jpg` endpoint on the board's web server.

<br>

## 🛠️ How to Use

1.  Place these files (`camera_ai_thinker.h`, `camera_ai_thinker.cpp`) into the `modules/` directory of your `MCP-Lite` project.
2.  In the `modules/tool_register.cpp` file, create and register the `CameraAiThinker` tool as shown below. The number `4` corresponds to the GPIO pin for the flash LED on the AI-Thinker board.
    ```cpp
    #include "modules/camera_ai_thinker.h"

    void register_tools(ToolRegistry& reg, const ToolConfig& cfg){
      // Create a camera tool instance using GPIO 4 for the flash pin
      auto* cam = new CameraAiThinker(4);
      reg.add(cam);
    }
    ```
3.  Select an environment like `env:esp32cam` in PlatformIO to build and upload the code.

<br>

## 🔧 MCP Tool Interface

This tool is registered with the name `capture_image` and can be called with an MCP command as follows.

#### **Example Invoke Command**

```json
{
  "tool": "capture_image",
  "args": {
    "quality": "high",
    "flash": "on"
  }
}
```

#### **Example Success Observation**

On a successful call, an `observation` event like the one below will be published. The captured image can be accessed directly via the `asset.url`.

```json
{
  "type": "observation",
  "source": "capture_image",
  "status": "success",
  "payload": {
    "result": "captured",
    "asset": {
      "asset_id": "3dc5b0a51c6f378a",
      "kind": "image",
      "mime": "image/jpeg",
      "url": "http://192.168.1.10/last.jpg?rid=3dc5b0a51c6f378a"
    }
  }
}
```

<br>

## 🔌 Pin Configuration

The camera pin settings are hard-coded in the `camera_ai_thinker.cpp` file to match the standard for the AI-Thinker board. If you are using a different variant of the ESP32 camera board, you may need to modify this pin map.