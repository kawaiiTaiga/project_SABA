#include "hooks.h"
#include "registry.h"
#include "modules/express_emotion_tool.h"
#include "modules/event_example_tool.h"  // ← 추가

void register_tools(ToolRegistry& reg, const ToolConfig& cfg){
  // ACTION tool
  auto* emotion = new ExpressEmotionTool();
  reg.add(emotion);
  
  // EVENT tool (pin은 사용 안 하지만 생성자 요구)
  auto* digitalEvent = new ExampleDigitalEvent(0);
  reg.add(digitalEvent);
}