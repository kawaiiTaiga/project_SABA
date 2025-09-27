#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>
#include <FastLED.h>
#include "tool.h"              // ITool, ObservationBuilder 인터페이스
#include "eye_controller.h"    // EyeController

// MCP 툴: 감정표출(영문명)
class ExpressEmotionTool : public ITool {
public:
  bool init() override {
    // LED 등록/초기화는 EyeController가 전담
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

    // mood: string
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

    // 감정 적용
    EyeController::instance().setMood(mood, /*immediateShow=*/true);

    StaticJsonDocument<64> doc;
    doc["mood"] = moodStr;
    String payload;
    serializeJson(doc, payload);
    out.success(payload.c_str());
    return true;
  }
};
