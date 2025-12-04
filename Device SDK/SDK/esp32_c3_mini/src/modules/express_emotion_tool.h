#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>
#include "tool.h"
#include "eye_controller.h"

// 1. 감정 표현 툴 (기존)
class ExpressEmotionTool : public ITool {
public:
  bool init() override {
    EyeController::instance().begin();
    return true;
  }

  const char* name() const override { return "ExpressEmotion"; }

  void describe(JsonObject& tool) override {
    tool["name"] = name();
    tool["description"] = "Set the eye mood color while blink continues automatically.";
    auto params = tool.createNestedObject("parameters");
    params["type"] = "object";
    auto props = params.createNestedObject("properties");

    auto mood = props.createNestedObject("mood");
    mood["type"] = "string";
    mood["description"] = "Emotion to express: neutral | annoyed | angry";

    auto req = params.createNestedArray("required");
    req.add("mood");
  }

  bool invoke(JsonObjectConst args, ObservationBuilder& out) override {
    const char* moodStr = args["mood"] | "neutral";
    EyeController::Mood mood = EyeController::Mood::Neutral;

    if      (strcasecmp(moodStr, "neutral") == 0) mood = EyeController::Mood::Neutral;
    else if (strcasecmp(moodStr, "annoyed") == 0) mood = EyeController::Mood::Annoyed;
    else if (strcasecmp(moodStr, "angry")   == 0) mood = EyeController::Mood::Angry;
    else {
      return false;
    }

    EyeController::instance().setMood(mood, /*immediateShow=*/true);

    StaticJsonDocument<64> doc;
    doc["mood"] = moodStr;
    String payload;
    serializeJson(doc, payload);
    out.success(payload.c_str());
    return true;
  }
};

// 2. 패턴 실행 툴 (임시 실행 - 저장하지 않음)
class PlayLEDPatternTool : public ITool {
public:
  bool init() override {
    EyeController::instance().begin();
    return true;
  }

  const char* name() const override { return "PlayLEDPattern"; }

  void describe(JsonObject& tool) override {
    tool["name"] = name();
    tool["description"] = "Play a LED pattern with mathematical expressions (temporary - not saved). "
                          "Use this to test patterns or create one-time effects. "
                          "Variables: theta (0~2π), t (time in seconds), i (LED index 0~11). "
                          "Functions: sin, cos, tan, abs, sqrt, floor, ceil, max(a,b), min(a,b), mod(a,b), pow(a,b). "
                          "Operators: +, -, *, /, %, <, >, <=, >=, ==, !=, &&, ||, !. "
                          "Examples:\n"
                          "- Rotating rainbow: hue='theta+t', sat='1', brightness='0.5'\n"
                          "- Half split (red/cyan): hue='(i < 6) * 0 + (i >= 6) * 3.14', sat='1', brightness='0.5'\n"
                          "- Even LEDs only: brightness='(i % 2 == 0) * 1.0'\n"
                          "- Pulsing: brightness='sin(t*2)*0.5+0.5'\n"
                          "- Complex: hue='(i >= 3 && i <= 8) * (theta + t)', sat='1', brightness='0.8'";
    
    auto params = tool.createNestedObject("parameters");
    params["type"] = "object";
    auto props = params.createNestedObject("properties");

    auto hue = props.createNestedObject("hue");
    hue["type"] = "string";
    hue["description"] = "Expression for color (0~2π color wheel)";

    auto sat = props.createNestedObject("saturation");
    sat["type"] = "string";
    sat["description"] = "Expression for saturation (0~1)";

    auto val = props.createNestedObject("brightness");
    val["type"] = "string";
    val["description"] = "Expression for brightness (0~1)";

    auto dur = props.createNestedObject("duration");
    dur["type"] = "number";
    dur["description"] = "Duration in seconds (0 = infinite)";

    auto req = params.createNestedArray("required");
    req.add("hue");
    req.add("saturation");
    req.add("brightness");
    req.add("duration");
  }

  bool invoke(JsonObjectConst args, ObservationBuilder& out) override {
    const char* hue = args["hue"] | "0";
    const char* sat = args["saturation"] | "1";
    const char* val = args["brightness"] | "0.5";
    float duration = args["duration"] | 0.0f;

    // 임시 패턴 이름으로 저장 (항상 덮어쓰기)
    bool success = EyeController::instance().dynamicPattern.savePattern(
      "__temp__", hue, sat, val, duration
    );

    if (!success) {
      out.error("Failed to create pattern", "Failed to create pattern");
      return false;
    }

    // 즉시 실행
    EyeController::instance().dynamicPattern.playPattern("__temp__");

    StaticJsonDocument<256> doc;
    doc["status"] = "playing";
    doc["hue"] = hue;
    doc["saturation"] = sat;
    doc["brightness"] = val;
    doc["duration"] = duration;
    doc["saved"] = false;
    
    String payload;
    serializeJson(doc, payload);
    out.success(payload.c_str());
    return true;
  }
};

// 3. 패턴 저장 툴 (영구 저장)
class SaveLEDPatternTool : public ITool {
public:
  bool init() override {
    EyeController::instance().begin();
    return true;
  }

  const char* name() const override { return "SaveLEDPattern"; }

  void describe(JsonObject& tool) override {
    tool["name"] = name();
    tool["description"] = "Save a LED pattern permanently with a name for later use. "
                          "Use this only for patterns the user wants to keep. "
                          "Saved patterns can be replayed by name using PlaySavedLEDPattern. "
                          "Maximum 10 saved patterns.";
    
    auto params = tool.createNestedObject("parameters");
    params["type"] = "object";
    auto props = params.createNestedObject("properties");

    auto name_param = props.createNestedObject("name");
    name_param["type"] = "string";
    name_param["description"] = "Pattern name (unique identifier, must not be '__temp__')";

    auto hue = props.createNestedObject("hue");
    hue["type"] = "string";
    hue["description"] = "Expression for color (0~2π color wheel)";

    auto sat = props.createNestedObject("saturation");
    sat["type"] = "string";
    sat["description"] = "Expression for saturation (0~1)";

    auto val = props.createNestedObject("brightness");
    val["type"] = "string";
    val["description"] = "Expression for brightness (0~1)";

    auto dur = props.createNestedObject("duration");
    dur["type"] = "number";
    dur["description"] = "Duration in seconds (0 = infinite)";

    auto req = params.createNestedArray("required");
    req.add("name");
    req.add("hue");
    req.add("saturation");
    req.add("brightness");
    req.add("duration");
  }

  bool invoke(JsonObjectConst args, ObservationBuilder& out) override {
    const char* name = args["name"] | "unnamed";
    const char* hue = args["hue"] | "0";
    const char* sat = args["saturation"] | "1";
    const char* val = args["brightness"] | "0.5";
    float duration = args["duration"] | 0.0f;

    // __temp__ 이름은 예약어
    if (strcmp(name, "__temp__") == 0) {
      out.error("Pattern name '__temp__' is reserved", "Pattern name '__temp__' is reserved");
      return false;
    }

    bool success = EyeController::instance().dynamicPattern.savePattern(
      name, hue, sat, val, duration
    );

    if (!success) {
      out.error("Failed to save pattern (storage full or invalid)", "Failed to save pattern (storage full or invalid)");
      return false;
    }

    StaticJsonDocument<256> doc;
    doc["name"] = name;
    doc["hue"] = hue;
    doc["saturation"] = sat;
    doc["brightness"] = val;
    doc["duration"] = duration;
    doc["saved"] = true;
    
    String payload;
    serializeJson(doc, payload);
    out.success(payload.c_str());
    return true;
  }
};

// 4. 저장된 패턴 재생 툴
class PlaySavedLEDPatternTool : public ITool {
public:
  bool init() override {
    EyeController::instance().begin();
    return true;
  }

  const char* name() const override { return "PlaySavedLEDPattern"; }

  void describe(JsonObject& tool) override {
    tool["name"] = name();
    tool["description"] = "Play a previously saved LED pattern by name. "
                          "Pattern will run for its specified duration.";
    
    auto params = tool.createNestedObject("parameters");
    params["type"] = "object";
    auto props = params.createNestedObject("properties");

    auto name_param = props.createNestedObject("name");
    name_param["type"] = "string";
    name_param["description"] = "Saved pattern name to play";

    auto req = params.createNestedArray("required");
    req.add("name");
  }

  bool invoke(JsonObjectConst args, ObservationBuilder& out) override {
    const char* name = args["name"] | "";
    
    if (strlen(name) == 0) {
      out.error("Pattern name required", "Pattern name required");
      return false;
    }

    bool success = EyeController::instance().dynamicPattern.playPattern(name);

    if (!success) {
      out.error("Pattern not found", "Pattern not found");
      return false;
    }

    StaticJsonDocument<128> doc;
    doc["playing"] = name;
    doc["status"] = "started";
    
    String payload;
    serializeJson(doc, payload);
    out.success(payload.c_str());
    return true;
  }
};

// 5. 패턴 중지 툴
class StopLEDPatternTool : public ITool {
public:
  bool init() override {
    EyeController::instance().begin();
    return true;
  }

  const char* name() const override { return "StopLEDPattern"; }

  void describe(JsonObject& tool) override {
    tool["name"] = name();
    tool["description"] = "Stop the currently playing LED pattern and return to eye blink mode.";
    
    auto params = tool.createNestedObject("parameters");
    params["type"] = "object";
    auto props = params.createNestedObject("properties");
  }

  bool invoke(JsonObjectConst args, ObservationBuilder& out) override {
    EyeController::instance().dynamicPattern.stop();
    
    StaticJsonDocument<64> doc;
    doc["status"] = "stopped";
    
    String payload;
    serializeJson(doc, payload);
    out.success(payload.c_str());
    return true;
  }
};

// 6. 저장된 패턴 목록 조회 툴
class ListSavedPatternsTool : public ITool {
public:
  bool init() override {
    EyeController::instance().begin();
    return true;
  }

  const char* name() const override { return "ListSavedPatterns"; }

  void describe(JsonObject& tool) override {
    tool["name"] = name();
    tool["description"] = "List all saved LED patterns with their details.";
    
    auto params = tool.createNestedObject("parameters");
    params["type"] = "object";
    auto props = params.createNestedObject("properties");
  }

  bool invoke(JsonObjectConst args, ObservationBuilder& out) override {
    auto& dp = EyeController::instance().dynamicPattern;
    int count = dp.getPatternCount();

    StaticJsonDocument<1024> doc;
    doc["count"] = count;
    auto patterns = doc.createNestedArray("patterns");

    for (int i = 0; i < count; i++) {
      const auto* pattern = dp.getPattern(i);
      if (pattern && pattern->name != "__temp__") {  // 임시 패턴 제외
        auto p = patterns.createNestedObject();
        p["name"] = pattern->name;
        p["hue"] = pattern->hue_expr;
        p["saturation"] = pattern->sat_expr;
        p["brightness"] = pattern->val_expr;
        p["duration"] = pattern->duration_sec;
      }
    }

    String payload;
    serializeJson(doc, payload);
    out.success(payload.c_str());
    return true;
  }
};