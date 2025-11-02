#pragma once
#include "tool.h"
#include "obs_emitter.h"

// Minimal base for EVENT-only tools.
// Provides: describe() with kind=event, subscribe/unsubscribe routing, emit helper, and optional tick().
class EventTool : public ITool {
public:
  explicit EventTool(const char* tool_name, const char* desc="") : name_(tool_name), desc_(desc) {}
  virtual ~EventTool() {}

  bool init() override { return onInit(); }
  const char* name() const override { return name_; }

  void describe(JsonObject& tool) override {
    tool["name"] = name();
    tool["description"] = desc_;
    tool["kind"] = "event";

    // Capabilities
    auto caps = tool.createNestedObject("capabilities");
    caps["subscribe"] = true;
    caps["unsubscribe"] = true;

    // Parameters schema (default: op enum subscribe/unsubscribe)
    auto params = tool.createNestedObject("parameters");
    params["type"] = "object";
    auto props = params.createNestedObject("properties");
    props["op"]["type"] = "string";
    auto e = props["op"].createNestedArray("enum");
    e.add("subscribe"); e.add("unsubscribe");
    buildExtraParameters(props);   // let child add fields (e.g., filters/thresholds)
    auto req = params.createNestedArray("required");
    req.add("op");

    // Signals (optional)
    auto sigs = tool.createNestedObject("signals");
    buildSignals(sigs);
  }

  bool invoke(JsonObjectConst args, ObservationBuilder& out) override {
    Serial.printf("[EventTool] invoke called for '%s'\n", name());
    Serial.print("[EventTool] args.size=");
    Serial.println(args.size());
    Serial.print("[EventTool] args content: ");
    serializeJson(args, Serial);
    Serial.println();
    
    // Use containsKey() and getMember() for JsonObjectConst
    if (!args.containsKey("op")) {
      Serial.println("[EventTool] ERROR: 'op' key not found!");
      out.error("bad_request", "op is required"); 
      return false;
    }
    
    const char* op = args["op"].as<const char*>();
    if (!op) {
      Serial.println("[EventTool] ERROR: op is null after as<const char*>()!");
      out.error("bad_request", "op is required"); 
      return false;
    }
    
    Serial.printf("[EventTool] op=%s\n", op);
    
    if (strcmp(op, "subscribe") == 0) {
      Serial.println("[EventTool] Calling onSubscribe...");
      return onSubscribe(args, out);
    }
    if (strcmp(op, "unsubscribe") == 0) {
      Serial.println("[EventTool] Calling onUnsubscribe...");
      return onUnsubscribe(args, out);
    }
    
    Serial.printf("[EventTool] ERROR: unsupported op '%s'\n", op);
    out.error("bad_op", "unsupported op"); 
    return false;
  }

  // Optional periodic work (e.g., debounce/timers). Call from registry_tick_all().
  virtual void tick(uint32_t /*now_ms*/) {}

protected:
  // Child hooks
  virtual bool onInit(){ return true; }
  virtual bool onSubscribe(JsonObjectConst /*args*/, ObservationBuilder& out){ out.error("not_impl","subscribe not implemented"); return false; }
  virtual bool onUnsubscribe(JsonObjectConst /*args*/, ObservationBuilder& out){ out.error("not_impl","unsubscribe not implemented"); return false; }
  virtual void buildExtraParameters(JsonObject& /*props*/) {}
  virtual void buildSignals(JsonObject& /*signals*/) {}

  // Emit helper
  void emitNow(const ObservationBuilder& ob){
    if (auto* e = get_global_emitter()) e->emit(ob);
  }

private:
  const char* name_;
  const char* desc_;
};