# SABA Reflex

**Smart Automated Behavioral Assistant** - LLM-powered Conditional Automation Framework

> ⚠️ **BETA OF BETA VERSION** - This project is in early development stage. Features and APIs may change.

SABA Reflex is a lightweight automation framework that automatically performs tasks in response to schedules, events, or sensor data. LLM (Claude) analyzes situations and invokes appropriate tools to execute tasks.

## 🌟 Key Features

- **⏰ Schedule-based Automation**: Execute periodic tasks with cron expressions
- **🤖 LLM-powered Decision Making**: Claude analyzes situations and selects appropriate tools
- **🔧 MCP Protocol Support**: Control devices/services via Model Context Protocol
- **🔌 MQTT Communication**: Real-time communication with IoT devices
- **📦 Lifecycle Management**: Automatic management of one-time/persistent reflexes

## 📋 Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Example](#example)
- [Configuration](#configuration)

## 🚀 Installation

### Requirements

- Python 3.10+
- Anthropic API Key
- MQTT Broker (optional)

### Installation Steps

```bash
# Clone the repository
git clone https://github.com/your-org/saba-reflex.git
cd saba-reflex

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export ANTHROPIC_API_KEY=your_api_key_here
```

### Run MCP Bridge (Optional)

```bash
# For MQTT-based device control
cd bridge
python bridge_mcp.py
```

## ⚡ Quick Start

### Basic Example

```python
# main.py
import asyncio
from reflex.core.engine import ReflexEngine
from reflex.core.state import WorldState
from reflex.core.reflex import Reflex
from reflex.core.lifecycle import Lifecycle
from reflex.triggers.schedule import ScheduleTrigger
from reflex.actions.llm import LLMAction
from reflex.tools.registry import ToolRegistry

async def main():
    # 1. Initialize
    tool_registry = ToolRegistry(mcp_bridge_url="http://localhost:8083")
    state = WorldState()
    engine = ReflexEngine(tool_registry, state)
    
    # 2. Create Reflex
    morning_routine = Reflex(
        id="morning_routine",
        name="Morning Routine",
        trigger=ScheduleTrigger({
            'type': 'schedule',
            'cron': '0 7 * * *'  # Every day at 7 AM
        }),
        action=LLMAction({
            'messages': [
                {'role': 'system', 'content': 'You are a smart home management AI.'},
                {'role': 'user', 'content': 'Execute morning routine. Open curtains and turn on lights.'}
            ]
        }),
        tools=['curtain_control', 'light_control'],
        lifecycle=Lifecycle(type='persistent')
    )
    
    engine.add_reflex(morning_routine)
    
    # 3. Start engine
    await engine.start()

if __name__ == "__main__":
    asyncio.run(main())
```

Run:
```bash
python main.py
```

## 📚 Example

### Plant Care Automation

```python
plant_care = Reflex(
    id="plant_care",
    name="Automated Plant Care",
    trigger=ScheduleTrigger({
        'type': 'schedule',
        'cron': '0 9 * * *'  # Daily at 9 AM
    }),
    action=LLMAction({
        'messages': [
            {'role': 'system', 'content': 'You are a plant care expert.'},
            {'role': 'user', 'content': '''
Current time: 9 AM
Task: Check plant health and water if necessary.
            '''}
        ]
    }),
    tools=['check_plant_health', 'water_pump'],
    lifecycle=Lifecycle(type='persistent')
)
```

## ⚙️ Configuration

### Environment Variables

```bash
# Required
export ANTHROPIC_API_KEY=your_api_key

# Optional (when using MCP Bridge)
export MQTT_BROKER=localhost
export MQTT_PORT=1883
export MCP_BRIDGE_URL=http://localhost:8083
```

### MCP Bridge Configuration

Configure MQTT in `bridge/bridge_mcp.py`:

```python
MQTT_BROKER = os.getenv('MQTT_BROKER', 'localhost')
MQTT_PORT = int(os.getenv('MQTT_PORT', 1883))
MQTT_TOPIC_PREFIX = 'saba'
```

### Registry Configuration

```python
# Set MCP Bridge URL
tool_registry = ToolRegistry(
    mcp_bridge_url="http://localhost:8083"
)
```

## 🔧 Debugging

### Enable Logging

```python
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

### Check Reflex Status

```python
# List registered reflexes
reflexes = engine.list_reflexes()
print(reflexes)

# Get specific reflex
reflex = engine.get_reflex("reflex_id")
print(reflex)

# Enable/disable reflex
engine.disable_reflex("reflex_id")
engine.enable_reflex("reflex_id")
```

## 🤝 Contributing

Contributions are always welcome!

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

MIT License

## 🙋 FAQ

### Q: Can I use it without MCP Bridge?
A: Yes! You can register custom tools directly. MCP Bridge is only for MQTT device control.

### Q: Can I use other LLMs?
A: Currently only Claude is supported, but you can extend `LLMAction` to add other LLMs.

### Q: Can I add/remove reflexes dynamically?
A: Yes! You can manage them at runtime using `engine.add_reflex()` and `engine.remove_reflex()`.

### Q: What happens when an error occurs?
A: The reflex remains active and will retry at the next trigger time. Check logs for errors.

## 📞 Support

- Issues: [GitHub Issues](https://github.com/your-org/saba-reflex/issues)
- Discussions: [GitHub Discussions](https://github.com/your-org/saba-reflex/discussions)

---

Made with ❤️ by SABA Team
