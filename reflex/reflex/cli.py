# reflex/cli.py
import click
import os
import shutil
import asyncio
import yaml
from reflex.core.engine import ReflexEngine
from reflex.core.state import WorldState
from reflex.tools.registry import ToolManager
from reflex.core.config import ConfigManager

REFLEX_DIR = "reflexes"
TRASH_DIR = "trashcan"
LOG_DIR = "logs"

@click.group()
def cli():
    """SABA Reflex CLI"""
    pass

@cli.command()
def dashboard():
    """Open the interactive dashboard"""
    from reflex.dashboard import run_dashboard
    run_dashboard()

@cli.command()
def start():
    """Start the Reflex Engine"""
    tool_manager = ToolManager()
    state = WorldState()
    engine = ReflexEngine(tool_manager, state, reflex_dir=REFLEX_DIR, log_dir=LOG_DIR)
    asyncio.run(engine.start())

@cli.group()
def reflex():
    """Manage Reflexes"""
    pass

@reflex.command(name="list")
def list_reflexes():
    """List all active reflexes"""
    if not os.path.exists(REFLEX_DIR):
        click.echo("No reflexes found.")
        return

    files = [f for f in os.listdir(REFLEX_DIR) if f.endswith('.yaml') or f.endswith('.yml')]
    if not files:
        click.echo("No reflexes found.")
        return

    click.echo(f"Found {len(files)} reflexes:")
    for f in files:
        click.echo(f"  - {f}")

@reflex.command(name="add")
def add_reflex():
    """Create a new reflex interactively"""
    import questionary
    from reflex.triggers.base import TriggerBase
    from reflex.actions.base import ActionBase
    import reflex.triggers.schedule
    import reflex.actions.llm
    import reflex.actions.meow
    
    name = questionary.text("Reflex Name (e.g., morning_routine):").ask()
    if not name:
        return
        
    trigger_choices = []
    for t_type, t_cls in TriggerBase._registry.items():
        desc = getattr(t_cls, 'description', 'No description')
        trigger_choices.append(questionary.Choice(title=f"{t_type} - {desc}", value=t_type))
        
    trigger_type = questionary.select("Select Trigger Type:", choices=trigger_choices).ask()
    
    trigger_config = {"type": trigger_type}
    trigger_cls = TriggerBase._registry[trigger_type]
    schema = getattr(trigger_cls, 'schema', {})
    
    for param, config in schema.items():
        desc = config.get('description', param)
        default = config.get('default', '')
        val = questionary.text(f"{desc}:", default=str(default)).ask()
        trigger_config[param] = val

    action_choices = []
    for a_type, a_cls in ActionBase._registry.items():
        desc = getattr(a_cls, 'description', 'No description')
        action_choices.append(questionary.Choice(title=f"{a_type} - {desc}", value=a_type))

    action_type = questionary.select("Select Action Type:", choices=action_choices).ask()
    
    action_config = {"type": action_type}
    action_cls = ActionBase._registry[action_type]
    schema = getattr(action_cls, 'schema', {})
    
    flat_params = {}
    for param, config in schema.items():
        desc = config.get('description', param)
        default = config.get('default', '')
        val = questionary.text(f"{desc}:", default=str(default)).ask()
        flat_params[param] = val
        
    if action_type == 'llm':
        action_config["messages"] = [
            {"role": "system", "content": flat_params.get('system_prompt', '')},
            {"role": "user", "content": flat_params.get('user_prompt', '')}
        ]
    else:
        action_config.update(flat_params)

    tools_str = questionary.text("Tools (comma separated, optional):").ask()
    tools = [t.strip() for t in tools_str.split(',')] if tools_str else []

    lifecycle_type = questionary.select("Lifecycle Type:", choices=["persistent", "temporary"]).ask()
    
    lifecycle_config = {"type": lifecycle_type}
    if lifecycle_type == "temporary":
        ttl = questionary.text("TTL (seconds):", default="3600").ask()
        lifecycle_config["ttl_sec"] = int(ttl)

    template = {
        "id": name,
        "name": name.replace("_", " ").title(),
        "trigger": trigger_config,
        "action": action_config,
        "tools": tools,
        "lifecycle": lifecycle_config
    }
    
    os.makedirs(REFLEX_DIR, exist_ok=True)
    filename = f"{name}.yaml"
    path = os.path.join(REFLEX_DIR, filename)
    
    if os.path.exists(path):
        if not questionary.confirm(f"Reflex '{name}' already exists. Overwrite?").ask():
            click.echo("Cancelled.")
            return

    with open(path, 'w', encoding='utf-8') as f:
        yaml.dump(template, f, sort_keys=False, allow_unicode=True)
    
    click.echo(f"✨ Created reflex: {path}")

@reflex.command(name="remove")
@click.argument("name")
def remove_reflex(name):
    """Move a reflex to trashcan"""
    filename = f"{name}.yaml"
    src = os.path.join(REFLEX_DIR, filename)
    dst = os.path.join(TRASH_DIR, filename)
    
    if not os.path.exists(src):
        src_yml = os.path.join(REFLEX_DIR, f"{name}.yml")
        if os.path.exists(src_yml):
            src = src_yml
            filename = f"{name}.yml"
            dst = os.path.join(TRASH_DIR, filename)
        else:
            click.echo(f"Error: Reflex '{name}' not found.")
            return

    os.makedirs(TRASH_DIR, exist_ok=True)
    shutil.move(src, dst)
    click.echo(f"Moved '{name}' to trashcan.")

@reflex.command(name="restore")
@click.argument("name")
def restore_reflex(name):
    """Restore a reflex from trashcan"""
    filename = f"{name}.yaml"
    src = os.path.join(TRASH_DIR, filename)
    dst = os.path.join(REFLEX_DIR, filename)
    
    if not os.path.exists(src):
        src_yml = os.path.join(TRASH_DIR, f"{name}.yml")
        if os.path.exists(src_yml):
            src = src_yml
            filename = f"{name}.yml"
            dst = os.path.join(REFLEX_DIR, filename)
        else:
            click.echo(f"Error: Reflex '{name}' not found in trashcan.")
            return

    shutil.move(src, dst)
    click.echo(f"Restored '{name}' from trashcan.")

@cli.group()
def trash():
    """Manage Trashcan"""
    pass

@trash.command(name="list")
def list_trash():
    """List trashed reflexes"""
    if not os.path.exists(TRASH_DIR):
        click.echo("Trashcan is empty.")
        return
        
    files = [f for f in os.listdir(TRASH_DIR) if f.endswith('.yaml') or f.endswith('.yml')]
    if not files:
        click.echo("Trashcan is empty.")
        return

    click.echo(f"Trashcan ({len(files)} items):")
    for f in files:
        click.echo(f"  - {f}")

@trash.command(name="empty")
def empty_trash():
    """Empty the trashcan"""
    if not os.path.exists(TRASH_DIR):
        click.echo("Trashcan is already empty.")
        return
        
    files = [f for f in os.listdir(TRASH_DIR) if f.endswith('.yaml') or f.endswith('.yml')]
    for f in files:
        os.remove(os.path.join(TRASH_DIR, f))
    
    click.echo(f"Deleted {len(files)} item(s) from trashcan.")

@cli.group()
def tool():
    """Manage Tools"""
    pass

@tool.command(name="list")
def list_tools():
    """List available tools (requires MCP Bridge)"""
    async def _list():
        tool_manager = ToolManager()
        
        registries = ConfigManager.load_tools_config()
        for reg in registries:
            if reg['type'] == 'sse':
                tool_manager.add_sse_registry(reg['name'], reg['url'])
            elif reg['type'] == 'stdio':
                tool_manager.add_stdio_registry(reg['name'], reg['command'], reg['args'], reg.get('env'))
                
        if await tool_manager.connect():
            tool_manager.list_all_tools()
            await tool_manager.disconnect()
        else:
            click.echo("Could not connect to MCP Bridge.")

    asyncio.run(_list())

if __name__ == "__main__":
    cli()
