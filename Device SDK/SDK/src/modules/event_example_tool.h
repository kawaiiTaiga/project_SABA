#pragma once
#include "event_tool.h"

// Mock: every interval_ms (default 10s) emit a random dio.rise / dio.fall event.
class ExampleDigitalEvent : public EventTool {
public:
  explicit ExampleDigitalEvent(uint8_t /*pin_ignored*/)
  : EventTool("digital_event", "Mock: random dio events (rise/fall)") {}

  bool onInit() override {
    // 랜덤 시드 (ESP32에선 micros()만으로도 충분)
    randomSeed((uint32_t)micros());
    return true;
  }

  // 추가 파라미터: interval_ms만 받도록 변경
  void buildExtraParameters(JsonObject& props) override {
    props["interval_ms"]["type"] = "integer";    // 기본 10000ms
  }

  void buildSignals(JsonObject& signals) override {
    auto ev = signals.createNestedArray("event_types");
    ev.add("dio.rise");
    ev.add("dio.fall");
  }

  bool onSubscribe(JsonObjectConst args, ObservationBuilder& out) override {
    // Use .as<T>() for JsonObjectConst
    interval_ms_ = args.containsKey("interval_ms") 
                   ? args["interval_ms"].as<uint32_t>() 
                   : 10000;
    
    active_ = true;
    last_emit_ms_ = millis();
    
    Serial.printf("[DIGITAL_EVENT] ✅ SUBSCRIBED! interval=%ums\n", interval_ms_);
    
    out.success("subscribed (mock random events)");
    return true;
  }

  bool onUnsubscribe(JsonObjectConst /*args*/, ObservationBuilder& out) override {
    active_ = false;
    out.success("unsubscribed");
    return true;
  }

  void tick(uint32_t now_ms) override {
    if (!active_) return;
    if (now_ms - last_emit_ms_ < interval_ms_) return;
    last_emit_ms_ = now_ms;

    // 0 or 1 랜덤 선택
    int v = (int)random(0, 2);
    const bool isRise = (v == 1);

    ObservationBuilder ob;
    ob.success(isRise ? "rise" : "fall");

    auto a = ob.addAsset();
    a["kind"] = "event";
    a["event_type"] = isRise ? "dio.rise" : "dio.fall";
    a["value"] = isRise ? 1 : 0;

    emitNow(ob);
  }

private:
  bool active_ = false;
  uint32_t interval_ms_ = 10000;  // 기본 10초
  uint32_t last_emit_ms_ = 0;
};