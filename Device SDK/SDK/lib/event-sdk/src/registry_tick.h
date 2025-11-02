#pragma once
#include "registry.h"
#include "event_tool.h"

inline void registry_tick_all(ToolRegistry& reg, uint32_t now_ms){
  for (auto* t : reg.list()){
    t->tick(now_ms);
  }
}