// modules/ports_impact.cpp
#include <Arduino.h>
#include "port_registry.h"

// 테스트용 임팩트 OutPort (랜덤 값 발생)
class ImpactOutPort : public OutPort {
public:
  static constexpr uint32_t PERIOD_MS = 100;  // 10Hz
  const char* name() const override { return "impact_live"; }

  void describe(JsonObject& port) override {
    port["name"] = name();
    port["type"] = "outport";
    port["data_type"] = "float";
    port["description"] = "Fake impact sensor (test only)";
    port["update_rate_hz"] = 1000 / PERIOD_MS;
  }

  uint32_t periodMs() const override { return PERIOD_MS; }

  void tick(uint32_t now_ms) override {
    (void)now_ms;

    // 랜덤 충격 값 생성
    float impact = random(0, 200) / 10.0f; // 0.0 ~ 20.0

    // 가끔 (40%)만 이벤트 보내기
    if (random(0, 1000) < 5) {
      port_publish_data(name(), impact);
      Serial.printf("[FAKE IMPACT] %.2f\n", impact);
    }
  }
};

// 전역 인스턴스

