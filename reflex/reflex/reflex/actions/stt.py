# reflex/actions/stt.py
from typing import Dict, Any, Callable, List
import os
import asyncio
from anthropic import AsyncAnthropic
from .base import ActionBase
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

@ActionBase.register('stt')
class STTAction(ActionBase):
    """
    Interactive Chat Action that controls an external STT client.
    """
    
    description = "Chat with STT Control"
    schema = {
        "system_prompt": {
            "type": "text",
            "description": "System prompt for the LLM",
            "default": "You are a helpful assistant."
        },
        "exit_keyword": {
            "type": "text",
            "description": "Keyword to exit the chat loop",
            "default": "exit"
        },
        "model": {
            "type": "text",
            "description": "LLM model to use",
            "default": "claude-3-5-sonnet-20241022"
        }
    }
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        
        self.api = config.get('api', 'claude')
        self.model = config.get('model', 'claude-3-5-sonnet-20241022')
        self.system_prompt = config.get('system_prompt', "You are a helpful assistant.")
        self.exit_keyword = config.get('exit_keyword', 'exit')
        self.temperature = config.get('temperature', 0.7)
        self.initial_messages = config.get('messages', [])
        
        # API Client Init
        if self.api == 'claude':
            api_key = os.environ.get('ANTHROPIC_API_KEY')
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY environment variable not set")
            self.client = AsyncAnthropic(api_key=api_key)
        else:
            raise ValueError(f"Unsupported API: {self.api}")
            
        self._tool_name_mapping = {}
        self.console = Console()

    def _prepare_tool_specs(self, tools: Dict[str, Callable]) -> list:
        """
        Reuse logic from LLMAction to prepare tool specs.
        TODO: Consider moving this to a shared utility if code duplication becomes too much.
        """
        specs = []
        self._tool_name_mapping.clear()
        
        for full_tool_name, tool_func in tools.items():
            # pure name extraction
            pure_tool_name = full_tool_name.split('.')[-1] if '.' in full_tool_name else full_tool_name
            
            self._tool_name_mapping[pure_tool_name] = full_tool_name
            
            mcp_schema = getattr(tool_func, '_mcp_schema', None)
            
            if mcp_schema:
                description = mcp_schema.get('description', f"Execute {pure_tool_name}")
                parameters = mcp_schema.get('parameters', {})
                
                spec = {
                    "name": pure_tool_name,
                    "description": description,
                    "input_schema": parameters
                }
            else:
                doc = getattr(tool_func, '__doc__', f"Execute {pure_tool_name}")
                spec = {
                    "name": pure_tool_name,
                    "description": doc.strip() if doc else f"Execute {pure_tool_name}",
                    "input_schema": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            specs.append(spec)
        
        return specs

    async def execute(
        self, 
        event: Dict[str, Any], 
        state: Dict[str, Any],
        tools: Dict[str, Callable],
        trigger: Dict[str, Any]
    ) -> Dict[str, Any]:
        
        ipc = trigger.get('ipc')
        
        async def _print(text: str, style: str = ""):
            # Local Console
            if style:
                self.console.print(f"[{style}]{text}[/{style}]")
            else:
                self.console.print(text)
            
            # IPC Broadcast
            if ipc:
                await ipc.broadcast({
                    "type": "chat_output",
                    "content": text,
                    "style": style
                })

        async def _input(prompt: str) -> str:
            # IPC Input (Preferred if available)
            if ipc and ipc.clients:
                # 1. Send signal to start STT
                await ipc.broadcast({
                    "type": "stt_command",
                    "command": "start_listening",
                })
                
                await _print(prompt, "bold yellow")
                
                # 2. Wait for input from IPC (STT Client or Dashboard)
                return await ipc.get_input()
            else:
                # Local Fallback
                return await asyncio.to_thread(input, prompt)

        await _print(f"\nStarting Voice Chat Session...", "bold green")
        
        # 1. Prepare Tools
        tool_specs = self._prepare_tool_specs(tools)
        
        # 2. Initialize History
        resolved_initial_messages = []
        for msg in self.initial_messages:
             resolved_initial_messages.append({
                 'role': msg.get('role', 'user'),
                 'content': self._resolve_template(msg.get('content', ''), event, state, trigger)
             })
             
        history = []
        if resolved_initial_messages:
            history.extend(resolved_initial_messages)
            
        system_content = self._resolve_template(self.system_prompt, event, state, trigger)
        system_param = [{"type": "text", "text": system_content}] if system_content else []
        
        while True:
            # 3. User Input
            try:
                user_input = await _input("\nUser: ")
            except EOFError:
                break
                
            if user_input.strip() == self.exit_keyword:
                await _print("Exiting chat...", "yellow")
                break
            
            # Add user message to history
            history.append({"role": "user", "content": user_input})
            
            # 4. LLM Turn (Loop for tools)
            while True:
                # Prepare call params
                call_params = {
                    "model": self.model,
                    "max_tokens": 4096,
                    "temperature": self.temperature,
                    "messages": history,
                }
                if system_param:
                    call_params["system"] = system_param
                if tool_specs:
                    call_params["tools"] = tool_specs
                
                try:
                    response = await self.client.messages.create(**call_params)
                except Exception as e:
                    await _print(f"Error calling LLM: {e}", "bold red")
                    import traceback
                    traceback.print_exc()
                    break # Break inner loop
                
                # Process response
                has_tool_use = False
                assistant_content_blocks = []
                
                # We need to construct the assistant message content exactly as Anthropic expects for history
                # It can be a list of blocks.
                
                for block in response.content:
                    if block.type == 'text':
                        # Markdown render for assistant output
                        await _print(block.text, "blue") 
                        assistant_content_blocks.append(block.model_dump())
                        
                    elif block.type == 'tool_use':
                        has_tool_use = True
                        await _print(f"Tool Call: {block.name}({block.input})", "magenta")
                        assistant_content_blocks.append(block.model_dump())
                
                # Append assistant response to history
                history.append({
                    "role": "assistant", 
                    "content": assistant_content_blocks
                })
                
                if has_tool_use:
                    # Execute tools and append results
                    for block in response.content:
                        if block.type == 'tool_use':
                            pure_name = block.name
                            tool_id = block.id
                            tool_args = block.input
                            
                            full_name = self._tool_name_mapping.get(pure_name, pure_name)
                            tool_result_content = ""
                            is_error = False
                            
                            if full_name in tools:
                                try:
                                    # Execute tool
                                    result = await tools[full_name](**tool_args)
                                    tool_result_content = str(result)
                                    display_result = tool_result_content[:200] + "..." if len(tool_result_content) > 200 else tool_result_content
                                    await _print(f"   Result: {display_result}", "green")
                                except Exception as e:
                                    tool_result_content = f"Error executing tool: {e}"
                                    is_error = True
                                    await _print(f"   Error: {e}", "red")
                            else:
                                tool_result_content = f"Tool {full_name} not found."
                                is_error = True
                                await _print(f"   Tool not found: {full_name}", "red")
                            
                            # Append tool result to history
                            history.append({
                                "role": "user",
                                "content": [
                                    {
                                        "type": "tool_result",
                                        "tool_use_id": tool_id,
                                        "content": tool_result_content,
                                        "is_error": is_error
                                    }
                                ]
                            })
                    # Continue inner loop to get LLM's interpretation of tool results
                    continue 
                else:
                    # No tool use, break inner loop to wait for next user input
                    break

        # Format transcript for logging
        transcript_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in history])
        
        return {
            "success": True,
            "transcript": history,
            "last_message": history[-1] if history else None,
            "text": transcript_text
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            'type': 'stt',
            'api': self.api,
            'model': self.model,
            'system_prompt': self.system_prompt,
            'exit_keyword': self.exit_keyword
        }
