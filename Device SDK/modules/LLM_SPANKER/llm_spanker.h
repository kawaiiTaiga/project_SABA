// modules/pain_receptor_hitme.h
#pragma once
#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include "tool.h"  // ObservationBuilder, ITool 정의 포함

class PainReceptor_HitMe : public ITool {
public:
  // ===== 설정값 (필요 시 조정) =====
  static constexpr uint32_t WINDOW_MS = 6000;   // 측정 창 (6초)
  static constexpr uint8_t SDA_PIN    = 5;      // ESP32-C3 Mini 권장
  static constexpr uint8_t SCL_PIN    = 4;

  bool init() override {
    Wire.begin(SDA_PIN, SCL_PIN);
    delay(50);
    if (!mpu.begin()) return false;
    mpu.setAccelerometerRange(MPU6050_RANGE_8_G);
    mpu.setGyroRange(MPU6050_RANGE_500_DEG);
    mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);
    return true;
  }

  const char* name() const override { return "PAIN_RECEPTOR_HITME"; }

  void describe(JsonObject& tool) override {
    tool["name"] = name();
    tool["description"] =
      "Detects impact strength from motion and acceleration spikes (6s window).";
    JsonObject params = tool.createNestedObject("parameters");
    params["type"] = "object";
    params.createNestedObject("properties"); // 입력 없음
  }

  bool invoke(JsonObjectConst /*args*/, ObservationBuilder& out) override {
    sensors_event_t a, g, t;
    const uint32_t start = millis();

    int hits = 0;
    float maxImpact = 0.0f;
    float prevAcc = 9.81f;      // 중력 초기값
    float swingSpeed = 0.0f;    // 휘두르는 속도 누적값
    bool inHit = false;

    while (millis() - start < WINDOW_MS) {
      if (!mpu.getEvent(&a, &g, &t)) {
        delay(10);
        continue;
      }

      // 현재 가속도 벡터 크기
      float ax = a.acceleration.x;
      float ay = a.acceleration.y;
      float az = a.acceleration.z;
      float acc = sqrtf(ax*ax + ay*ay + az*az);

      // (1) 휘두르는 속도 추정: 가속도의 편차를 누적
      float deltaAcc = acc - 9.81f;
      if (fabsf(deltaAcc) > 2.0f) {   // 작은 진동은 무시
        swingSpeed += fabsf(deltaAcc) * 0.01f;  // dt ≈ 10ms
      }

      // (2) 충격 감지: 이전 프레임과의 변화량
      float dA = fabsf(acc - prevAcc);
      prevAcc = acc;

      // 히트 시작
      if (!inHit && dA > 35.0f) {
        inHit = true;
        hits++;

        // 충격 강도 = 순간 변화량 + 휘두름 속도의 영향
        float impact = dA + (swingSpeed * 10.0f);
        if (impact > maxImpact) maxImpact = impact;

        // 한 번 충돌 후 리셋
        swingSpeed = 0.0f;

      } else if (inHit && dA < 12.0f) {
        inHit = false;
      }

      delay(10);
    }

    // === 결과 분류 ===
    const char* hitsLabel =
        (hits <= 0) ? "none" :
        (hits == 1) ? "single" :
        (hits <= 3) ? "few" : "flurry";

    const char* intensity =
        (maxImpact < 40.0f)  ? "gentle" :
        (maxImpact < 80.0f)  ? "normal" :
        (maxImpact < 150.0f) ? "hard"   : "brutal";

    // === 결과 텍스트 ===
    String txt = "impact_window_complete | hits=";
    txt += hitsLabel;
    txt += " | intensity=";
    txt += intensity;

    out.success(txt.c_str()); // ObservationBuilder 그대로 사용
    return true;
  }

private:
  Adafruit_MPU6050 mpu;
};
