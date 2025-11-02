#include "registry.h"
#include <Arduino.h>

String ToolRegistry::buildAnnounce(const String& device_id, const String& http_base){
  StaticJsonDocument<1024> doc;
  doc["type"]="device.announce";
  doc["device_id"]=device_id;
  doc["http_base"]=http_base;
  JsonArray arr=doc.createNestedArray("tools");
  for(auto* t:tools){ JsonObject o=arr.createNestedObject(); t->describe(o); }
  String s; serializeJson(doc,s); return s;
}

bool ToolRegistry::dispatch(const JsonDocument& cmd, String& outEventsJson, const String& http_base){
  const char* type=cmd["type"]|"";
  if(strcmp(type,"device.command")!=0) return false;

  String toolName=(const char*)(cmd["tool"]|"");
  String rid=(const char*)(cmd["request_id"]|"");

  JsonVariantConst v = cmd["args"];
  JsonObjectConst args = v.isNull() ? JsonObjectConst() : v.as<JsonObjectConst>();
  
  // DEBUG: Check args
  Serial.printf("[REGISTRY] Dispatch tool='%s', args.isNull=%d\n", toolName.c_str(), v.isNull());
  if (!v.isNull()) {
    Serial.print("[REGISTRY] args size=");
    Serial.println(args.size());
    Serial.print("[REGISTRY] args content: ");
    serializeJson(args, Serial);
    Serial.println();
  }

  ITool* target=nullptr;
  for(auto* t:tools){ if(toolName==t->name()){ target=t; break; } }

  ObservationBuilder ob;
  ob.setRequestId(rid.length()? rid : String(millis(),HEX));

  if(!target){ 
    Serial.printf("[REGISTRY] Tool '%s' not found\n", toolName.c_str());
    ob.error("unsupported_tool","tool not found"); 
    outEventsJson=ob.toJson(); 
    return false; 
  }
  
  Serial.printf("[REGISTRY] Invoking tool '%s'...\n", target->name());
  bool ok = target->invoke(args, ob);
  Serial.printf("[REGISTRY] Tool invoke returned: %s\n", ok ? "true" : "false");
  
  outEventsJson = ob.toJson();
  return ok;
}