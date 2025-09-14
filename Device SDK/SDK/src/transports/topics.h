#pragma once
#include <Arduino.h>
inline String topicAnnounce(const String& id){ return String("mcp/dev/")+id+ "/announce"; }
inline String topicStatus  (const String& id){ return String("mcp/dev/")+id+ "/status"; }
inline String topicCmd     (const String& id){ return String("mcp/dev/")+id+ "/cmd"; }
inline String topicEvents  (const String& id){ return String("mcp/dev/")+id+ "/events"; }