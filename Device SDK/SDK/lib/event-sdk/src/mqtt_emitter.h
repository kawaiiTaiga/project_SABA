#pragma once
#include <ArduinoJson.h>
#include <PubSubClient.h>
#include "obs_emitter.h"
#include "transports/topics.h"   // topicEvents(device_id) helper

// Emits ObservationBuilder payloads to MQTT /events topic.
class MqttObservationEmitter : public IObservationEmitter {
public:
  MqttObservationEmitter(PubSubClient& mqtt, const String& device_id, const String& http_base)
  : mqtt_(mqtt), device_id_(device_id), http_base_(http_base) {}

  void set_http_base(const String& http_base){ http_base_ = http_base; }
  void set_device_id(const String& did){ device_id_ = did; }

  void emit(const ObservationBuilder& ob) override {
    String eventsJson = ob.toJson();
    patchAssetUrls(eventsJson);
    mqtt_.publish(topicEvents(device_id_).c_str(), eventsJson.c_str());
  }

private:
  void patchAssetUrls(String& eventsJson){
    StaticJsonDocument<2048> tmp;
    auto err = deserializeJson(tmp, eventsJson);
    if (err == DeserializationError::Ok) {
      JsonArray assets = tmp["result"]["assets"];
      if (!assets.isNull()) {
        for (JsonObject a : assets) {
          const char* url = a["url"] | nullptr;
          if (url && url[0] == '/') {
            a["url"] = http_base_ + String(url);
          }
        }
        String patched; serializeJson(tmp, patched);
        eventsJson = patched;
      }
    }
  }

  PubSubClient& mqtt_;
  String device_id_;
  String http_base_;
};
