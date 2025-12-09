# reflex/dashboard.py
"""
SABA Reflex Dashboard - Rich + Questionary
Menu-based TUI that works well on Windows
"""
import asyncio
import os
import shutil
import yaml
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

import questionary
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text
from rich import box

from reflex.core.engine import ReflexEngine
from reflex.core.state import WorldState
from reflex.tools.registry import ToolManager
from reflex.core.config import ConfigManager
from reflex.triggers.base import TriggerBase
from reflex.actions.base import ActionBase

# Ensure subclasses are loaded
import reflex.triggers
import reflex.actions

REFLEX_DIR = "reflexes"
TRASH_DIR = "trashcan"

console = Console()


def clear_screen():
    """Clear terminal"""
    os.system('cls' if os.name == 'nt' else 'clear')


def print_header():
    """Print dashboard header"""
    header = """
[bold green]
┏━┓┏━┓┏┓ ┏━┓   ┏━┓┏━╸┏━╸╻  ┏━╸╻ ╻
┗━┓┣━┫┣┻┓┣━┫   ┣┳┛┣╸ ┣╸ ┃  ┣╸ ┏╋┛
┗━┛╹ ╹┗━┛╹ ╹   ╹┗╸┗━╸╹  ┗━╸┗━╸╹ ╹
[/bold green]
    """
    console.print(header)


def show_reflex_table(engine: ReflexEngine):
    """Display reflexes in a table"""
    table = Table(
        title="[bold green]REFLEXES[/bold green]",
        box=box.ROUNDED,
        border_style="green"
    )
    
    table.add_column("ID", style="green")
    table.add_column("Trigger", style="cyan")
    table.add_column("Action", style="cyan")
    table.add_column("Runs", justify="right", style="yellow")
    table.add_column("Status", style="bold")
    
    for reflex in engine.reflexes.values():
        status = "[green]ON[/green]" if reflex.enabled else "[red]OFF[/red]"
        runs = reflex.metadata.get("runs", 0)
        table.add_row(
            reflex.id,
            reflex.trigger.type,
            reflex.action.type,
            str(runs),
            status
        )
    
    if not engine.reflexes:
        table.add_row("[dim]No reflexes[/dim]", "", "", "", "")
    
    console.print(table)


def show_tool_servers():
    """Display tool servers"""
    servers = ConfigManager.load_tools_config()
    
    table = Table(
        title="[bold green]TOOL SERVERS[/bold green]",
        box=box.ROUNDED,
        border_style="green"
    )
    
    table.add_column("Name", style="green")
    table.add_column("Type", style="cyan")
    table.add_column("Config", style="white")
    
    for server in servers:
        stype = server['type'].upper()
        if server['type'] == 'sse':
            config = server.get('url', '')
        else:
            config = f"{server.get('command', '')} {' '.join(server.get('args', []))}"
        
        table.add_row(server['name'], stype, config)
    
    if not servers:
        table.add_row("[dim]No servers configured[/dim]", "", "")
    
    console.print(table)


def show_trash():
    """Display trashed reflexes"""
    os.makedirs(TRASH_DIR, exist_ok=True)
    
    table = Table(
        title="[bold yellow]TRASH[/bold yellow]",
        box=box.ROUNDED,
        border_style="yellow"
    )
    
    table.add_column("Filename", style="yellow")
    table.add_column("Deleted At", style="dim")
    
    trashed = []
    for f in os.listdir(TRASH_DIR):
        if f.endswith('.yaml'):
            path = os.path.join(TRASH_DIR, f)
            mtime = datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y-%m-%d %H:%M')
            trashed.append((f, mtime))
            table.add_row(f, mtime)
    
    if not trashed:
        table.add_row("[dim]Empty[/dim]", "")
    
    console.print(table)
    return trashed


async def _fetch_all_tools() -> List[Dict]:
    """Connect to all servers and fetch available tools"""
    servers = ConfigManager.load_tools_config()
    all_tools = []
    tool_manager = ToolManager()
    
    for server in servers:
        name = server['name']
        try:
            if server['type'] == 'sse':
                tool_manager.add_sse_registry(name, server['url'])
            else:
                tool_manager.add_stdio_registry(
                    name,
                    server['command'],
                    server.get('args', []),
                    server.get('env')
                )
            
            registry = tool_manager.registries[name]
            if await registry.connect():
                await registry.load_tools_from_mcp()
                for tool_name in registry.list_tools():
                    desc = registry.tool_schemas.get(tool_name, {}).get('description', '')
                    all_tools.append({"name": tool_name, "desc": desc, "server": name})
                await registry.disconnect()
        except Exception as e:
            console.print(f"[dim red]Could not connect to {name}: {e}[/dim red]")
    
    return all_tools


# =============================================================================
# REFLEX MANAGEMENT
# =============================================================================

def create_reflex():
    """Interactive reflex creation"""
    console.print("\n[bold green]== CREATE NEW REFLEX ==[/bold green]\n")
    
    name = questionary.text("Reflex Name (Enter to cancel):").ask()
    if not name:
        return
    
    # ==========================================
    # Step 1: Tool Selection (FIRST!)
    # ==========================================
    console.print("\n[bold cyan]== STEP 1: SELECT TOOL ==[/bold cyan]")
    tools = []
    servers = ConfigManager.load_tools_config()
    available_tools = []
    
    if servers:
        console.print("[cyan]Fetching available tools from servers...[/cyan]")
        available_tools = asyncio.run(_fetch_all_tools())
    
    if available_tools:
        tool_choices = [
            questionary.Choice(f"{t['server']}.{t['name']} - {t['desc'][:40]}", f"{t['server']}.{t['name']}") 
            for t in available_tools
        ]
        selected_tools = questionary.checkbox(
            "Select tools (Space to select, Enter to confirm):",
            choices=tool_choices
        ).ask()
        if selected_tools:
            tools = selected_tools
    else:
        console.print("[yellow]No tools available from servers. Enter manually (comma separated):[/yellow]")
        tool_str = questionary.text("Tool names (server.tool_name):").ask()
        if tool_str and tool_str.strip():
            tools = [t.strip() for t in tool_str.split(',') if t.strip()]
    
    # 0개 선택 허용 (LLMAction 등을 위해)
    if not tools:
        console.print("[dim]No tools selected. Proceeding without tools.[/dim]\n")
    else:
        console.print(f"[green]Selected tools: {', '.join(tools)}[/green]\n")
    
    # ==========================================
    # Step 2: Trigger
    # ==========================================
    console.print("[bold cyan]== STEP 2: SELECT TRIGGER ==[/bold cyan]")
    trigger_choices = [
        questionary.Choice(f"{t} - {getattr(c, 'description', '')}", t) 
        for t, c in TriggerBase._registry.items()
    ]
    trigger_type = questionary.select("Trigger Type:", choices=trigger_choices).ask()
    
    trigger_config = {"type": trigger_type}
    trigger_cls = TriggerBase._registry[trigger_type]
    for param, cfg in getattr(trigger_cls, 'schema', {}).items():
        val = questionary.text(f"{cfg.get('description', param)}:", default=str(cfg.get('default', ''))).ask()
        trigger_config[param] = val
        
    # Cooldown (Trigger 속성으로 이동)
    cooldown_str = questionary.text("Cooldown (seconds, 0 = none):", default="0").ask()
    cooldown = int(cooldown_str) if cooldown_str else 0
    if cooldown > 0:
        trigger_config["cooldown_sec"] = cooldown
    
    # ==========================================
    # Step 3: Action
    # ==========================================
    console.print("\n[bold cyan]== STEP 3: SELECT ACTION ==[/bold cyan]")
    action_choices = [
        questionary.Choice(f"{a} - {getattr(c, 'description', '')}", a) 
        for a, c in ActionBase._registry.items()
    ]
    action_type = questionary.select("Action Type:", choices=action_choices).ask()
    
    action_config = {"type": action_type}
    action_cls = ActionBase._registry[action_type]
    
    # ToolAction은 별도 인자가 필요 없음 (tool은 이미 선택됨)
    # ToolAction은 별도 인자가 필요 없음 (tool은 이미 선택됨)
    if action_type == 'tool':
        if not tools:
             console.print("[yellow]WARNING: 'tool' action selected but no tools are configured! This reflex will fail to run.[/yellow]")
        else:
             console.print(f"[dim]ToolAction will use the selected tools: {tools}[/dim]")
        
        # arguments만 입력받기
        args_str = questionary.text(
            "Tool arguments (JSON format, e.g. {\"key\": \"value\"}):",
            default="{}"
        ).ask()
        if args_str and args_str.strip():
            action_config["arguments"] = args_str.strip()
    elif action_type == 'llm':
        flat_params = {}
        for param, cfg in getattr(action_cls, 'schema', {}).items():
            val = questionary.text(f"{cfg.get('description', param)}:", default=str(cfg.get('default', ''))).ask()
            flat_params[param] = val
        action_config["messages"] = [
            {"role": "system", "content": flat_params.get('system_prompt', '')},
            {"role": "user", "content": flat_params.get('user_prompt', '')}
        ]
    else:
        # 다른 Action들은 schema에 따라 입력
        for param, cfg in getattr(action_cls, 'schema', {}).items():
            val = questionary.text(f"{cfg.get('description', param)}:", default=str(cfg.get('default', ''))).ask()
            action_config[param] = val
    
    # Lifecycle
    console.print("\n[bold green]== LIFECYCLE SETTINGS ==[/bold green]")
    lifecycle_choice = questionary.select(
        "Lifecycle Policy:",
        choices=[
            questionary.Choice("Persistent (Run forever)", "persistent"),
            questionary.Choice("Temporary (Expire after time)", "temporary"),
            questionary.Choice("Max Runs (Expire after count)", "max_runs"),
        ]
    ).ask()
    
    lifecycle_config = {"type": lifecycle_choice}
    
    if lifecycle_choice == "temporary":
        ttl = questionary.text("TTL (seconds):", default="3600").ask()
        lifecycle_config["ttl_sec"] = int(ttl)
    elif lifecycle_choice == "max_runs":
        runs = questionary.text("Max runs:", default="1").ask()
        lifecycle_config["max_runs"] = int(runs)
    
    # Enabled by default
    enabled = questionary.confirm("Enable immediately?", default=True).ask()
    
    # Save
    os.makedirs(REFLEX_DIR, exist_ok=True)
    config = {
        "id": name,
        "name": name.replace("_", " ").title(),
        "trigger": trigger_config,
        "action": action_config,
        "tools": tools,
        "lifecycle": lifecycle_config,
        "enabled": enabled
    }
    
    path = os.path.join(REFLEX_DIR, f"{name}.yaml")
    with open(path, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, sort_keys=False, allow_unicode=True)
    
    console.print(f"\n[green]Created: {path}[/green]")


def edit_reflex(engine: ReflexEngine):
    """Edit existing reflex"""
    if not engine.reflexes:
        console.print("[yellow]No reflexes to edit[/yellow]")
        return
    
    choices = ["Back"] + list(engine.reflexes.keys())
    reflex_id = questionary.select("Select reflex to edit:", choices=choices).ask()
    if not reflex_id or reflex_id == "Back":
        return
    
    path = os.path.join(REFLEX_DIR, f"{reflex_id}.yaml")
    if not os.path.exists(path):
        console.print(f"[red]File not found: {path}[/red]")
        return
    
    # Open in editor or show current config
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    
    # logs와 metadata 제외한 config만 표시
    display_data = {k: v for k, v in data.items() if k not in ('logs', 'metadata')}
    content = yaml.dump(display_data, sort_keys=False, allow_unicode=True)
    
    console.print(f"\n[bold]Current config for {reflex_id}:[/bold]")
    console.print(Panel(content, border_style="green"))
    
    if questionary.confirm("Edit this reflex?").ask():
        # Simple field editing
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        # Edit trigger params
        if questionary.confirm("Edit trigger?").ask():
            for key in list(data.get('trigger', {}).keys()):
                if key == 'type':
                    continue
                new_val = questionary.text(f"{key}:", default=str(data['trigger'].get(key, ''))).ask()
                data['trigger'][key] = new_val
        
        # Edit action params
        if questionary.confirm("Edit action?").ask():
            action_data = data.get('action', {})
            action_type = action_data.get('type', '')
            
            if action_type == 'llm':
                # LLM action - messages 수정
                messages = action_data.get('messages', [])
                new_messages = []
                for i, msg in enumerate(messages):
                    role = msg.get('role', 'user')
                    content = msg.get('content', '')
                    console.print(f"\n[cyan]Message {i+1} ({role}):[/cyan]")
                    new_content = questionary.text(
                        f"Content ({role}):", 
                        default=content,
                        multiline=True
                    ).ask()
                    new_messages.append({'role': role, 'content': new_content})
                action_data['messages'] = new_messages
            
            elif action_type == 'tool':
                # Tool action - arguments 수정
                args = action_data.get('arguments', '{}')
                if isinstance(args, dict):
                    import json
                    args = json.dumps(args)
                new_args = questionary.text("Arguments (JSON):", default=args).ask()
                action_data['arguments'] = new_args
            
            else:
                # 기타 action - 모든 파라미터 수정
                for key in list(action_data.keys()):
                    if key == 'type':
                        continue
                    new_val = questionary.text(f"{key}:", default=str(action_data.get(key, ''))).ask()
                    action_data[key] = new_val
            
            data['action'] = action_data
        
        # Edit tools
        if questionary.confirm("Edit tools?").ask():
            tools_str = questionary.text("Tools (comma separated):", default=", ".join(data.get('tools', []))).ask()
            data['tools'] = [t.strip() for t in tools_str.split(',') if t.strip()]
        
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, sort_keys=False, allow_unicode=True)
        
        console.print(f"[green]Updated: {path}[/green]")


def delete_reflex(engine: ReflexEngine):
    """Move reflex to trash"""
    if not engine.reflexes:
        console.print("[yellow]No reflexes to delete[/yellow]")
        return
    
    choices = ["Back"] + list(engine.reflexes.keys())
    reflex_id = questionary.select("Select reflex to delete:", choices=choices).ask()
    if not reflex_id or reflex_id == "Back":
        return
    
    if questionary.confirm(f"Delete '{reflex_id}'?").ask():
        os.makedirs(TRASH_DIR, exist_ok=True)
        src = os.path.join(REFLEX_DIR, f"{reflex_id}.yaml")
        dst = os.path.join(TRASH_DIR, f"{reflex_id}.yaml")
        if os.path.exists(src):
            # Remove existing file in trash if exists
            if os.path.exists(dst):
                os.remove(dst)
            # Copy then delete (more reliable than move on Windows)
            shutil.copy2(src, dst)
            os.remove(src)
            
            # Remove from engine memory
            engine.remove_reflex(reflex_id)
            
            console.print(f"[yellow]Moved to trash: {reflex_id}[/yellow]")



LOG_DIR = "logs"


def view_reflex_logs(engine: ReflexEngine):
    """View logs for a specific reflex"""
    if not engine.reflexes:
        console.print("[yellow]No reflexes available[/yellow]")
        return
    
    choices = ["Back"] + list(engine.reflexes.keys())
    reflex_id = questionary.select("Select reflex to view logs:", choices=choices).ask()
    if not reflex_id or reflex_id == "Back":
        return
    
    # Read logs from .log file
    log_path = os.path.join(LOG_DIR, f"{reflex_id}.log")
    logs = []
    
    if os.path.exists(log_path):
        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                for line in f:
                    # Parse log line: [2024-12-09 22:30:00] [INFO] message
                    line = line.strip()
                    if not line: continue
                    
                    try:
                        # Simple parsing
                        parts = line.split('] [', 2)
                        if len(parts) >= 2:
                            time_str = parts[0].strip('[')
                            # Check if 3rd part exists (message)
                            if len(parts) > 2:
                                # status is parts[1], message is parts[2]
                                status_str = parts[1]
                                msg_str = parts[2]
                            else:
                                # Maybe format is [time] [status] message
                                # Split the rest
                                remainder = parts[1]
                                if '] ' in remainder:
                                    status_str, msg_str = remainder.split('] ', 1)
                                else:
                                    status_str = remainder.strip(']')
                                    msg_str = ""
                                    
                            logs.append({'time': time_str, 'status': status_str, 'message': msg_str})
                        else:
                            logs.append({'time': '', 'status': 'RAW', 'message': line})
                    except:
                         logs.append({'time': '', 'status': 'RAW', 'message': line})
        except Exception as e:
            console.print(f"[red]Error reading logs: {e}[/red]")

    # Load reflex YAML for metadata
    path = os.path.join(REFLEX_DIR, f"{reflex_id}.yaml")
    metadata = {}
    lifecycle = {}
    
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            metadata = data.get('metadata', {})
            lifecycle = data.get('lifecycle', {})
            
    # Fallback to engine data if file load failed or empty
    if not metadata:
        reflex = engine.reflexes.get(reflex_id)
        if reflex:
             metadata = reflex.metadata
             lifecycle = reflex.lifecycle.__dict__ if hasattr(reflex.lifecycle, '__dict__') else {}
    
    console.print(f"\n[bold green]== LOGS: {reflex_id} ==[/bold green]\n")
    
    # Show metadata
    table = Table(title="Metadata", box=box.SIMPLE)
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="white")
    table.add_row("Runs", str(metadata.get('runs', 0)))
    table.add_row("Last Run", str(metadata.get('last_run', 'Never')))
    created_at = lifecycle.get('created_at', 'Unknown')
    # Handle if created_at is not in dict but object
    table.add_row("Created", str(created_at))
    console.print(table)
    
    # Show logs
    if logs:
        console.print(f"\n[bold]Recent Logs (Last 20 of {len(logs)}):[/bold]")
        log_table = Table(box=box.SIMPLE)
        log_table.add_column("Time", style="dim")
        log_table.add_column("Status", style="cyan")
        log_table.add_column("Message", style="white")
        
        for log in logs[-20:]:  # Show last 20 logs
            log_table.add_row(
                log.get('time', ''),
                log.get('status', ''),
                log.get('message', '')[:60]
            )
        
        console.print(log_table)
    else:
        console.print("\n[dim]No logs found.[/dim]")
    
    # Option to clear logs
    if logs and questionary.confirm("Clear logs?", default=False).ask():
        try:
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write("") # Truncate
            console.print("[yellow]Logs cleared[/yellow]")
        except Exception as e:
            console.print(f"[red]Failed to clear logs: {e}[/red]")


# =============================================================================
# TRASH MANAGEMENT
# =============================================================================

def manage_trash():
    """Trash management menu"""
    while True:
        clear_screen()
        print_header()
        trashed = show_trash()
        
        choices = ["Restore", "Empty Trash", "Back"]
        action = questionary.select("Action:", choices=choices).ask()
        
        if action == "Back" or action is None:
            break
        elif action == "Restore" and trashed:
            files = [t[0] for t in trashed]
            fname = questionary.select("Select file to restore:", choices=files).ask()
            if fname:
                src = os.path.join(TRASH_DIR, fname)
                dst = os.path.join(REFLEX_DIR, fname)
                if not os.path.exists(dst):
                    os.rename(src, dst)
                    console.print(f"[green]Restored: {fname}[/green]")
                else:
                    console.print(f"[red]File already exists in reflexes[/red]")
                questionary.press_any_key_to_continue().ask()
        elif action == "Empty Trash":
            if questionary.confirm("Empty all trash?").ask():
                for f in os.listdir(TRASH_DIR):
                    if f.endswith('.yaml'):
                        os.remove(os.path.join(TRASH_DIR, f))
                console.print("[yellow]Trash emptied[/yellow]")
                questionary.press_any_key_to_continue().ask()


# =============================================================================
# TOOL SERVER MANAGEMENT
# =============================================================================

def add_tool_server():
    """Add new tool server"""
    console.print("\n[bold green]== ADD TOOL SERVER ==[/bold green]\n")
    
    name = questionary.text("Server Name:").ask()
    if not name:
        return
    
    stype = questionary.select("Type:", choices=["sse", "stdio"]).ask()
    
    config = {"name": name, "type": stype}
    
    if stype == "sse":
        url = questionary.text("URL:", default="http://localhost:8083").ask()
        config["url"] = url
    else:
        cmd = questionary.text("Command:").ask()
        args = questionary.text("Args (space separated):").ask()
        env_str = questionary.text("Env vars (KEY=VAL,KEY2=VAL2):").ask()
        
        config["command"] = cmd
        config["args"] = args.split() if args else []
        
        if env_str:
            env = {}
            for pair in env_str.split(","):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    env[k.strip()] = v.strip()
            if env:
                config["env"] = env
    
    try:
        ConfigManager.add_registry(config)
        console.print(f"[green]Added: {name}[/green]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def edit_tool_server():
    """Edit tool server"""
    servers = ConfigManager.load_tools_config()
    if not servers:
        console.print("[yellow]No servers to edit[/yellow]")
        return
    
    choices = [s['name'] for s in servers]
    name = questionary.select("Select server:", choices=choices).ask()
    if not name:
        return
    
    server = next((s for s in servers if s['name'] == name), None)
    if not server:
        return
    
    console.print(f"\n[bold]Current config:[/bold]")
    console.print(Panel(yaml.dump(server), border_style="green"))
    
    if server['type'] == 'sse':
        new_url = questionary.text("URL:", default=server.get('url', '')).ask()
        server['url'] = new_url
    else:
        new_cmd = questionary.text("Command:", default=server.get('command', '')).ask()
        new_args = questionary.text("Args:", default=' '.join(server.get('args', []))).ask()
        server['command'] = new_cmd
        server['args'] = new_args.split() if new_args else []
    
    ConfigManager.remove_registry(name)
    ConfigManager.add_registry(server)
    console.print(f"[green]Updated: {name}[/green]")


def delete_tool_server():
    """Delete tool server"""
    servers = ConfigManager.load_tools_config()
    if not servers:
        console.print("[yellow]No servers to delete[/yellow]")
        return
    
    choices = [s['name'] for s in servers]
    name = questionary.select("Select server to delete:", choices=choices).ask()
    if not name:
        return
    
    if questionary.confirm(f"Delete '{name}'?").ask():
        ConfigManager.remove_registry(name)
        console.print(f"[yellow]Deleted: {name}[/yellow]")


async def connect_and_list_tools():
    """Connect to servers and list tools"""
    servers = ConfigManager.load_tools_config()
    if not servers:
        console.print("[yellow]No servers configured[/yellow]")
        return
    
    tool_manager = ToolManager()
    
    for server in servers:
        name = server['name']
        console.print(f"\n[cyan]Connecting to {name}...[/cyan]")
        
        try:
            if server['type'] == 'sse':
                tool_manager.add_sse_registry(name, server['url'])
            else:
                tool_manager.add_stdio_registry(
                    name,
                    server['command'],
                    server.get('args', []),
                    server.get('env')
                )
            
            registry = tool_manager.registries[name]
            if await registry.connect():
                await registry.load_tools_from_mcp()
                
                table = Table(title=f"[bold]{name}[/bold] ({len(registry.tools)} tools)", box=box.SIMPLE)
                table.add_column("Tool", style="green")
                table.add_column("Description", style="dim")
                
                for tool_name in registry.list_tools():
                    desc = registry.tool_schemas.get(tool_name, {}).get('description', '')[:50]
                    table.add_row(tool_name, desc)
                
                console.print(table)
                await registry.disconnect()
            else:
                console.print(f"[red]Failed to connect to {name}[/red]")
        except Exception as e:
            console.print(f"[red]Error with {name}: {e}[/red]")


def manage_tools():
    """Tool management menu"""
    while True:
        clear_screen()
        print_header()
        show_tool_servers()
        
        choices = [
            "Add Server",
            "Edit Server", 
            "Delete Server",
            "Connect & List Tools",
            "Back"
        ]
        action = questionary.select("Action:", choices=choices).ask()
        
        if action == "Back" or action is None:
            break
        elif action == "Add Server":
            add_tool_server()
            questionary.press_any_key_to_continue().ask()
        elif action == "Edit Server":
            edit_tool_server()
            questionary.press_any_key_to_continue().ask()
        elif action == "Delete Server":
            delete_tool_server()
            questionary.press_any_key_to_continue().ask()
        elif action == "Connect & List Tools":
            asyncio.run(connect_and_list_tools())
            questionary.press_any_key_to_continue().ask()


# =============================================================================
# VIRTUAL TOOL MANAGEMENT (Combine Tools)
# =============================================================================

def create_virtual_tool_ui():
    """Create a new virtual tool (Combine Tools)"""
    console.print("\n[bold green]== COMBINE TOOLS (Virtual Tool) ==[/bold green]\n")
    
    name = questionary.text("Virtual Tool Name:").ask()
    if not name:
        return

    description = questionary.text("Description:").ask()
    
    mode = questionary.select(
        "Execution Mode:",
        choices=[
            questionary.Choice("Sequential (One by one)", "sequential"),
            questionary.Choice("Parallel (At the same time)", "parallel")
        ]
    ).ask()
    
    # Select tools to combine
    console.print("\n[cyan]Fetching available tools...[/cyan]")
    available_tools = asyncio.run(_fetch_all_tools())
    
    if not available_tools:
        console.print("[yellow]No tools available to combine. Add tool servers first.[/yellow]")
        return

    tool_choices = [
        questionary.Choice(f"{t['server']}.{t['name']} - {t['desc'][:40]}", f"{t['server']}.{t['name']}") 
        for t in available_tools
    ]
    
    selected_tools = questionary.checkbox(
        "Select tools to combine (Space to select, Enter to confirm):",
        choices=tool_choices
    ).ask()
    
    if not selected_tools:
        console.print("[dim]No tools selected. Cancelled.[/dim]")
        return
    
    # Save to config
    new_virtual_tool = {
        "name": name,
        "description": description,
        "mode": mode,
        "tools": selected_tools
    }
    
    registries = ConfigManager.load_tools_config()
    virtual_tools = ConfigManager.load_virtual_tools_config()
    
    # Check for duplicates
    if any(vt['name'] == name for vt in virtual_tools):
        console.print(f"[red]Virtual tool '{name}' already exists![/red]")
        return
        
    virtual_tools.append(new_virtual_tool)
    ConfigManager.save_tools_config(registries, virtual_tools)
    
    console.print(f"\n[green]Created Virtual Tool: {name}[/green]")
    console.print(f"   Mode: {mode}")
    console.print(f"   Tools: {len(selected_tools)}")


def delete_virtual_tool_ui():
    """Delete a virtual tool"""
    virtual_tools = ConfigManager.load_virtual_tools_config()
    if not virtual_tools:
        console.print("[yellow]No virtual tools to delete[/yellow]")
        return
    
    choices = [vt['name'] for vt in virtual_tools] + ["Back"]
    name = questionary.select("Select virtual tool to delete:", choices=choices).ask()
    
    if not name or name == "Back":
        return
    
    if questionary.confirm(f"Delete '{name}'?").ask():
        new_virtual_tools = [vt for vt in virtual_tools if vt['name'] != name]
        registries = ConfigManager.load_tools_config()
        ConfigManager.save_tools_config(registries, new_virtual_tools)
        console.print(f"[yellow]Deleted: {name}[/yellow]")


def list_virtual_tools_ui():
    """List virtual tools"""
    virtual_tools = ConfigManager.load_virtual_tools_config()
    if not virtual_tools:
        console.print("[dim]No virtual tools configured[/dim]")
        return

    table = Table(title="[bold cyan]Virtual Tools[/bold cyan]", box=box.SIMPLE)
    table.add_column("Name", style="green")
    table.add_column("Mode", style="yellow")
    table.add_column("Tools", style="white")
    table.add_column("Description", style="dim")
    
    for vt in virtual_tools:
        tools_str = ", ".join(vt.get('tools', []))
        if len(tools_str) > 50:
            tools_str = tools_str[:47] + "..."
            
        table.add_row(
            vt.get('name', 'Unknown'),
            vt.get('mode', 'sequential'),
            tools_str,
            vt.get('description', '')
        )
    
    console.print(table)


def manage_virtual_tools():
    """Virtual Tool Management Menu"""
    while True:
        clear_screen()
        print_header()
        list_virtual_tools_ui()
        console.print()
        
        choices = [
            "Create Combined Tool",
            "Delete Combined Tool",
            "Back"
        ]
        
        action = questionary.select("Action:", choices=choices).ask()
        
        if action == "Back" or action is None:
            break
        elif action == "Create Combined Tool":
            create_virtual_tool_ui()
            questionary.press_any_key_to_continue().ask()
        elif action == "Delete Combined Tool":
            delete_virtual_tool_ui()
            questionary.press_any_key_to_continue().ask()


# =============================================================================
# MAIN DASHBOARD
# =============================================================================

# =============================================================================
# MAIN DASHBOARD
# =============================================================================

async def live_monitor():
    """Connect to Engine IPC and stream logs/interaction"""
    from reflex.core.ipc import IPCClient
    
    client = IPCClient()
    console.print(f"\n[cyan]Connecting to Engine at {client.host}:{client.port}...[/cyan]")
    
    if not await client.connect():
        console.print("[red]Could not connect to Engine. Is it running?[/red]")
        return

    console.print("[green]Connected! Streaming logs... (Press Ctrl+C to exit)[/green]\n")
    
    import asyncio
    
    async def receive_loop():
        try:
            while client.connected:
                data = await client.receive()
                if not data:
                    break
                
                dtype = data.get('type')
                
                if dtype == 'log':
                    # Format log
                    time = data.get('time', '')
                    level = data.get('level', 'INFO')
                    msg = data.get('message', '')
                    rid = data.get('reflex_id', '')
                    
                    style = "white"
                    if level == "ERROR": style = "red"
                    elif level == "WARNING": style = "yellow"
                    elif level == "RESULT": style = "green"
                    
                    console.print(f"[{time}] [{rid}] [{style}]{msg}[/{style}]")
                    
                elif dtype == 'chat_output':
                    # Chat output
                    content = data.get('content', '')
                    style = data.get('style', '')
                    if style:
                        console.print(f"[{style}]{content}[/{style}]")
                    else:
                        console.print(content)
                        
        except asyncio.CancelledError:
            pass
        except Exception as e:
            console.print(f"[red]Connection lost: {e}[/red]")

    async def input_loop():
        # Handle user input for chat
        # This blocks, so we run it in a thread executor if possible, 
        # but here we are in async.
        # Simple blocking input is easiest for CLI, but blocks output.
        # For a true TUI, we need key listeners. 
        # For this MVP, we just accept that input prompt might interleave.
        try:
            while client.connected:
                # We only want to ask for input if we know a chat is active?
                # Or just provide a ">" prompt always?
                # Let's try a non-blocking approach or just wait for user to type
                
                # Using questionary actually handles some async? No.
                # Let's just use a simple input inside a thread
                msg = await asyncio.to_thread(input) # No prompt to avoid text messing up logs
                if msg:
                     await client.send(msg)
        except:
             pass

    # Run loops
    # Note: input_loop will fight with receive_loop for console cursor.
    # ideally we use textual or similar, but for now simple streaming.
    try:
        await asyncio.gather(receive_loop(), input_loop())
    except KeyboardInterrupt:
        pass
    finally:
        await client.disconnect()
        console.print("\n[yellow]Disconnected[/yellow]")


def run_dashboard():
    """Main dashboard loop"""
    tool_manager = ToolManager()
    state = WorldState()
    engine = ReflexEngine(tool_manager, state)
    
    while True:
        clear_screen()
        print_header()
        
        # Load and display reflexes
        engine.load_reflexes()
        show_reflex_table(engine)
        
        console.print()
        
        choices = [
            "Live Monitor (Real-time)",
            "New Reflex",
            "Edit Reflex",
            "Delete Reflex",
            "View Logs",
            "Combine Tools",
            "Trash",
            "Tool Servers",
            "Quit"
        ]
        
        action = questionary.select(
            "Select action:",
            choices=choices,
            instruction="(Use arrow keys)"
        ).ask()
        
        if action == "Quit" or action is None:
            console.print("[green]Goodbye![/green]")
            break
        elif action == "Live Monitor (Real-time)":
             try:
                 asyncio.run(live_monitor())
             except KeyboardInterrupt:
                 pass
             questionary.press_any_key_to_continue().ask()
        elif action == "New Reflex":
            create_reflex()
            questionary.press_any_key_to_continue().ask()
        elif action == "Edit Reflex":
            edit_reflex(engine)
            questionary.press_any_key_to_continue().ask()
        elif action == "Delete Reflex":
            delete_reflex(engine)
        elif action == "View Logs":
            view_reflex_logs(engine)
            questionary.press_any_key_to_continue().ask()
        elif action == "Combine Tools":
            manage_virtual_tools()
        elif action == "Trash":
            manage_trash()
        elif action == "Tool Servers":
            manage_tools()


if __name__ == "__main__":
    run_dashboard()
