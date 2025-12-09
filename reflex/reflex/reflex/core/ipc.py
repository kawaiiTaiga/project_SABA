
import asyncio
import json
import logging
from typing import Callable, Awaitable, Dict, Any, Optional

logger = logging.getLogger("IPC")

class IPCServer:
    def __init__(self, host='127.0.0.1', port=8090):
        self.host = host
        self.port = port
        self.server = None
        self.clients = set()
        
        # Queues
        self.trigger_queue = asyncio.Queue()
        self.chat_queue = asyncio.Queue()
        
        self.running = False

    async def start(self):
        self.server = await asyncio.start_server(
            self.handle_client, self.host, self.port
        )
        self.running = True
        logger.info(f"IPC Server running on {self.host}:{self.port}")
        # asyncio.create_task(self.server.serve_forever())

    async def stop(self):
        self.running = False
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        
        # Disconnect all clients
        for writer in list(self.clients):
            try:
                writer.close()
                await writer.wait_closed()
            except:
                pass
        self.clients.clear()

    async def handle_client(self, reader, writer):
        addr = writer.get_extra_info('peername')
        logger.info(f"New connection from {addr}")
        self.clients.add(writer)

        try:
            while self.running:
                data = await reader.read(4096)
                if not data:
                    break
                
                raw_message = data.decode().strip()
                if not raw_message:
                    continue
                
                # Try to parse as JSON
                try:
                    message_json = json.loads(raw_message)
                    
                    if message_json.get('type') == 'trigger':
                        await self.trigger_queue.put(message_json)
                        logger.info(f"IPC Trigger: {message_json.get('name')}")
                    else:
                        # Assume chat input or other raw input
                        if 'content' in message_json:
                            # If it's formatted as {"type": "chat_input", "content": "..."}
                            await self.chat_queue.put(message_json['content'])
                        else:
                            # Possibly just a JSON we don't know, treat as chat input or ignore?
                            # If it has neither type=trigger nor content, what is it?
                            # Maybe we just dump it to chat queue as string if it's not a trigger
                            await self.chat_queue.put(raw_message)
                            
                except json.JSONDecodeError:
                    # Raw string (e.g. from Dashboard simple input)
                    await self.chat_queue.put(raw_message)
                    
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error handling client {addr}: {e}")
        finally:
            logger.info(f"Connection closed {addr}")
            self.clients.discard(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except:
                pass

    async def broadcast(self, data: Dict[str, Any]):
        if not self.clients:
            return
            
        message = json.dumps(data) + "\n"
        encoded = message.encode()
        
        for writer in list(self.clients):
            try:
                writer.write(encoded)
                await writer.drain()
            except Exception as e:
                logger.error(f"Broadcast error: {e}")
                self.clients.discard(writer)

    async def get_input(self) -> str:
        # ChatAction uses this. Now it pulls from chat_queue
        return await self.chat_queue.get()
        
    async def get_trigger(self):
        # Engine uses this to get triggers (non-blocking preferred?)
        # For now, expose blocking, Engine will use nowait or task
        return await self.trigger_queue.get()


class IPCClient:
    def __init__(self, host='127.0.0.1', port=8090):
        self.host = host
        self.port = port
        self.reader = None
        self.writer = None
        self.connected = False

    async def connect(self):
        try:
            self.reader, self.writer = await asyncio.open_connection(
                self.host, self.port
            )
            self.connected = True
            return True
        except Exception as e:
            print(f"Connection failed: {e}")
            return False

    async def send(self, message: str):
        if not self.connected:
            return
        try:
            self.writer.write(message.encode())
            await self.writer.drain()
        except Exception as e:
            print(f"Send failed: {e}")
            self.connected = False

    async def send_json(self, data: Dict[str, Any]):
        if not self.connected:
            return
        try:
            msg = json.dumps(data)
            self.writer.write(msg.encode())
            await self.writer.drain()
        except Exception as e:
            print(f"Send failed: {e}")
            self.connected = False

    async def receive(self) -> Optional[Dict[str, Any]]:
        if not self.connected:
            return None
        try:
            data = await self.reader.read(4096)
            if not data:
                self.connected = False
                return None
            
            decoded = data.decode().strip()
            
            try:
                return json.loads(decoded)
            except:
                lines = decoded.split('\n')
                for line in reversed(lines):
                    if line.strip():
                        try:
                            return json.loads(line)
                        except:
                            continue
                return None
                
        except Exception as e:
            print(f"Receive failed: {e}")
            self.connected = False
            return None

    async def disconnect(self):
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
        self.connected = False
