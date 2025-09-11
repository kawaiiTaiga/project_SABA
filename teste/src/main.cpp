// src/main.cpp
#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <DNSServer.h>
#include <Preferences.h>
#include <ArduinoJson.h>
#include <PubSubClient.h>
#include "esp_camera.h"

// ====== [0] Fixed Info ======
static const char* DEVICE_NAME   = "esp32cam-mcp-lite";
static const char* FW_VERSION    = "0.2.1-fixed";
static const uint16_t HTTP_PORT  = 80;

// ====== [1] ESP32-CAM (AI-Thinker) Pins ======
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
static const int FLASH_PIN = 4;

// ====== [2] Runtime Globals ======
enum RunMode { MODE_PROVISION, MODE_RUN };
RunMode RUN_MODE = MODE_PROVISION;

WebServer server(HTTP_PORT);
DNSServer dnsServer;
Preferences prefs;

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

String http_base;             // "http://<ip>"
unsigned long lastStatusMs = 0;
unsigned long lastAnnounceMs = 0;   // periodic re-announce timer

// Last captured frame in RAM
static uint8_t* last_jpeg = nullptr;
static size_t   last_len  = 0;
static String   last_id;

// Config (provisioned)
String CFG_WIFI_SSID;
String CFG_WIFI_PASS;
String CFG_MQTT_HOST;
uint16_t CFG_MQTT_PORT = 1883;
String CFG_DEVICE_ID;

// ====== [3] Utils ======
String isoNow() {
  time_t now = time(nullptr);
  struct tm* t = gmtime(&now);
  char buf[32];
  if (t) strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", t);
  else   snprintf(buf, sizeof(buf), "0");
  return String(buf);
}

String uuidLike() {
  char buf[32];
  snprintf(buf, sizeof(buf), "%08lX%08lX",
           (unsigned long)millis(),
           (unsigned long)esp_random());
  return String(buf);
}

String macTailDeviceId() {
  uint8_t mac[6]; WiFi.macAddress(mac);
  char buf[32];
  snprintf(buf, sizeof(buf), "dev-%02X%02X%02X", mac[3], mac[4], mac[5]);
  return String(buf);
}

// 문자열 기반 flash 파싱 ("on"/"off", 하위호환: true/false, 1/0, yes/no)
bool flashOnFrom(const String& v) {
  String s = v; s.toLowerCase();
  if (s == "on" || s == "1" || s == "true" || s == "yes") return true;
  if (s == "off" || s == "0" || s == "false" || s == "no") return false;
  return false; // 기본값: off
}

// ====== [4] NVS Config ======
void loadConfig() {
  prefs.begin("mcp", true);
  CFG_WIFI_SSID = prefs.getString("wifi_ssid", "");
  CFG_WIFI_PASS = prefs.getString("wifi_pass", "");
  CFG_MQTT_HOST = prefs.getString("mqtt_host", "");
  CFG_MQTT_PORT = prefs.getUShort("mqtt_port", 1883);  // 16-bit OK
  CFG_DEVICE_ID = prefs.getString("device_id", "");
  prefs.end();

  if (CFG_DEVICE_ID.length() == 0) {
    CFG_DEVICE_ID = macTailDeviceId();
  }
}

void saveConfig(const String& ssid, const String& pass,
                const String& host, uint16_t port,
                const String& did) {
  prefs.begin("mcp", false);
  prefs.putString("wifi_ssid", ssid);
  prefs.putString("wifi_pass", pass);
  prefs.putString("mqtt_host", host);
  prefs.putUShort("mqtt_port", port);  // 16-bit OK
  prefs.putString("device_id", did);
  prefs.end();
}

void clearConfig() {
  prefs.begin("mcp", false);
  prefs.clear();
  prefs.end();
}

// ====== [5] Camera ======
bool cameraInitOnce() {
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
  config.frame_size   = FRAMESIZE_VGA; // default mid
  config.jpeg_quality = 12;
  config.fb_count     = 1;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed: 0x%x\n", err);
    return false;
  }
  sensor_t* s = esp_camera_sensor_get();
  if (s) {
    s->set_brightness(s, 0);
    s->set_saturation(s, 0);
    s->set_whitebal(s, 1);
  }
  pinMode(FLASH_PIN, OUTPUT);
  digitalWrite(FLASH_PIN, LOW);
  return true;
}

void setQualityAndSize(const String& q) {
  sensor_t* s = esp_camera_sensor_get();
  if (!s) return;
  if      (q == "low")  { s->set_framesize(s, FRAMESIZE_QVGA); s->set_quality(s, 20); }
  else if (q == "high") { s->set_framesize(s, FRAMESIZE_SVGA); s->set_quality(s, 10); }
  else                  { s->set_framesize(s, FRAMESIZE_VGA);  s->set_quality(s, 12); }
}

// --- FIX #1: 리컨피그 후 워밍업 프레임 버리기 ---
static void warmupFrames(int count = 2, int delayMs = 30) {
  for (int i = 0; i < count; i++) {
    camera_fb_t* warm = esp_camera_fb_get();
    if (warm) esp_camera_fb_return(warm);
    delay(delayMs);
  }
}

// --- FIX #2: 실제 캡처 (flash 문자열 모드) ---
bool captureToLast(const String& quality, const String& flashMode) {
  setQualityAndSize(quality);

  // 리컨피그 직후 "이전/불안정 프레임" 제거
  warmupFrames(2, 30);

  const bool flashOn = flashOnFrom(flashMode);
  if (flashOn) digitalWrite(FLASH_PIN, HIGH);

  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    if (flashOn) digitalWrite(FLASH_PIN, LOW);
    Serial.println("[CAPTURE] camera_fb_get failed");
    return false;
  }

  uint8_t* newbuf = (uint8_t*)malloc(fb->len);
  if (!newbuf) {
    if (flashOn) digitalWrite(FLASH_PIN, LOW);
    esp_camera_fb_return(fb);
    Serial.println("[CAPTURE] malloc failed");
    return false;
  }
  memcpy(newbuf, fb->buf, fb->len);
  size_t newlen = fb->len;

  esp_camera_fb_return(fb);
  if (flashOn) digitalWrite(FLASH_PIN, LOW);

  if (last_jpeg) { free(last_jpeg); last_jpeg = nullptr; }
  last_jpeg = newbuf;
  last_len  = newlen;
  last_id   = uuidLike();

  Serial.printf("[CAPTURE] stored last.jpg (%u bytes), id=%s, flash=%s\n",
                (unsigned)newlen, last_id.c_str(), flashOn ? "on" : "off");
  return true;
}

// ====== [6] Runtime HTTP (RUN mode) ======
void handle_last() {
  if (!last_jpeg || last_len == 0) {
    server.send(404, "application/json", "{\"error\":\"no last image\"}");
    return;
  }

  // --- FIX #3: 강력 캐시 무효화 ---
  server.sendHeader("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0");
  server.sendHeader("Pragma", "no-cache");
  server.sendHeader("Expires", "0");

  server.setContentLength(last_len);
  server.send(200, "image/jpeg", "");
  WiFiClient client = server.client();
  client.write(last_jpeg, last_len);
}

void handle_capture_now() { // quick manual test
  String quality = server.hasArg("quality") ? server.arg("quality") : "mid";
  String flashMode = server.hasArg("flash") ? server.arg("flash") : "off"; // "on" | "off" (기본 off)
  if (!captureToLast(quality, flashMode)) {
    server.send(500, "application/json", "{\"error\":\"capture failed\"}");
    return;
  }
  handle_last(); // 재사용 (헤더 포함)
}

String topicAnnounce() { return String("mcp/dev/") + CFG_DEVICE_ID + "/announce"; }
String topicStatus()   { return String("mcp/dev/") + CFG_DEVICE_ID + "/status"; }

// Clear retained announce/status on the broker
void clearRetainedOnBroker() {
  if (!mqtt.connected()) return;
  mqtt.publish(topicAnnounce().c_str(), (const uint8_t*)"", 0, true); // empty retained
  mqtt.publish(topicStatus().c_str(),   (const uint8_t*)"", 0, true); // empty retained
  Serial.println("[MQTT] cleared retained announce/status on broker");
}

void handle_clear_retained() {
  if (!mqtt.connected()) {
    server.send(503, "text/plain", "MQTT not connected");
    return;
  }
  clearRetainedOnBroker();
  server.send(200, "text/plain", "Cleared retained announce/status");
}

void handle_factory_reset() {
  clearConfig();
  if (mqtt.connected()) clearRetainedOnBroker();
  server.send(200, "text/plain", "Factory reset done. Rebooting...");
  delay(800);
  ESP.restart();
}

// ====== [7] MQTT (RUN mode) ======
String topicCmd()      { return String("mcp/dev/") + CFG_DEVICE_ID + "/cmd"; }
String topicEvents()   { return String("mcp/dev/") + CFG_DEVICE_ID + "/events"; }

void publishAnnounceRetained() {
  StaticJsonDocument<768> doc;
  doc["type"] = "device.announce";
  doc["device_id"] = CFG_DEVICE_ID;
  doc["name"] = DEVICE_NAME;
  doc["version"] = FW_VERSION;
  doc["http_base"] = http_base;

  JsonArray tools = doc.createNestedArray("tools");
  JsonObject tool = tools.createNestedObject();
  tool["name"] = "capture_image";
  tool["description"] = "Capture image (quality: low|mid|high, flash: on|off) ";
  JsonObject params = tool.createNestedObject("parameters");
  params["type"] = "object";
  JsonObject props = params.createNestedObject("properties");
  {
    JsonObject qobj = props.createNestedObject("quality");
    JsonArray qenum = qobj.createNestedArray("enum");
    qenum.add("low"); qenum.add("mid"); qenum.add("high");
  }
  {
    JsonObject fobj = props.createNestedObject("flash");
    fobj["type"] = "string";
    JsonArray fenum = fobj.createNestedArray("enum");
    fenum.add("on"); fenum.add("off");
  }
  JsonArray req = params.createNestedArray("required");
  req.add("quality"); req.add("flash");

  char buf[1024];
  size_t n = serializeJson(doc, buf, sizeof(buf));
  mqtt.publish(topicAnnounce().c_str(),
               reinterpret_cast<const uint8_t*>(buf),
               n, true);
  Serial.println("[MQTT] announce (retain) sent");
}

void publishStatus(bool online) {
  StaticJsonDocument<256> doc;
  doc["type"] = "device.status";
  doc["device_id"] = CFG_DEVICE_ID;
  doc["online"] = online;
  doc["uptime_ms"] = (uint32_t)millis();
  doc["rssi"] = (int)WiFi.RSSI();
  doc["ts"] = isoNow();

  char buf[384];
  size_t n = serializeJson(doc, buf, sizeof(buf));
  mqtt.publish(topicStatus().c_str(),
               reinterpret_cast<const uint8_t*>(buf),
               n, false);
}

bool mqttConnect() {
  mqtt.setServer(CFG_MQTT_HOST.c_str(), CFG_MQTT_PORT);
  mqtt.setCallback([](char* /*topic*/, byte* payload, unsigned int length){
    StaticJsonDocument<768> doc;
    DeserializationError e = deserializeJson(doc, payload, length);
    if (e) { Serial.println("JSON parse error"); return; }

    const char* type = doc["type"] | "";
    if (strcmp(type, "device.command") != 0) return;

    const char* rid = doc["request_id"] | "";
    String request_id = (rid && rid[0]) ? String(rid) : uuidLike();

    const char* tname = doc["tool"] | "";
    String tool = String(tname);

    if (tool != "capture_image") {
      StaticJsonDocument<256> errd;
      errd["type"] = "device.observation";
      errd["request_id"] = request_id;
      errd["ok"] = false;
      JsonObject er = errd.createNestedObject("error");
      er["code"] = "unsupported_tool";
      er["message"] = "only capture_image is supported";
      char b[384]; size_t n = serializeJson(errd, b, sizeof(b));
      mqtt.publish(topicEvents().c_str(), reinterpret_cast<const uint8_t*>(b), n, false);
      return;
    }

    const char* q = doc["args"]["quality"] | "mid";
    String quality = String(q);

    // flash는 문자열(on/off)로 우선 읽고, 불리언/정수면 하위호환 변환
    String flashMode = "off";
    if (doc["args"]["flash"].is<const char*>()) {
      flashMode = String((const char*)doc["args"]["flash"]);
    } else if (doc["args"]["flash"].is<bool>()) {
      flashMode = doc["args"]["flash"].as<bool>() ? "on" : "off";
    } else if (doc["args"]["flash"].is<int>()) {
      flashMode = (doc["args"]["flash"].as<int>() != 0) ? "on" : "off";
    }

    if (!captureToLast(quality, flashMode)) {
      StaticJsonDocument<256> errd;
      errd["type"] = "device.observation";
      errd["request_id"] = request_id;
      errd["ok"] = false;
      JsonObject er = errd.createNestedObject("error");
      er["code"] = "camera_error";
      er["message"] = "failed to capture";
      char b[384]; size_t n = serializeJson(errd, b, sizeof(b));
      mqtt.publish(topicEvents().c_str(), reinterpret_cast<const uint8_t*>(b), n, false);
      return;
    }

    // success
    StaticJsonDocument<768> okd;
    okd["type"] = "device.observation";
    okd["request_id"] = request_id;
    okd["ok"] = true;
    JsonObject res = okd.createNestedObject("result");
    res["text"] = "captured";
    JsonArray assets = res.createNestedArray("assets");
    JsonObject a = assets.createNestedObject();
    a["asset_id"] = last_id;
    a["kind"]     = "image";
    a["mime"]     = "image/jpeg";
    String url    = http_base + String("/last.jpg?rid=") + last_id;  // 캐시버스터 포함
    a["url"]      = url;
    char b[1024]; size_t n = serializeJson(okd, b, sizeof(b));
    mqtt.publish(topicEvents().c_str(), reinterpret_cast<const uint8_t*>(b), n, false);
    Serial.println(String("[MQTT] events sent with URL: ") + url);
  });

  // LWT retained (status schema-compatible)
  StaticJsonDocument<256> will;
  will["type"] = "device.status";
  will["device_id"] = CFG_DEVICE_ID;
  will["online"] = false;
  will["uptime_ms"] = (uint32_t)millis();
  will["ts"] = isoNow();
  char willBuf[256];
  size_t willLen = serializeJson(will, willBuf, sizeof(willBuf));
  if (willLen < sizeof(willBuf)) willBuf[willLen] = '\0';

  bool ok = mqtt.connect(
    CFG_DEVICE_ID.c_str(),
    nullptr, nullptr,
    topicStatus().c_str(),
    0,
    true,
    willBuf
  );
  if (ok) {
    Serial.println("[MQTT] connected");
    mqtt.subscribe(topicCmd().c_str());
    publishAnnounceRetained();      // once right after connect
    publishStatus(true);
    lastAnnounceMs = millis();      // periodic timer reset
  }
  return ok;
}

// ====== [8] PROVISION mode ======
String apSsid() {
  uint8_t mac[6]; WiFi.macAddress(mac);
  char ssid[32];
  snprintf(ssid, sizeof(ssid), "MCP-SETUP-%02X%02X", mac[4], mac[5]);
  return String(ssid);
}

String htmlEscape(const String& s) {
  String o; o.reserve(s.length()+8);
  for (char c: s) {
    switch (c) {
      case '&': o += F("&amp;"); break;
      case '<': o += F("&lt;"); break;
      case '>': o += F("&gt;"); break;
      case '"': o += F("&quot;"); break;
      case '\'':o += F("&#39;"); break;
      default: o += c;
    }
  }
  return o;
}

String buildProvisionPage(bool doScan) {
  String body;
  body.reserve(6000);
  body += F("<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>MCP-Lite Setup</title>"
            "<style>body{font-family:sans-serif;max-width:560px;margin:20px auto;padding:0 12px}"
            "label{display:block;margin:.6rem 0 .2rem}input,select{width:100%;padding:.6rem;font-size:1rem}"
            "button{padding:.6rem 1rem;margin-top:1rem}small{color:#666}</style>"
            "</head><body><h2>MCP-Lite Provisioning</h2>");

  if (doScan) {
    int n = WiFi.scanNetworks();
    body += F("<details open><summary>Scan Wi-Fi</summary><label>SSID</label><select id='ssid'>");
    for (int i=0;i<n;i++) {
      String ssid = WiFi.SSID(i);
      int32_t rssi = WiFi.RSSI(i);
      bool enc = WiFi.encryptionType(i) != WIFI_AUTH_OPEN;
      body += "<option value='" + htmlEscape(ssid) + "'>";
      body += htmlEscape(ssid) + " (" + String(rssi) + " dBm";
      body += enc ? ", 🔒" : ", 🔓";
      body += ")</option>";
    }
    if (n<=0) body += F("<option value=''>No networks found (rescan)</option>");
    body += F("</select><button onclick='document.getElementById(\"ssidText\").value=document.getElementById(\"ssid\").value'>Use selected</button></details>");
  } else {
    body += F("<p><a href='/?scan=1'>Scan Wi-Fi</a> (recommended)</p>");
  }

  body += F("<form method='POST' action='/save'>"
            "<label>Wi-Fi SSID</label><input id='ssidText' name='wifi_ssid' required>"
            "<label>Wi-Fi Password</label><input name='wifi_pass' type='password'>"
            "<label>MQTT Host (IP)</label><input name='mqtt_host' value='192.168.0.100' required>"
            "<label>MQTT Port</label><input name='mqtt_port' type='number' value='1883' min='1' max='65535' required>"
            "<label>Device ID</label><input name='device_id' value='");
  body += htmlEscape(CFG_DEVICE_ID.length()? CFG_DEVICE_ID : macTailDeviceId());
  body += F("' required>"
            "<button type='submit'>Save & Reboot</button>"
            "</form><hr>"
            "<p><small>Project sabasegan</small></p>"
            "</body></html>");
  return body;
}

void startProvisioning() {
  RUN_MODE = MODE_PROVISION;
  Serial.println("[PROV] starting SoftAP provisioning");

  WiFi.mode(WIFI_AP);
  String ssid = apSsid();
  WiFi.softAP(ssid.c_str(), "12345678");
  delay(200);
  IPAddress apIP = WiFi.softAPIP();
  Serial.printf("[PROV] AP SSID=%s, IP=%s\n", ssid.c_str(), apIP.toString().c_str());

  // Captive portal DNS
  dnsServer.start(53, "*", apIP);

  server.onNotFound([](){
    if (RUN_MODE == MODE_PROVISION) {
      bool doScan = server.hasArg("scan");
      String html = buildProvisionPage(doScan);
      server.send(200, "text/html; charset=utf-8", html);
    } else {
      server.send(404, "text/plain", "404");
    }
  });

  server.on("/", HTTP_GET, [](){
    String html = buildProvisionPage(server.hasArg("scan"));
    server.send(200, "text/html; charset=utf-8", html);
  });

  // Captive portal probes
  server.on("/generate_204", HTTP_GET, [](){ server.send(204); });
  server.on("/hotspot-detect.html", HTTP_GET, [](){ server.send(200, "text/plain", "OK"); });

  server.on("/save", HTTP_POST, [](){
    String ssid = server.arg("wifi_ssid");
    String pass = server.arg("wifi_pass");
    String host = server.arg("mqtt_host");
    uint16_t port = (uint16_t) server.arg("mqtt_port").toInt();
    String did  = server.arg("device_id");
    if (ssid.length()==0 || host.length()==0 || port==0 || did.length()==0) {
      server.send(422, "text/plain", "Missing required fields");
      return;
    }
    saveConfig(ssid, pass, host, port, did);
    server.send(200, "text/plain", "Saved. Rebooting...");
    delay(800);
    ESP.restart();
  });

  server.begin();
}

// ====== [9] STA + Runtime ======
bool connectSTA(const String& ssid, const String& pass, unsigned long timeoutMs=30000) {
  WiFi.setSleep(false);
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid.c_str(), pass.c_str());
  Serial.printf("[WIFI] connecting to %s", ssid.c_str());
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && (millis() - start < timeoutMs)) {
    delay(500); Serial.print(".");
  }
  Serial.println();
  return WiFi.status() == WL_CONNECTED;
}

void startRuntime() {
  RUN_MODE = MODE_RUN;
  Serial.println("[RUN] entering runtime");

  // NTP (non-blocking; continue even if fail)
  configTime(9*3600, 0, "pool.ntp.org", "time.google.com");

  // HTTP routes
  server.on("/", [](){
    String msg = "OK\n"
      " - /last.jpg (last captured)\n"
      " - /capture.jpg?quality=low|mid|high&flash=on|off (capture now)\n"
      " - /clear_retained (clear retained announce/status on broker)\n"
      " - /factory_reset (clear NVS + retained, reboot to provisioning)\n"
      " - /reannounce (re-publish announce with retain)\n"
      " - /status_now (publish immediate status)\n";
    server.sendHeader("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0");
    server.sendHeader("Pragma", "no-cache");
    server.sendHeader("Expires", "0");
    server.send(200, "text/plain", msg);
  });
  server.on("/last.jpg", HTTP_GET, handle_last);
  server.on("/capture.jpg", HTTP_GET, handle_capture_now);
  server.on("/clear_retained", HTTP_GET, handle_clear_retained);
  server.on("/factory_reset", HTTP_GET, handle_factory_reset);

  // re-announce & immediate status
  server.on("/reannounce", HTTP_GET, [](){
    if (!mqtt.connected()) { server.send(503, "text/plain", "MQTT not connected"); return; }
    publishAnnounceRetained();
    lastAnnounceMs = millis();
    server.send(200, "text/plain", "Re-announced (retain) sent");
  });
  server.on("/status_now", HTTP_GET, [](){
    if (!mqtt.connected()) { server.send(503, "text/plain", "MQTT not connected"); return; }
    publishStatus(true);
    server.send(200, "text/plain", "Status published");
  });

  server.begin();

  // Camera
  if (!cameraInitOnce()) {
    Serial.println("[RUN] camera init failed, reboot...");
    delay(1500); ESP.restart();
  }

  // MQTT
  mqtt.setBufferSize(2048);
  if (!mqttConnect()) {
    Serial.println("[RUN] mqtt connect failed (will retry in loop)");
  }
}

// ====== [A] setup/loop ======
void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n=== ESP32-CAM MCP-Lite (Provisioning + Eager Capture, FIXED) ===");

  loadConfig();

  // No config → Provision
  bool hasConfig = CFG_WIFI_SSID.length() && CFG_MQTT_HOST.length();
  if (!hasConfig) {
    startProvisioning();
    return;
  }

  // Config exists → try STA, else fallback to provisioning
  if (!connectSTA(CFG_WIFI_SSID, CFG_WIFI_PASS)) {
    Serial.println("[WIFI] connect failed, fallback to provisioning");
    startProvisioning();
    return;
  }

  IPAddress ip = WiFi.localIP();
  http_base = String("http://") + ip.toString();
  Serial.printf("[WIFI] OK, IP=%s\n", ip.toString().c_str());

  startRuntime();
}

void loop() {
  if (RUN_MODE == MODE_PROVISION) {
    dnsServer.processNextRequest();
    server.handleClient();
    return;
  }

  // RUN mode
  server.handleClient();

  if (WiFi.status() != WL_CONNECTED) {
    static unsigned long lastWifiTry=0;
    if (millis()-lastWifiTry > 5000) {
      lastWifiTry = millis();
      WiFi.reconnect();
    }
  }

  if (!mqtt.connected()) {
    static unsigned long lastTry = 0;
    if (millis() - lastTry > 3000) {
      lastTry = millis();
      mqttConnect();
    }
  } else {
    mqtt.loop();

    // periodic status (30s)
    if (millis() - lastStatusMs > 30000UL) {
      lastStatusMs = millis();
      publishStatus(true);
    }

    // periodic re-announce (5min)
    if (millis() - lastAnnounceMs > 300000UL) { // 5 * 60 * 1000
      lastAnnounceMs = millis();
      publishAnnounceRetained();
    }
  }
}
