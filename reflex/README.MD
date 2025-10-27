# SABA Reflex

**Smart Automated Behavioral Assistant** - LLM-powered Conditional Automation Framework

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
- [Core Concepts](#core-concepts)
- [Examples](#examples)
- [Architecture](#architecture)
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

## 💡 Core Concepts

### Reflex

A **Reflex** is a combination of `Trigger` + `Action` + `Tools`.

```python
reflex = Reflex(
    id="unique_id",
    name="Display Name",
    trigger=ScheduleTrigger(...),  # When to execute
    action=LLMAction(...),          # What to do
    tools=['tool1', 'tool2'],       # Which tools to use
    lifecycle=Lifecycle(...)        # How long to maintain
)
```

### Trigger

Detects conditions and activates reflexes.

#### ScheduleTrigger
```python
ScheduleTrigger({
    'type': 'schedule',
    'cron': '0 9 * * *'  # Daily at 9 AM
})
```

Cron Expression Examples:
- `* * * * *` - Every minute
- `0 * * * *` - Every hour (on the hour)
- `0 9 * * *` - Daily at 9 AM
- `0 9 * * 1` - Every Monday at 9 AM
- `*/5 * * * *` - Every 5 minutes

### Action

Performs the actual work.

#### LLMAction

LLM analyzes the situation and invokes tools.

```python
# Simple command
LLMAction({
    'messages': [
        {'role': 'user', 'content': 'Execute the motor tool.'}
    ]
})

# With system prompt
LLMAction({
    'messages': [
        {'role': 'system', 'content': 'You are a helpful assistant.'},
        {'role': 'user', 'content': 'Check the plant health and water if needed.'}
    ],
    'temperature': 0.7
})

# Few-shot example
LLMAction({
    'messages': [
        {'role': 'system', 'content': 'You control smart home devices.'},
        {'role': 'user', 'content': 'Turn on the lights.'},
        {'role': 'assistant', 'content': 'I\'ll use the light_control tool.'},
        {'role': 'user', 'content': 'Now close the curtains.'}
    ]
})
```

#### MeowAction

Simple action for logging/notifications.

```python
MeowAction({
    'type': 'meow',
    'message': 'Task completed! 🎉'
})
```

### Lifecycle

Manages reflex lifespan.

```python
# Persistent (runs indefinitely)
Lifecycle(type='persistent')

# Temporary (expires after 10 minutes, max 5 runs)
Lifecycle(
    type='temporary',
    ttl_sec=600,
    max_runs=5
)
```

## 📚 Examples

### Example 1: Plant Care Automation

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

### Example 2: Temperature-based Control

```python
temperature_control = Reflex(
    id="temp_control",
    name="Auto Temperature Control",
    trigger=ScheduleTrigger({
        'type': 'schedule',
        'cron': '*/10 * * * *'  # Every 10 minutes
    }),
    action=LLMAction({
        'messages': [
            {'role': 'system', 'content': 'Turn on the fan if temperature exceeds 25°C.'},
            {'role': 'user', 'content': 'Check current temperature and take necessary action.'}
        ]
    }),
    tools=['read_temperature', 'fan_control'],
    lifecycle=Lifecycle(type='persistent')
)
```

### Example 3: Reminder Scheduler

```python
reminder = Reflex(
    id="reminder",
    name="Water Drinking Reminder",
    trigger=ScheduleTrigger({
        'type': 'schedule',
        'cron': '0 */2 * * *'  # Every 2 hours
    }),
    action=MeowAction({
        'type': 'meow',
        'message': '💧 Time to drink water!'
    }),
    tools=[],
    lifecycle=Lifecycle(
        type='temporary',
        ttl_sec=28800,  # 8 hours
        max_runs=4
    )
)
```

### Example 4: Multi-device Control

```python
good_night = Reflex(
    id="good_night",
    name="Good Night Routine",
    trigger=ScheduleTrigger({
        'type': 'schedule',
        'cron': '0 23 * * *'  # Daily at 11 PM
    }),
    action=LLMAction({
        'messages': [
            {'role': 'system', 'content': 'You are an AI that helps with bedtime preparation.'},
            {'role': 'user', 'content': '''
Execute good night routine:
1. Turn off all lights
2. Close curtains
3. Set AC to 22°C
            '''}
        ]
    }),
    tools=['light_control', 'curtain_control', 'ac_control'],
    lifecycle=Lifecycle(type='persistent')
)
```

## 🏗️ Architecture

```
saba-reflex/
├── reflex/
│   ├── core/
│   │   ├── engine.py          # Reflex execution engine
│   │   ├── reflex.py          # Reflex definition
│   │   ├── lifecycle.py       # Lifecycle management
│   │   └── state.py           # Global state management
│   ├── triggers/
│   │   ├── base.py            # Trigger base class
│   │   └── schedule.py        # Schedule trigger
│   ├── actions/
│   │   ├── base.py            # Action base class
│   │   ├── llm.py             # LLM action
│   │   └── meow.py            # Simple notification action
│   └── tools/
│       └── registry.py        # MCP tool registry
├── bridge/
│   └── bridge_mcp.py          # MCP Bridge (MQTT integration)
├── main.py                    # Main entry point
└── requirements.txt
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


