#include "hooks.h"
#include "registry.h"
#include "modules/camera_ai_thinker.h"
void register_tools(ToolRegistry& reg, const ToolConfig& cfg){
  auto* cam = new CameraAiThinker(4);
  reg.add(cam);
}