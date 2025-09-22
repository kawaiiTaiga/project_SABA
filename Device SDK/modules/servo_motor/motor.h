#pragma once
#include <Arduino.h>
#include <ESP32Servo.h>
#include "tool.h"

// 보드에 맞춰 바꿔도 됨
#ifndef SERVO_PIN
#define SERVO_PIN 6
#endif

class Motor_rotate : public ITool {
public:
  explicit Motor_rotate(int pin = SERVO_PIN) : _pin(pin) {}

  bool init() override {
    _servo.setPeriodHertz(50);      // SG90 표준
    _servo.attach(_pin, 500, 2400); // 안전 범위
    _servo.write(10);                // 출발 각도(0도)
    return true;
  }

  const char* name() const override { return "Motor"; }

  void describe(JsonObject& tool) override {
    tool["name"] = name();
    tool["description"] = "3초 회전 후 복귀";
    auto params = tool.createNestedObject("parameters");
    params["type"] = "object";      // 파라미터 없음
  }

  bool invoke(JsonObjectConst /*args*/, ObservationBuilder& out) override {
    _servo.write(100);        
    delay(3000);            
    _servo.write(10);         
    out.success("Done");
    return true;
  }
  

private:
  int _pin;
  Servo _servo;
};
