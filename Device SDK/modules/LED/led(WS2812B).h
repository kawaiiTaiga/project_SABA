#pragma once
#include <Arduino.h>
#include <FastLED.h>
#include "tool.h"

// LED 설정
#define LED_PIN     6
#define NUM_LEDS    12
#define LED_TYPE    WS2812B
#define COLOR_ORDER GRB

static CRGB leds[NUM_LEDS];  // 공용 버퍼

// ==================== LED ON Tool ====================
class LedOnTool : public ITool {
public:
  bool init() override {
    FastLED.addLeds<LED_TYPE, LED_PIN, COLOR_ORDER>(leds, NUM_LEDS);
    FastLED.clear();
    FastLED.show();
    return true;
  }

  const char* name() const override { return "LED_On"; }

  void describe(JsonObject& tool) override {
    tool["name"] = name();
    tool["description"] = "RGB LED 켜기";
    auto params = tool.createNestedObject("parameters");
    params["type"] = "object";

    auto props = params.createNestedObject("properties");
    props["r"]["type"] = "string";
    props["g"]["type"] = "string";
    props["b"]["type"] = "string";
    props["brightness"]["type"] = "string";
  }

  bool invoke(JsonObjectConst args, ObservationBuilder& out) override {
    const char* rStr = args["r"] | "0";
    const char* gStr = args["g"] | "0";
    const char* bStr = args["b"] | "0";
    const char* brStr = args["brightness"] | "64";

    int r = atoi(rStr);
    int g = atoi(gStr);
    int b = atoi(bStr);
    int br = constrain(atoi(brStr), 0, 255);

    fill_solid(leds, NUM_LEDS, CRGB(r, g, b));
    FastLED.setBrightness(br);
    FastLED.show();
    out.success("LED 켜짐");
    return true;
  }
};

// ==================== LED OFF Tool ====================
class LedOffTool : public ITool {
public:
  bool init() override {
    FastLED.addLeds<LED_TYPE, LED_PIN, COLOR_ORDER>(leds, NUM_LEDS);
    FastLED.show();
    return true;
  }

  const char* name() const override { return "LED_Off"; }

  void describe(JsonObject& tool) override {
    tool["name"] = name();
    tool["description"] = "RGB LED 끄기";
    auto params = tool.createNestedObject("parameters");
    params["type"] = "object"; // 인자 없음
  }

  bool invoke(JsonObjectConst /*args*/, ObservationBuilder& out) override {
    FastLED.clear();
    FastLED.show();
    out.success("LED 끔");
    return true;
  }
};
