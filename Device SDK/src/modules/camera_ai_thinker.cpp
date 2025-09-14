
#include "camera_ai_thinker.h"

extern String http_base;
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

CameraAiThinker::CameraAiThinker(int flashPin): _flash(flashPin) {}

bool CameraAiThinker::init(){
  Serial.println("[CAM] init AI-Thinker");
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0       = Y2_GPIO_NUM;
  config.pin_d1       = Y3_GPIO_NUM;
  config.pin_d2       = Y4_GPIO_NUM;
  config.pin_d3       = Y5_GPIO_NUM;
  config.pin_d4       = Y6_GPIO_NUM;
  config.pin_d5       = Y7_GPIO_NUM;
  config.pin_d6       = Y8_GPIO_NUM;
  config.pin_d7       = Y9_GPIO_NUM;
  config.pin_xclk     = XCLK_GPIO_NUM;
  config.pin_pclk     = PCLK_GPIO_NUM;
  config.pin_vsync    = VSYNC_GPIO_NUM;
  config.pin_href     = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn     = PWDN_GPIO_NUM;
  config.pin_reset    = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size   = FRAMESIZE_VGA;
  config.jpeg_quality = 12;
  config.fb_count     = 1;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) { Serial.printf("[CAM] init failed: 0x%x\n", err); return false; }
  pinMode(_flash, OUTPUT);
  digitalWrite(_flash, LOW);
  Serial.println("[CAM] init OK");
  return true;
}

void CameraAiThinker::setQuality(const String& q){
  sensor_t* s = esp_camera_sensor_get();
  if (!s) return;
  if      (q=="low")  { s->set_framesize(s, FRAMESIZE_QVGA); s->set_quality(s,20); }
  else if (q=="high") { s->set_framesize(s, FRAMESIZE_SVGA); s->set_quality(s,10); }
  else                { s->set_framesize(s, FRAMESIZE_VGA);  s->set_quality(s,12); }
}

void CameraAiThinker::warmup(int count,int delayMs){
  for(int i=0;i<count;i++){ if(auto fb=esp_camera_fb_get()){ esp_camera_fb_return(fb);} delay(delayMs); }
}

bool CameraAiThinker::capture(const String& quality, const String& flashMode){
  setQuality(quality);
  warmup(2,30);
  bool on = String(flashMode).equalsIgnoreCase("on");
  if (on) digitalWrite(_flash, HIGH);

  camera_fb_t* fb = esp_camera_fb_get();
  if(!fb){ if(on) digitalWrite(_flash, LOW); Serial.println("[CAM] capture failed"); return false; }
  if(_last){ free(_last); _last=nullptr; _lastLen=0; }
  _last=(uint8_t*)malloc(fb->len);
  if(!_last){ esp_camera_fb_return(fb); if(on) digitalWrite(_flash, LOW); Serial.println("[CAM] malloc failed"); return false; }
  memcpy(_last, fb->buf, fb->len);
  _lastLen = fb->len;
  _lastId = String(millis(),HEX) + String((uint32_t)esp_random(), HEX);
  esp_camera_fb_return(fb);
  if (on) digitalWrite(_flash, LOW);
  Serial.printf("[CAM] captured %u bytes id=%s\n", (unsigned)_lastLen, _lastId.c_str());
  return true;
}

void CameraAiThinker::describe(JsonObject& tool){
  tool["name"]=name();
  tool["description"]="Capture image (quality: low|mid|high, flash: on|off)";
  JsonObject params=tool.createNestedObject("parameters");
  params["type"]="object";
  JsonObject props=params.createNestedObject("properties");
  JsonArray qenum=props.createNestedObject("quality").createNestedArray("enum");
  qenum.add("low"); qenum.add("mid"); qenum.add("high");
  JsonArray fenum=props.createNestedObject("flash").createNestedArray("enum");
  fenum.add("on"); fenum.add("off");
  JsonArray req=params.createNestedArray("required");
  req.add("quality"); req.add("flash");
}

bool CameraAiThinker::invoke(JsonObjectConst args, ObservationBuilder& out){
  String q=args["quality"]|"mid";
  String f=args["flash"]|"off";
  Serial.printf("[CAM] invoke quality=%s flash=%s\n", q.c_str(), f.c_str());
  if(!capture(q,f)){ out.error("camera_error","failed to capture"); return false; }

  out.success("captured");
  JsonObject a = out.addAsset();
  a["asset_id"] = _lastId;
  a["kind"]     = "image";
  a["mime"]     = "image/jpeg";
  a["url"]      = http_base + String("/last.jpg?rid=") + _lastId;
  return true;
}


void CameraAiThinker::register_http(WebServer& srv){
  srv.on("/last.jpg", HTTP_GET, [this,&srv](){
    if (!this->hasLast()) { srv.send(404, "application/json", "{\"error\":\"no last image\"}"); return; }
    srv.sendHeader("Cache-Control","no-store, no-cache, must-revalidate, max-age=0");
    srv.sendHeader("Pragma","no-cache"); srv.sendHeader("Expires","0");
    srv.setContentLength(this->lastLen());
    srv.send(200, "image/jpeg", "");
    WiFiClient c = srv.client();
    c.write(this->lastBuf(), this->lastLen());
  });
}
