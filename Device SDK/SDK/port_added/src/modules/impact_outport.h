// modules/ports_impact.cpp
#include <Arduino.h>
#include "port_registry.h"

// 테스트용 임팩트 OutPort (1->100->1 순차 값 발생)
class Counter : public OutPort {
public:
  static constexpr uint32_t PERIOD_MS = 1000;  // 1Hz (1초에 한번)
  const char* name() const override { return "impact_live"; }

  void describe(JsonObject& port) override {
    port["name"] = name();
    port["type"] = "outport";
    port["data_type"] = "float";
    port["description"] = "1->100->1";
    port["update_rate_hz"] = 1000 / PERIOD_MS;
  }

  uint32_t periodMs() const override { return PERIOD_MS; }
  void tick(uint32_t now_ms) override {
    static uint32_t last_tick = 0;
    if (now_ms - last_tick < PERIOD_MS) return;
    last_tick = now_ms;

    // 1부터 100까지 올라갔다가 다시 1로 내려오기
    static float impact = 1.0f;
    static bool increasing = true;

    if (increasing) {
      impact += 1.0f;
      if (impact >= 100.0f) {
        increasing = false;
      }
    } else {
      impact -= 1.0f;
      if (impact <= 1.0f) {
        increasing = true;
      }
    }

    // 매 tick마다 이벤트 보내기 (1초에 한번)
    port_publish_data(name(), impact);
  }
};

// 전역 인스턴스