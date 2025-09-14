
#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <DNSServer.h>
#include <Preferences.h>
#include <ArduinoJson.h>
#include <PubSubClient.h>
#include "esp_camera.h"

#include "config.hpp"
#include "transports/topics.h"
#include "registry.h"
#include "hooks.h"
#include "provisioning_service.h"
#include "tool.h"

static const uint16_t HTTP_PORT_NUM = HTTP_PORT;

enum RunMode { MODE_PROVISION, MODE_RUN };
RunMode RUN_MODE = MODE_PROVISION;

WebServer server(HTTP_PORT_NUM);
DNSServer dnsServer;
Preferences prefs;

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

ToolRegistry registry;

String http_base;
String device_id;
unsigned long lastStatusMs = 0;
unsigned long lastAnnounceMs = 0;

McpConfig CFG;
ProvisioningService* prov = nullptr;

String isoNow() {
  time_t now = time(nullptr);
  struct tm* t = gmtime(&now);
  char buf[32];
  if (t) strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", t);
  else   snprintf(buf, sizeof(buf), "0");
  return String(buf);
}

String macTailDeviceId() {
  uint8_t mac[6]; WiFi.macAddress(mac);
  char buf[32];
  snprintf(buf, sizeof(buf), "dev-%02X%02X%02X", mac[3], mac[4], mac[5]);
  return String(buf);
}

String topicAnn(){ return topicAnnounce(device_id); }
String topicStat(){ return topicStatus(device_id); }
String topicCmdT(){ return topicCmd(device_id); }
String topicEvt(){ return topicEvents(device_id); }

void publishAnnounceRetained() {
  String ann = registry.buildAnnounce(device_id, http_base);
  mqtt.publish(topicAnn().c_str(), ann.c_str(), true);
  Serial.println("[MQTT] announce retain sent");
}

void publishStatus(bool online) {
  StaticJsonDocument<256> doc;
  doc["type"] = "device.status";
  doc["device_id"] = device_id;
  doc["online"] = online;
  doc["uptime_ms"] = (uint32_t)millis();
  doc["rssi"] = (int)WiFi.RSSI();
  doc["ts"] = isoNow();
  String s; serializeJson(doc, s);
  mqtt.publish(topicStat().c_str(), s.c_str());
  Serial.printf("[MQTT] status online=%d rssi=%d\\n", online?1:0, (int)WiFi.RSSI());
}

void clearRetainedOnBroker() {
  if (!mqtt.connected()) return;
  mqtt.publish(topicAnn().c_str(), "", true);
  mqtt.publish(topicStat().c_str(), "", true);
  Serial.println("[MQTT] cleared retained announce/status");
}

bool mqttConnect() {
  mqtt.setServer(CFG.mqtt_host.c_str(), CFG.mqtt_port);
  mqtt.setCallback([](char*, byte* payload, unsigned length){
    StaticJsonDocument<768> cmd;
    if (deserializeJson(cmd, payload, length)) { Serial.println("[MQTT] JSON parse error"); return; }

    String eventsJson;
    if (!registry.dispatch(cmd, eventsJson, http_base)) return;

StaticJsonDocument<2048> tmp;
auto err = deserializeJson(tmp, eventsJson);
if (err == DeserializationError::Ok) {              // <-- 이 조건이 정답
  JsonArray assets = tmp["result"]["assets"];
  if (!assets.isNull()) {
    for (JsonObject a : assets) {
      const char* url = a["url"] | nullptr;
      if (url && url[0] == '/') {                   // 상대경로면 절대경로로
        a["url"] = http_base + String(url);
      }
    }
    String patched; serializeJson(tmp, patched);
    eventsJson = patched;
  }
}

    mqtt.publish(topicEvt().c_str(), eventsJson.c_str());
    Serial.println("[MQTT] events sent");
  });

  StaticJsonDocument<256> will;
  will["type"] = "device.status";
  will["device_id"] = device_id;
  will["online"] = false;
  will["uptime_ms"] = (uint32_t)millis();
  will["ts"] = isoNow();
  char willBuf[256]; size_t willLen = serializeJson(will, willBuf, sizeof(willBuf));
  if (willLen < sizeof(willBuf)) willBuf[willLen] = '\\0';

  bool ok = mqtt.connect(device_id.c_str(), nullptr, nullptr, topicStat().c_str(), 0, true, willBuf);
  if (ok) {
    mqtt.subscribe(topicCmdT().c_str());
    publishAnnounceRetained();
    publishStatus(true);
    lastAnnounceMs = millis();
    Serial.println("[MQTT] connected & subscribed");
  } else {
    Serial.println("[MQTT] connect failed");
  }
  return ok;
}

void startProvisioning() {
  RUN_MODE = MODE_PROVISION;
  String did = CFG.device_id.length() ? CFG.device_id : macTailDeviceId();
  prov->startPortal(did);
  Serial.println("[PROV] started portal");
}

void startRuntime() {
  RUN_MODE = MODE_RUN;
  configTime(9*3600, 0, "pool.ntp.org", "time.google.com");

  server.on("/", [](){
    String msg =
      "OK\\n - /clear_retained\\n - /factory_reset\\n - /reannounce\\n - /status_now\\n";
    server.sendHeader("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0");
    server.sendHeader("Pragma", "no-cache");
    server.sendHeader("Expires", "0");
    server.send(200, "text/plain", msg);
  });
  server.on("/clear_retained", HTTP_GET, [](){
    if (!mqtt.connected()) { server.send(503, "text/plain", "MQTT not connected"); return; }
    clearRetainedOnBroker();
    server.send(200, "text/plain", "Cleared retained announce/status");
  });
  server.on("/factory_reset", HTTP_GET, [](){
    prov->clear();
    if (mqtt.connected()) clearRetainedOnBroker();
    server.send(200, "text/plain", "Factory reset done. Rebooting...");
    delay(800); ESP.restart();
  });
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

  for (auto* t : registry.list()) { t->register_http(server); }

  server.begin();
  Serial.printf("[HTTP] server started on :%u\\n", (unsigned)HTTP_PORT);

  mqtt.setBufferSize(2048);
  if (!mqttConnect()) Serial.println("[RUN] mqtt connect will retry");
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\\n=== MCP-Lite (Provisioning + Run, parts) ===");

  prov = new ProvisioningService(server, dnsServer, prefs);
  prov->load(CFG);

  device_id = CFG.device_id.length() ? CFG.device_id : macTailDeviceId();
  Serial.printf("[BOOT] device_id=%s\\n", device_id.c_str());

  ToolConfig tc; register_tools(registry, tc);
  if (!registry.initAll()) Serial.println("[BOOT] some tools failed to init");

  if (!prov->hasMinimum(CFG)) { startProvisioning(); return; }
  if (!prov->connectSTA(CFG.wifi_ssid, CFG.wifi_pass)) { startProvisioning(); return; }

  http_base = String("http://") + WiFi.localIP().toString();
  Serial.printf("[WIFI] IP=%s\\n", WiFi.localIP().toString().c_str());

  startRuntime();
}

void loop() {
  if (RUN_MODE == MODE_PROVISION) {
    dnsServer.processNextRequest();
    server.handleClient();
    return;
  }

  server.handleClient();

  if (WiFi.status() != WL_CONNECTED) {
    static unsigned long lastWifiTry = 0;
    if (millis() - lastWifiTry > 5000) { lastWifiTry = millis(); WiFi.reconnect(); Serial.println("[WIFI] reconnect"); }
  }

  if (!mqtt.connected()) {
    static unsigned long lastTry = 0;
    if (millis() - lastTry > 3000) { lastTry = millis(); mqttConnect(); }
  } else {
    mqtt.loop();
    if (millis() - lastStatusMs > 30000UL) { lastStatusMs = millis(); publishStatus(true); }
    if (millis() - lastAnnounceMs > 300000UL) { lastAnnounceMs = millis(); publishAnnounceRetained(); }
  }
}
