#pragma once
#include <Arduino.h>
#include <FastLED.h>

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
    uint8_t  topIndex      = 3;     // ★ 맨 위 LED 인덱스 (네 보드는 3)
  } cfg;

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

    switch (_phase) {
      case BlinkPhase::Idle:
        if ((int32_t)(now - _nextDue) >= 0) {
          _startPhase(BlinkPhase::Closing, now);
        } else {
          _renderOpen();
        }
        break;

      case BlinkPhase::Closing: {
        uint8_t scale = _progressScale(now, _phaseStart, cfg.closeMs, true); // 255→0
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
        uint8_t scale = _progressScale(now, _phaseStart, cfg.openMs, false); // 0→255
        _renderByPhase(scale);
        if (_phaseDone(now, _phaseStart, cfg.openMs)) {
          _phase = BlinkPhase::Idle;
          // 더블 블링크
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
      case Mood::Neutral:  _color = CRGB(0, 255, 0);   break; // 초록
      case Mood::Annoyed:  _color = CRGB(255, 255, 0); break; // 노랑
      case Mood::Angry:    _color = CRGB(255, 0, 0);   break; // 빨강
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

  // ---- 타이밍 ----
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
    return closing ? (255 - t) : t; // 닫힘: 255→0, 열림: 0→255
  }

  static uint32_t _withJitter(uint32_t base, uint16_t jitter) {
    if (jitter == 0) return base;
    int16_t half = jitter / 2;
    int16_t r = random(-half, half + 1);
    int32_t v = (int32_t)base + r;
    if (v < 50) v = 50;
    return (uint32_t)v;
  }

  // ---- 렌더링 (양쪽 눈꺼풀) ----
  void _renderOpen() { _renderBothLids(/*openRatio=*/1.0f); }

  void _renderByPhase(uint8_t scale /*0..255*/) {
    if (!cfg.eyelidSweep) { // 전체 페이드로 되돌리고 싶을 때
      CRGB c = _color; c.nscale8_video(scale);
      fill_solid(leds, NUM_LEDS, c);
      FastLED.show();
      return;
    }
    float openRatio = scale / 255.0f; // 0.0 닫힘 ~ 1.0 열림
    _renderBothLids(openRatio);
  }

  /**
   * 양쪽 눈꺼풀 스윕:
   * - 각 LED의 "세로 높이" h ∈ [0..1] 계산 (1=맨 위, 0=맨 아래)
   * - 열림 비율 openRatio에 따라 가운데 띠 [low, high]만 보이게 함.
   *   low  = (1 - openRatio) / 2
   *   high = 1 - low
   * - featherLEDs로 low/high 경계를 부드럽게.
   */
  void _renderBothLids(float openRatio) {
    const float low  = (1.0f - openRatio) * 0.5f;
    const float high = 1.0f - low;

    // feather를 'LED 개수'에서 '높이 스케일(0..1)'로 변환
    const float feather = (cfg.featherLEDs > 0) ? (float)cfg.featherLEDs / (float)NUM_LEDS : 0.0f;

    for (uint8_t i = 0; i < NUM_LEDS; ++i) {
      // 인덱스 → 각도(위=0 rad, 아래=π rad)
      int16_t di = (int16_t)i - (int16_t)cfg.topIndex;
      // 모듈러 정규화
      di %= (int16_t)NUM_LEDS; if (di < 0) di += NUM_LEDS;
      float theta = (2.0f * PI) * ((float)di / (float)NUM_LEDS); // 0..2π, 위=0

      // 세로 높이 h: 1(위) ↔ 0(아래)
      float h = (cosf(theta) + 1.0f) * 0.5f;

      // 가운데 띠 [low, high] 안이면 켜짐, 바깥이면 꺼짐, feather로 스무딩
      float lit = 0.0f;
      if (h >= (low + feather) && h <= (high - feather)) {
        lit = 1.0f; // 완전 켜짐
      } else if (feather > 0.0f) {
        // 아래 경계 스무딩
        if (h > low && h < (low + feather)) {
          float t = (h - low) / feather; // 0..1
          if (t < 0) t = 0; if (t > 1) t = 1;
          lit = t;
        }
        // 위 경계 스무딩
        if (h < high && h > (high - feather)) {
          float t = (high - h) / feather; // 0..1
          if (t < 0) t = 0; if (t > 1) t = 1;
          // 양쪽 경계가 겹치면 더 낮은 쪽 사용
          lit = max(lit, t);
        }
      }

      CRGB c = _color;
      c.nscale8_video((uint8_t)(lit * 255.0f));
      leds[i] = c;
    }
    FastLED.show();
  }

  // ---- 백그라운드 태스크 ----
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
