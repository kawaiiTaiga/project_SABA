import docker
from typing import Dict, Any
from .config import log

class DockerManager:
    def __init__(self):
        self.client = None
        try:
            self.client = docker.from_env()
            log("[DOCKER] Connected to Docker daemon")
        except Exception as e:
            log(f"[DOCKER] Failed to connect to Docker: {e}")
    
    def restart_bridge_container(self) -> bool:
        if not self.client:
            return False
        try:
            container = self.client.containers.get("mcp-bridge")
            container.restart()
            log("[DOCKER] Bridge container restarted successfully")
            return True
        except Exception as e:
            log(f"[DOCKER] Failed to restart bridge container: {e}")
            return False
    
    def get_bridge_status(self) -> Dict[str, Any]:
        if not self.client:
            return {"status": "docker_unavailable", "error": "Docker client not available"}
        try:
            container = self.client.containers.get("mcp-bridge")
            return {
                "status": container.status,
                "running": container.status == "running",
                "id": container.id[:12],
                "name": container.name,
                "image": container.attrs.get('Config', {}).get('Image', 'unknown')
            }
        except docker.errors.NotFound:
            return {"status": "container_not_found", "error": "Container 'mcp-bridge' not found"}
        except Exception as e:
            return {"status": "error", "error": str(e)}
