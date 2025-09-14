#pragma once
#include <Arduino.h>
#include <WebServer.h>
#include "esp_camera.h"
#include "tool.h"

class CameraAiThinker : public ITool {
public:
  explicit CameraAiThinker(int flashPin = 4);
  bool init() override;
  const char* name() const override { return "capture_image"; }
  void describe(JsonObject& tool) override;
  bool invoke(JsonObjectConst args, ObservationBuilder& out) override;
  void register_http(WebServer& srv) override;

  bool hasLast() const { return _last && _lastLen>0; }
  const uint8_t* lastBuf() const { return _last; }
  size_t lastLen() const { return _lastLen; }
  String lastId() const { return _lastId; }

private:
  int _flash;
  uint8_t* _last = nullptr;
  size_t _lastLen = 0;
  String _lastId;
  void setQuality(const String& q);
  static void warmup(int count=2, int delayMs=30);
  bool capture(const String& quality, const String& flashMode);
};