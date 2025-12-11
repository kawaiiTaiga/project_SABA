#include "hooks.h"
#include "registry.h"
#include "port_registry.h"                 // ★ 포트 레지스트리
#include "modules/express_emotion_tool.h"
#include "modules/impact_outport.h"        // 네가 만든 OutPort 구현 헤더들

void register_tools(ToolRegistry& reg, const ToolConfig& cfg) {
  auto* emotion = new ExpressEmotionTool();
  reg.add(emotion);

  auto* playLED = new PlayLEDPatternTool();
  reg.add(playLED);

  auto* stopLED = new StopLEDPatternTool();
  reg.add(stopLED);
}



// ★ 여기서 포트 등록
void register_ports(PortRegistry& reg, const PortConfig& cfg) {
  (void)cfg;

  // 예: 충격 센서 OutPort
  static Counter g_fakeImpact;
  reg.addOutPort(&g_fakeImpact);

  // 예: 범용 InPort들
  reg.createInPort("var_a", "float");
  reg.createInPort("var_b", "float");
  reg.createInPort("var_c", "bool");

  Serial.println("[PORT] register_ports: impact_live + var_a/b/c registered");
}