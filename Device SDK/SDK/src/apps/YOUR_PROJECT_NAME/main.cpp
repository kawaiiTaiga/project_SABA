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
#include "obs_emitter.h"
#include "mqtt_emitter.h"
#include "registry_tick.h"

// ========= Constants =========
static const uint16_t HTTP_PORT_NUM = HTTP_PORT;
static const uint32_t MQTT_RECONNECT_INTERVAL = 3000;
static const uint32_t WIFI_RECONNECT_INTERVAL = 5000;
static const uint32_t STATUS_PUBLISH_INTERVAL = 30000;
static const uint32_t ANNOUNCE_PUBLISH_INTERVAL = 300000;

// ========= Run Mode =========
enum RunMode { MODE_PROVISION, MODE_RUN };
RunMode RUN_MODE = MODE_PROVISION;

// ========= Global Objects =========
WebServer server(HTTP_PORT_NUM);
DNSServer dnsServer;
Preferences prefs;
WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);
ToolRegistry registry;

// ========= State Variables =========
String http_base;
String device_id;
McpConfig CFG;
ProvisioningService* prov = nullptr;

// ========= Timing =========
unsigned long lastStatusMs = 0;
unsigned long lastAnnounceMs = 0;
unsigned long lastMqttTry = 0;
unsigned long lastWifiTry = 0;

// ========= Helper Functions =========
String isoNow() {
  time_t now = time(nullptr);
  struct tm* t = gmtime(&now);
  char buf[32];
  if (t) strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", t);
  else   snprintf(buf, sizeof(buf), "1970-01-01T00:00:00Z");
  return String(buf);
}

String macTailDeviceId() {
  uint8_t mac[6]; 
  WiFi.macAddress(mac);
  char buf[32];
  snprintf(buf, sizeof(buf), "dev-%02X%02X%02X", mac[3], mac[4], mac[5]);
  return String(buf);
}

// ========= MQTT Topics =========
inline String topicAnn()  { return topicAnnounce(device_id); }
inline String topicStat() { return topicStatus(device_id); }
inline String topicCmd()  { return topicCmd(device_id); }
inline String topicEvt()  { return topicEvents(device_id); }

// ========= MQTT Publishing =========
void publishAnnounce() {
  if (!mqtt.connected()) return;
  
  String ann = registry.buildAnnounce(device_id, http_base);
  bool ok = mqtt.publish(topicAnn().c_str(), ann.c_str(), true);
  Serial.printf("[MQTT] Announce %s (retain, %u bytes)\n", ok ? "✓" : "✗", ann.length());
  
  if (ok) lastAnnounceMs = millis();
}

void publishStatus(bool online) {
  if (!mqtt.connected()) return;
  
  StaticJsonDocument<256> doc;
  doc["type"] = "device.status";
  doc["device_id"] = device_id;
  doc["online"] = online;
  doc["uptime_ms"] = millis();
  doc["rssi"] = WiFi.RSSI();
  doc["ts"] = isoNow();
  
  String s; 
  serializeJson(doc, s);
  bool ok = mqtt.publish(topicStat().c_str(), s.c_str());
  
  Serial.printf("[MQTT] Status %s (online=%d, rssi=%d)\n", 
                ok ? "✓" : "✗", online, (int)WiFi.RSSI());
  
  if (ok) lastStatusMs = millis();
}

void clearRetainedMessages() {
  if (!mqtt.connected()) return;
  
  mqtt.publish(topicAnn().c_str(), "", true);
  mqtt.publish(topicStat().c_str(), "", true);
  Serial.println("[MQTT] Cleared retained messages");
}

// ========= MQTT Callback =========
void onMqttMessage(char* topic, byte* payload, unsigned int length) {
  Serial.printf("[MQTT] RX %s (%u bytes)\n", topic, length);
  
  // DEBUG: Print raw payload
  Serial.print("[DEBUG] Raw payload: ");
  Serial.write(payload, length);
  Serial.println();
  
  // Parse command
  StaticJsonDocument<768> cmd;
  DeserializationError err = deserializeJson(cmd, payload, length);
  
  if (err) {
    Serial.printf("[MQTT] JSON parse error: %s\n", err.c_str());
    return;
  }
  
  // DEBUG: Print parsed JSON
  Serial.print("[DEBUG] Parsed JSON: ");
  serializeJson(cmd, Serial);
  Serial.println();
  
  const char* cmdType = cmd["type"] | "unknown";
  const char* toolName = cmd["tool"] | "unknown";
  Serial.printf("[MQTT] Type=%s, Tool=%s\n", cmdType, toolName);
  
  // DEBUG: Check if args exists and what's in it
  JsonVariantConst argsVariant = cmd["args"];
  Serial.printf("[DEBUG] args isNull=%d\n", argsVariant.isNull());
  if (!argsVariant.isNull()) {
    Serial.print("[DEBUG] args content: ");
    serializeJson(argsVariant, Serial);
    Serial.println();
  }
  
  // DEBUG: Show registered tools
  Serial.print("[DEBUG] Registered tools: ");
  for (auto* t : registry.list()) {
    Serial.printf("'%s' ", t->name());
  }
  Serial.println();
  
  // Dispatch to tool registry
  String eventsJson;
  bool dispatched = registry.dispatch(cmd, eventsJson, http_base);
  
  if (!dispatched) {
    Serial.println("[MQTT] Dispatch failed (tool not found or error)");
    Serial.printf("[DEBUG] Events response: %s\n", eventsJson.c_str());
    
    // Still publish the error response
    mqtt.publish(topicEvt().c_str(), eventsJson.c_str());
    return;
  }
  
  // Patch asset URLs (relative -> absolute)
  StaticJsonDocument<2048> tmp;
  DeserializationError err2 = deserializeJson(tmp, eventsJson);
  
  if (err2 == DeserializationError::Ok) {
    JsonArray assets = tmp["result"]["assets"];
    if (!assets.isNull()) {
      for (JsonObject a : assets) {
        const char* url = a["url"] | nullptr;
        if (url && url[0] == '/') {
          a["url"] = http_base + String(url);
        }
      }
      serializeJson(tmp, eventsJson);
    }
  }
  
  // Publish response to events topic
  bool pubOk = mqtt.publish(topicEvt().c_str(), eventsJson.c_str());
  Serial.printf("[MQTT] Events %s (%u bytes)\n", pubOk ? "✓" : "✗", eventsJson.length());
}

// ========= MQTT Connection =========
bool mqttConnect() {
  if (mqtt.connected()) return true;
  
  Serial.printf("[MQTT] Connecting to %s:%u...\n", CFG.mqtt_host.c_str(), CFG.mqtt_port);
  
  // Set Last Will & Testament
  StaticJsonDocument<256> will;
  will["type"] = "device.status";
  will["device_id"] = device_id;
  will["online"] = false;
  will["uptime_ms"] = millis();
  will["ts"] = isoNow();
  
  char willBuf[256];
  size_t willLen = serializeJson(will, willBuf, sizeof(willBuf));
  if (willLen >= sizeof(willBuf)) willBuf[sizeof(willBuf)-1] = '\0';
  else willBuf[willLen] = '\0';
  
  // Connect with LWT
  bool ok = mqtt.connect(
    device_id.c_str(),      // client_id
    nullptr,                // username
    nullptr,                // password
    topicStat().c_str(),    // will topic
    0,                      // will qos
    true,                   // will retain
    willBuf                 // will message
  );
  
  if (!ok) {
    Serial.printf("[MQTT] Connect failed (state=%d)\n", mqtt.state());
    return false;
  }
  
  // Subscribe to command topic
  String cmdTopic = topicCmd();
  bool subOk = mqtt.subscribe(cmdTopic.c_str());
  
  Serial.printf("[MQTT] Connected & subscribed to '%s': %s\n", 
                cmdTopic.c_str(), 
                subOk ? "OK" : "FAILED");
  
  // Publish initial messages
  publishAnnounce();
  publishStatus(true);
  
  return true;
}

// ========= HTTP Handlers =========
void setupHttpHandlers() {
  server.on("/", HTTP_GET, [](){
    String msg = "MCP-Lite Device API\n\n"
                 "Endpoints:\n"
                 "  GET  /            - This help\n"
                 "  GET  /status_now  - Publish status immediately\n"
                 "  GET  /reannounce  - Re-publish announce (retain)\n"
                 "  GET  /clear_retained - Clear retained messages\n"
                 "  GET  /factory_reset  - Factory reset & reboot\n";
    
    server.sendHeader("Cache-Control", "no-store, no-cache, must-revalidate");
    server.sendHeader("Pragma", "no-cache");
    server.send(200, "text/plain", msg);
  });
  
  server.on("/status_now", HTTP_GET, [](){
    if (!mqtt.connected()) {
      server.send(503, "text/plain", "MQTT not connected");
      return;
    }
    publishStatus(true);
    server.send(200, "text/plain", "Status published");
  });
  
  server.on("/reannounce", HTTP_GET, [](){
    if (!mqtt.connected()) {
      server.send(503, "text/plain", "MQTT not connected");
      return;
    }
    publishAnnounce();
    server.send(200, "text/plain", "Announce re-published (retain)");
  });
  
  server.on("/clear_retained", HTTP_GET, [](){
    if (!mqtt.connected()) {
      server.send(503, "text/plain", "MQTT not connected");
      return;
    }
    clearRetainedMessages();
    server.send(200, "text/plain", "Retained messages cleared");
  });
  
  server.on("/factory_reset", HTTP_GET, [](){
    prov->clear();
    if (mqtt.connected()) {
      clearRetainedMessages();
      mqtt.disconnect();
    }
    server.send(200, "text/plain", "Factory reset done. Rebooting in 1s...");
    delay(1000);
    ESP.restart();
  });
  
  // Let tools register their HTTP endpoints
  for (auto* t : registry.list()) {
    t->register_http(server);
  }
}

// ========= Provisioning Mode =========
void startProvisioning() {
  RUN_MODE = MODE_PROVISION;
  String did = CFG.device_id.length() ? CFG.device_id : macTailDeviceId();
  
  Serial.println("[PROV] Starting provisioning portal...");
  prov->startPortal(did);
  Serial.println("[PROV] Portal ready. Connect to Wi-Fi SSID shown above.");
}

// ========= Runtime Mode =========
void startRuntime() {
  RUN_MODE = MODE_RUN;
  
  Serial.println("[RUN] Starting runtime mode...");
  
  // Configure NTP
  configTime(9*3600, 0, "pool.ntp.org", "time.google.com");
  
  // Setup HTTP server
  setupHttpHandlers();
  server.begin();
  Serial.printf("[HTTP] Server started on port %u\n", HTTP_PORT_NUM);
  
  // Configure MQTT
  mqtt.setBufferSize(2048);
  mqtt.setServer(CFG.mqtt_host.c_str(), CFG.mqtt_port);
  mqtt.setCallback(onMqttMessage);
  mqtt.setKeepAlive(60);
  
  // Initial MQTT connection
  if (!mqttConnect()) {
    Serial.println("[RUN] MQTT initial connect failed, will retry...");
  }
  
  Serial.println("[RUN] Runtime mode ready");
}

// ========= Setup =========
void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n╔════════════════════════════════════════╗");
  Serial.println("║     MCP-Lite Device Firmware v2.0     ║");
  Serial.println("║   Provisioning + Runtime + Events      ║");
  Serial.println("╚════════════════════════════════════════╝\n");
  
  // Initialize provisioning service
  prov = new ProvisioningService(server, dnsServer, prefs);
  prov->load(CFG);
  
  // Determine device ID
  device_id = CFG.device_id.length() ? CFG.device_id : macTailDeviceId();
  Serial.printf("[BOOT] Device ID: %s\n", device_id.c_str());
  
  // Register tools
  ToolConfig tc;
  register_tools(registry, tc);
  
  bool initOk = registry.initAll();
  Serial.printf("[BOOT] Tool registry: %u tools, init %s\n", 
                registry.list().size(), 
                initOk ? "OK" : "FAILED");
  
  // List registered tools
  Serial.println("[BOOT] Registered tools:");
  for (auto* t : registry.list()) {
    Serial.printf("  - %s\n", t->name());
  }
  
  // Check if we have minimum config
  if (!prov->hasMinimum(CFG)) {
    Serial.println("[BOOT] No config found, starting provisioning...");
    startProvisioning();
    return;
  }
  
  // Try to connect to Wi-Fi
  Serial.printf("[BOOT] Connecting to Wi-Fi '%s'...\n", CFG.wifi_ssid.c_str());
  
  if (!prov->connectSTA(CFG.wifi_ssid, CFG.wifi_pass, 20000)) {
    Serial.println("[BOOT] Wi-Fi connect failed, starting provisioning...");
    startProvisioning();
    return;
  }
  
  // Connected successfully
  IPAddress ip = WiFi.localIP();
  http_base = String("http://") + ip.toString();
  
  Serial.printf("[WIFI] Connected! IP=%s, RSSI=%d dBm\n", 
                ip.toString().c_str(), 
                (int)WiFi.RSSI());
  
  // Setup MQTT observation emitter for EVENT tools
  static MqttObservationEmitter emitter(mqtt, device_id, http_base);
  set_global_emitter(&emitter);
  Serial.println("[EVENT] Observation emitter registered");
  
  // Start runtime
  startRuntime();
}

// ========= Loop =========
void loop() {
  uint32_t now = millis();
  
  // Provisioning mode - just handle captive portal
  if (RUN_MODE == MODE_PROVISION) {
    dnsServer.processNextRequest();
    server.handleClient();
    return;
  }
  
  // Runtime mode
  server.handleClient();
  
  // Wi-Fi reconnect logic
  if (WiFi.status() != WL_CONNECTED) {
    if (now - lastWifiTry >= WIFI_RECONNECT_INTERVAL) {
      lastWifiTry = now;
      Serial.println("[WIFI] Reconnecting...");
      WiFi.reconnect();
    }
    return; // Skip MQTT/events if no Wi-Fi
  }
  
  // MQTT connection management
  if (!mqtt.connected()) {
    if (now - lastMqttTry >= MQTT_RECONNECT_INTERVAL) {
      lastMqttTry = now;
      mqttConnect();
    }
  } else {
    // Process MQTT messages
    mqtt.loop();
    
    // Periodic status publishing
    if (now - lastStatusMs >= STATUS_PUBLISH_INTERVAL) {
      publishStatus(true);
    }
    
    // Periodic announce re-publishing (retain)
    if (now - lastAnnounceMs >= ANNOUNCE_PUBLISH_INTERVAL) {
      publishAnnounce();
    }
  }
  
  // Tick all tools (especially EVENT tools)
  registry_tick_all(registry, now);
}