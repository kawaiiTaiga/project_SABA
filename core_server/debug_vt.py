#!/usr/bin/env python3
"""Debug script to trace virtual tool registration"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from bridge_mcp.config import VIRTUAL_TOOLS_CONFIG_PATH
from bridge_mcp.virtual_tool import VirtualToolStore

print(f"[DEBUG] VIRTUAL_TOOLS_CONFIG_PATH = {VIRTUAL_TOOLS_CONFIG_PATH}")
print(f"[DEBUG] Absolute path = {os.path.abspath(VIRTUAL_TOOLS_CONFIG_PATH)}")
print(f"[DEBUG] File exists = {os.path.exists(VIRTUAL_TOOLS_CONFIG_PATH)}")

# Load virtual tool store
store = VirtualToolStore(VIRTUAL_TOOLS_CONFIG_PATH)
print(f"\n[DEBUG] Loaded config: {store.config}")

# List virtual tools
virtual_tools = store.get_all_virtual_tools()
print(f"\n[DEBUG] Virtual tools found: {len(virtual_tools)}")

for name, vt_def in virtual_tools.items():
    print(f"\n  - {name}:")
    print(f"    description: {vt_def.get('description')}")
    print(f"    bindings: {vt_def.get('bindings')}")

# Test schema building (mock device store)
class MockDeviceStore:
    def get(self, device_id):
        print(f"    [MockDeviceStore] get({device_id}) called")
        return None

print("\n[DEBUG] Testing schema building...")
for name in virtual_tools:
    schema = store.build_virtual_tool_schema(name, MockDeviceStore())
    print(f"  Schema for {name}: {schema}")
