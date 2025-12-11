#pragma once
#include <Arduino.h>
#include <FastLED.h>
#include "dynamic_pattern.h"

#if defined(ESP32)
  #include "freertos/FreeRTOS.h"
  #include "freertos/task.h"
#endif

#ifndef LED_PIN
#define LED_PIN     6
#endif
#ifndef NUM_LEDS
#define NUM_LEDS    12
#endif
#ifndef LED_TYPE
#define LED_TYPE    WS2812B
#endif
#ifndef COLOR_ORDER
#define COLOR_ORDER GRB
#endif

// 전역 LED 버퍼
static CRGB leds[NUM_LEDS];

class EyeController {
public:
  enum class Mood : uint8_t { Neutral, Annoyed, Angry };
  enum class BlinkPhase : uint8_t { Idle, Closing, Hold, Opening };

  struct Config {
    // 타이밍
    uint16_t baseBlinkMs   = 10000; // 기본 10초
    uint16_t jitterMs      = 2000;  // ±1초
    uint16_t closeMs       = 140;   // 감기
    uint16_t holdMs        =  80;   // 유지
    uint16_t openMs        = 160;   // 뜨기
    uint8_t  baseBrightness= 100;   // 기본 밝기
    uint16_t tickMs        = 16;    // 태스크 주기(~60fps)

    // 연출 옵션
    bool     eyelidSweep   = true;  // true면 눈꺼풀 스윕 사용
    uint8_t  featherLEDs   = 2;     // 경계 부드러움(LED 개수 기준)
    uint8_t  doubleBlinkPct= 20;    // 더블 블링크 확률(%)
    uint16_t doubleBlinkGapMin = 200; // 2회차 시작 지연 최소(ms)
    uint16_t doubleBlinkGapMax = 300; // 최대(ms)

    // 기하 정보
    uint8_t  topIndex      = 3;     // ★ 맨 위 LED 인덱스
  } cfg;

  DynamicPattern dynamicPattern;

  static EyeController& instance() {
    static EyeController inst;
    return inst;
  }

  void begin() {
    if (_inited) return;
    FastLED.addLeds<LED_TYPE, LED_PIN, COLOR_ORDER>(leds, NUM_LEDS);
    FastLED.setBrightness(cfg.baseBrightness);
    FastLED.clear(true);
    setMood(Mood::Neutral, /*immediateShow=*/true);

    randomSeed((uint32_t)micros());
    _scheduleNextBlink(millis(), /*immediate=*/false);
    _inited = true;
    _startBackgroundTask();
  }

  void update() {
    if (!_inited) return;
    const uint32_t now = millis();

    // 동적 패턴 우선 처리
    if (dynamicPattern.isActive()) {
      dynamicPattern.update(leds, now);
      FastLED.show();
      return;
    }

    // 기존 깜박임 로직
    switch (_phase) {
      case BlinkPhase::Idle:
        if ((int32_t)(now - _nextDue) >= 0) {
          _startPhase(BlinkPhase::Closing, now);
        } else {
          _renderOpen();
        }
        break;

      case BlinkPhase::Closing: {
        uint8_t scale = _progressScale(now, _phaseStart, cfg.closeMs, true);
        _renderByPhase(scale);
        if (_phaseDone(now, _phaseStart, cfg.closeMs)) {
          _startPhase(BlinkPhase::Hold, now);
        }
      } break;

      case BlinkPhase::Hold:
        _renderByPhase(0);
        if (_phaseDone(now, _phaseStart, cfg.holdMs)) {
          _startPhase(BlinkPhase::Opening, now);
        }
        break;

      case BlinkPhase::Opening: {
        uint8_t scale = _progressScale(now, _phaseStart, cfg.openMs, false);
        _renderByPhase(scale);
        if (_phaseDone(now, _phaseStart, cfg.openMs)) {
          _phase = BlinkPhase::Idle;
          if (!_pendingDouble && cfg.doubleBlinkPct > 0 &&
              (uint8_t)random(0, 100) < cfg.doubleBlinkPct) {
            _pendingDouble = true;
            uint16_t gap = cfg.doubleBlinkGapMin +
                           (uint16_t)random(0, (int)max<int>(0, cfg.doubleBlinkGapMax - cfg.doubleBlinkGapMin + 1));
            _nextDue = now + gap;
          } else {
            _pendingDouble = false;
            _scheduleNextBlink(now, /*immediate=*/false);
          }
        }
      } break;
    }
  }

  void setMood(Mood m, bool immediateShow = false) {
    _mood = m;
    switch (m) {
      case Mood::Neutral:  _color = CRGB(0, 255, 0);   break;
      case Mood::Annoyed:  _color = CRGB(255, 255, 0); break;
      case Mood::Angry:    _color = CRGB(255, 0, 0);   break;
    }
    if (immediateShow && _phase == BlinkPhase::Idle) _renderOpen();
  }

  Mood currentMood() const { return _mood; }

private:
  EyeController() {}
  bool _inited = false;

  Mood _mood = Mood::Neutral;
  CRGB _color = CRGB(0, 255, 0);

  BlinkPhase _phase = BlinkPhase::Idle;
  uint32_t _phaseStart = 0;
  uint32_t _nextDue    = 0;
  bool     _pendingDouble = false;

#if defined(ESP32)
  TaskHandle_t _taskHandle = nullptr;
#endif

  void _startPhase(BlinkPhase p, uint32_t now) { _phase = p; _phaseStart = now; }

  void _scheduleNextBlink(uint32_t now, bool immediate) {
    uint32_t base = cfg.baseBlinkMs;
    if (!immediate) base = _withJitter(cfg.baseBlinkMs, cfg.jitterMs);
    _nextDue = now + base;
  }

  static bool _phaseDone(uint32_t now, uint32_t start, uint16_t dur) {
    return (int32_t)(now - (start + dur)) >= 0;
  }

  static uint8_t _progressScale(uint32_t now, uint32_t start, uint16_t dur, bool closing) {
    if (dur == 0) return closing ? 0 : 255;
    uint32_t elapsed = now - start;
    if (elapsed >= dur) return closing ? 0 : 255;
    uint32_t t = (elapsed * 255UL) / dur;
    return closing ? (255 - t) : t;
  }

  static uint32_t _withJitter(uint32_t base, uint16_t jitter) {
    if (jitter == 0) return base;
    int16_t half = jitter / 2;
    int16_t r = random(-half, half + 1);
    int32_t v = (int32_t)base + r;
    if (v < 50) v = 50;
    return (uint32_t)v;
  }

  void _renderOpen() { _renderBothLids(/*openRatio=*/1.0f); }

  void _renderByPhase(uint8_t scale) {
    if (!cfg.eyelidSweep) {
      CRGB c = _color; c.nscale8_video(scale);
      fill_solid(leds, NUM_LEDS, c);
      FastLED.show();
      return;
    }
    float openRatio = scale / 255.0f;
    _renderBothLids(openRatio);
  }

  void _renderBothLids(float openRatio) {
    const float low  = (1.0f - openRatio) * 0.5f;
    const float high = 1.0f - low;

    const float feather = (cfg.featherLEDs > 0) ? (float)cfg.featherLEDs / (float)NUM_LEDS : 0.0f;

    for (uint8_t i = 0; i < NUM_LEDS; ++i) {
      int16_t di = (int16_t)i - (int16_t)cfg.topIndex;
      di %= (int16_t)NUM_LEDS; if (di < 0) di += NUM_LEDS;
      float theta = (2.0f * PI) * ((float)di / (float)NUM_LEDS);

      float h = (cosf(theta) + 1.0f) * 0.5f;

      float lit = 0.0f;
      if (h >= (low + feather) && h <= (high - feather)) {
        lit = 1.0f;
      } else if (feather > 0.0f) {
        if (h > low && h < (low + feather)) {
          float t = (h - low) / feather;
          if (t < 0) t = 0; if (t > 1) t = 1;
          lit = t;
        }
        if (h < high && h > (high - feather)) {
          float t = (high - h) / feather;
          if (t < 0) t = 0; if (t > 1) t = 1;
          lit = max(lit, t);
        }
      }

      CRGB c = _color;
      c.nscale8_video((uint8_t)(lit * 255.0f));
      leds[i] = c;
    }
    FastLED.show();
  }

  static void _taskLoop(void* pv) {
    EyeController* self = static_cast<EyeController*>(pv);
    for (;;) {
      self->update();
      vTaskDelay(pdMS_TO_TICKS(self->cfg.tickMs));
    }
  }

  void _startBackgroundTask() {
#if defined(ESP32)
    if (_taskHandle) return;
    xTaskCreate(&_taskLoop, "EyeBlinkTask", 4096, this, 1, &_taskHandle);
#endif
  }
};