#pragma once
#include <Arduino.h>
#include <FastLED.h>
#include <ctype.h>
#include <math.h>

#ifndef NUM_LEDS
#define NUM_LEDS 12
#endif

// 경량 수식 파서 (비교 및 논리 연산자 지원)
class ExpressionEvaluator {
public:
  float eval(const char* expr, float theta, float t, int i) {
    _expr = expr;
    _pos = 0;
    _theta = theta;
    _t = t;
    _i = i;
    return _parseLogicalOr();
  }

private:
  const char* _expr;
  size_t _pos;
  float _theta, _t;
  int _i;

  char _peek() const {
    return _expr[_pos];
  }

  char _consume() {
    return _expr[_pos++];
  }

  void _skipWhitespace() {
    while (isspace(_peek())) _pos++;
  }

  // 논리 OR: logicalOr → logicalAnd ('||' logicalAnd)*
  float _parseLogicalOr() {
    _skipWhitespace();
    float result = _parseLogicalAnd();
    
    while (true) {
      _skipWhitespace();
      if (_peek() == '|' && _expr[_pos + 1] == '|') {
        _consume(); _consume();
        float right = _parseLogicalAnd();
        result = (result != 0 || right != 0) ? 1.0f : 0.0f;
      } else {
        break;
      }
    }
    return result;
  }

  // 논리 AND: logicalAnd → comparison ('&&' comparison)*
  float _parseLogicalAnd() {
    _skipWhitespace();
    float result = _parseComparison();
    
    while (true) {
      _skipWhitespace();
      if (_peek() == '&' && _expr[_pos + 1] == '&') {
        _consume(); _consume();
        float right = _parseComparison();
        result = (result != 0 && right != 0) ? 1.0f : 0.0f;
      } else {
        break;
      }
    }
    return result;
  }

  // 비교: comparison → expression (('<' | '>' | '<=' | '>=' | '==' | '!=') expression)?
  float _parseComparison() {
    _skipWhitespace();
    float result = _parseExpression();
    
    _skipWhitespace();
    char op1 = _peek();
    
    if (op1 == '<' || op1 == '>' || op1 == '=' || op1 == '!') {
      _consume();
      char op2 = _peek();
      
      // <=, >=, ==, !=
      if ((op1 == '<' && op2 == '=') || 
          (op1 == '>' && op2 == '=') || 
          (op1 == '=' && op2 == '=') || 
          (op1 == '!' && op2 == '=')) {
        _consume();
        float right = _parseExpression();
        
        if (op1 == '<') return (result <= right) ? 1.0f : 0.0f;
        if (op1 == '>') return (result >= right) ? 1.0f : 0.0f;
        if (op1 == '=') return (fabs(result - right) < 0.0001f) ? 1.0f : 0.0f;
        if (op1 == '!') return (fabs(result - right) >= 0.0001f) ? 1.0f : 0.0f;
      }
      // <, >
      else if (op1 == '<' || op1 == '>') {
        float right = _parseExpression();
        if (op1 == '<') return (result < right) ? 1.0f : 0.0f;
        if (op1 == '>') return (result > right) ? 1.0f : 0.0f;
      }
    }
    
    return result;
  }

  // 파싱: expression → term (('+' | '-') term)*
  float _parseExpression() {
    _skipWhitespace();
    float result = _parseTerm();
    
    while (true) {
      _skipWhitespace();
      char op = _peek();
      if (op == '+' || op == '-') {
        _consume();
        float right = _parseTerm();
        result = (op == '+') ? (result + right) : (result - right);
      } else {
        break;
      }
    }
    return result;
  }

  // term → factor (('*' | '/' | '%') factor)*
  float _parseTerm() {
    _skipWhitespace();
    float result = _parseFactor();
    
    while (true) {
      _skipWhitespace();
      char op = _peek();
      if (op == '*' || op == '/' || op == '%') {
        _consume();
        float right = _parseFactor();
        if (op == '*') {
          result *= right;
        } else if (op == '/') {
          result = (right != 0) ? (result / right) : 0;
        } else if (op == '%') {
          result = fmod(result, right);
        }
      } else {
        break;
      }
    }
    return result;
  }

  // factor → '!' factor | number | variable | function '(' expression ')' | '(' expression ')'
  float _parseFactor() {
    _skipWhitespace();
    
    // 논리 NOT
    if (_peek() == '!') {
      _consume();
      _skipWhitespace();
      // != 연산자와 구분 (다음이 =가 아닐 때만 NOT)
      if (_peek() != '=') {
        return (_parseFactor() == 0) ? 1.0f : 0.0f;
      } else {
        // != 연산자인 경우 위치 되돌림
        _pos--;
        return _parseUnary();
      }
    }
    
    return _parseUnary();
  }

  float _parseUnary() {
    _skipWhitespace();
    
    // 음수
    if (_peek() == '-') {
      _consume();
      return -_parseUnary();
    }
    
    // 괄호
    if (_peek() == '(') {
      _consume();
      float result = _parseLogicalOr();  // 최상위 레벨부터 다시 파싱
      _skipWhitespace();
      if (_peek() == ')') _consume();
      return result;
    }
    
    // 숫자
    if (isdigit(_peek()) || _peek() == '.') {
      return _parseNumber();
    }
    
    // 변수 또는 함수
    if (isalpha(_peek())) {
      return _parseIdentifier();
    }
    
    return 0;
  }

  float _parseNumber() {
    size_t start = _pos;
    while (isdigit(_peek()) || _peek() == '.') _pos++;
    
    char buffer[32];
    size_t len = min((size_t)31, _pos - start);
    strncpy(buffer, _expr + start, len);
    buffer[len] = '\0';
    
    return atof(buffer);
  }

  float _parseIdentifier() {
    size_t start = _pos;
    while (isalnum(_peek()) || _peek() == '_') _pos++;
    
    char buffer[32];
    size_t len = min((size_t)31, _pos - start);
    strncpy(buffer, _expr + start, len);
    buffer[len] = '\0';
    
    _skipWhitespace();
    
    // 함수 호출
    if (_peek() == '(') {
      _consume();
      float arg1 = _parseLogicalOr();  // 함수 인자도 최상위 레벨부터
      _skipWhitespace();
      
      // 2개 인자 함수
      if (_peek() == ',') {
        _consume();
        float arg2 = _parseLogicalOr();
        _skipWhitespace();
        if (_peek() == ')') _consume();
        
        if (strcmp(buffer, "max") == 0) return max(arg1, arg2);
        if (strcmp(buffer, "min") == 0) return min(arg1, arg2);
        if (strcmp(buffer, "mod") == 0) return fmod(arg1, arg2);
        if (strcmp(buffer, "pow") == 0) return pow(arg1, arg2);
        return 0;
      }
      
      // 1개 인자 함수
      if (_peek() == ')') _consume();
      
      if (strcmp(buffer, "sin") == 0) return sin(arg1);
      if (strcmp(buffer, "cos") == 0) return cos(arg1);
      if (strcmp(buffer, "tan") == 0) return tan(arg1);
      if (strcmp(buffer, "abs") == 0) return fabs(arg1);
      if (strcmp(buffer, "sqrt") == 0) return sqrt(arg1);
      if (strcmp(buffer, "floor") == 0) return floor(arg1);
      if (strcmp(buffer, "ceil") == 0) return ceil(arg1);
      return 0;
    }
    
    // 변수
    if (strcmp(buffer, "theta") == 0) return _theta;
    if (strcmp(buffer, "t") == 0) return _t;
    if (strcmp(buffer, "i") == 0) return (float)_i;
    if (strcmp(buffer, "pi") == 0) return PI;
    
    return 0;
  }
};

// 동적 패턴 컨트롤러
class DynamicPattern {
public:
  struct Pattern {
    String name;
    String hue_expr;
    String sat_expr;
    String val_expr;
    float duration_sec;  // 0이면 무한
  };

  // 패턴 저장 (최대 10개)
  bool savePattern(const char* name, const char* hue, const char* sat, const char* val, float duration) {
    // 이미 있으면 덮어쓰기
    for (int i = 0; i < _pattern_count; i++) {
      if (_patterns[i].name == name) {
        _patterns[i].hue_expr = hue;
        _patterns[i].sat_expr = sat;
        _patterns[i].val_expr = val;
        _patterns[i].duration_sec = duration;
        return true;
      }
    }
    
    // 새로 추가
    if (_pattern_count >= 10) return false;
    
    _patterns[_pattern_count].name = name;
    _patterns[_pattern_count].hue_expr = hue;
    _patterns[_pattern_count].sat_expr = sat;
    _patterns[_pattern_count].val_expr = val;
    _patterns[_pattern_count].duration_sec = duration;
    _pattern_count++;
    return true;
  }

  // 패턴 실행
  bool playPattern(const char* name) {
    for (int i = 0; i < _pattern_count; i++) {
      if (_patterns[i].name == name) {
        _current_pattern = &_patterns[i];
        _active = true;
        _start_time = millis();
        return true;
      }
    }
    return false;
  }

  // 패턴 목록
  int getPatternCount() const { return _pattern_count; }
  const Pattern* getPattern(int idx) const {
    if (idx >= 0 && idx < _pattern_count) return &_patterns[idx];
    return nullptr;
  }

  void stop() {
    _active = false;
    _current_pattern = nullptr;
  }

  bool isActive() const { return _active; }

  void update(CRGB* leds, uint32_t now) {
    if (!_active || !_current_pattern) return;
    
    // 시간 체크
    float elapsed = (now - _start_time) / 1000.0f;
    if (_current_pattern->duration_sec > 0 && elapsed >= _current_pattern->duration_sec) {
      stop();
      return;
    }
    
    float t = elapsed;
    
    for (int i = 0; i < NUM_LEDS; i++) {
      float theta = (2.0f * PI * i) / NUM_LEDS;
      
      float h = _evaluator.eval(_current_pattern->hue_expr.c_str(), theta, t, i);
      float s = _evaluator.eval(_current_pattern->sat_expr.c_str(), theta, t, i);
      float v = _evaluator.eval(_current_pattern->val_expr.c_str(), theta, t, i);
      
      // 정규화
      h = fmod(h, 2 * PI);
      if (h < 0) h += 2 * PI;
      
      s = constrain(s, 0.0f, 1.0f);
      v = constrain(fabs(v), 0.0f, 1.0f);
      
      // HSV → RGB
      uint8_t hue_byte = (uint8_t)((h / (2 * PI)) * 255);
      uint8_t sat_byte = (uint8_t)(s * 255);
      uint8_t val_byte = (uint8_t)(v * 255);
      
      leds[i] = CHSV(hue_byte, sat_byte, val_byte);
    }
  }

private:
  Pattern _patterns[10];
  int _pattern_count = 0;
  Pattern* _current_pattern = nullptr;
  bool _active = false;
  uint32_t _start_time = 0;
  ExpressionEvaluator _evaluator;
};