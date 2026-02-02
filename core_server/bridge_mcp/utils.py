import time
import json
import base64
import requests
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List, Union
from mcp.types import ImageContent, TextContent
from pydantic import create_model

# ---- STDERR-only logging (STDIO-safe)
# ---- STDERR-only logging (STDIO-safe)
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
# Suppress noisy library logs
logging.getLogger("mcp.server.fastmcp.tools.tool_manager").setLevel(logging.ERROR)
logging.getLogger("mcp.server.fastmcp").setLevel(logging.ERROR)

def log(*a, **k): print(*a, file=sys.stderr, flush=True, **k)

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def fetch_and_convert_to_base64(url: str, timeout: int = 10) -> Optional[str]:
    try:
        cache_bust_url = f"{url}{'&' if '?' in url else '?'}t={int(time.time() * 1000)}"
        response = requests.get(cache_bust_url, timeout=timeout)
        response.raise_for_status()
        b64_data = base64.b64encode(response.content).decode('utf-8')
        log(f"[BASE64] Converted image to base64 ({len(b64_data)} chars)")
        return b64_data
    except Exception as e:
        log(f"[BASE64] Failed to fetch/convert {url}: {e}")
        return None

def convert_response_to_content_list(resp: Dict[str, Any]) -> List[Union[ImageContent, TextContent]]:
    result = resp.get("result", {})
    text = result.get("text", "")
    assets = result.get("assets", [])
    
    content = []
    
    for asset in assets:
        kind = str(asset.get("kind", ""))
        mime = str(asset.get("mime", "application/octet-stream")).lower()
        url = asset.get("url")
        
        if kind == "image" and mime.startswith("image/") and url:
            b64_data = fetch_and_convert_to_base64(url)
            if b64_data:
                content.append(ImageContent(
                    type="image",
                    mimeType=mime,
                    data=b64_data
                ))
    
    if text:
        content.append(TextContent(type="text", text=text))
    
    return content

def json_schema_to_pydantic_model(name: str, schema: dict):
    from pydantic import Field
    
    fields = {}
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    
    for prop_name, prop_schema in properties.items():
        field_type = str
        
        if prop_schema.get("type") == "integer":
            field_type = int
        elif prop_schema.get("type") == "number":
            field_type = float
        elif prop_schema.get("type") == "boolean":
            field_type = bool
        elif prop_schema.get("type") == "object":
            field_type = dict
        elif prop_schema.get("type") == "array":
            field_type = list
        elif prop_schema.get("type") == "string":
            field_type = str
        
        # Extract description for LLM visibility
        description = prop_schema.get("description", "")
        
        # Build Field with description
        if prop_name in required:
            # Required field
            fields[prop_name] = (field_type, Field(..., description=description))
        else:
            # Optional field with default
            if "enum" in prop_schema and prop_schema["enum"]:
                default_value = prop_schema["enum"][0]
            else:
                default_value = None
            fields[prop_name] = (field_type, Field(default_value, description=description))
    
    return create_model(name, **fields)
