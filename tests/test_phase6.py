import pytest
import json
import time
from fastapi.testclient import TestClient
from app.main import app
from app.services.mcp import mcp_service

client = TestClient(app)

def test_mcp_websocket_registration():
    """Verify that an MCP client can connect and register tools via WebSocket."""
    client_id = "test_agent"
    
    with client.websocket_connect(f"/mcp/ws/{client_id}") as websocket:
        # Simulate MCP tool registration
        registration_msg = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "params": {
                "tools": [
                    {
                        "name": "read_file",
                        "description": "Read a file from disk",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}}
                        }
                    }
                ]
            }
        }
        websocket.send_text(json.dumps(registration_msg))
        
        # Give it a tiny bit of time to process
        import time
        time.sleep(0.1)
        
        # Verify tool is in registry
        assert "read_file" in mcp_service.registered_tools
        assert mcp_service.registered_tools["read_file"]["client_id"] == client_id

def test_mcp_disconnect_cleanup():
    """Verify that tools are removed when an MCP client disconnects."""
    client_id = "temp_agent"
    
    with client.websocket_connect(f"/mcp/ws/{client_id}") as websocket:
        websocket.send_text(json.dumps({
            "jsonrpc": "2.0",
            "method": "tools/list",
            "params": {"tools": [{"name": "temp_tool", "description": "..."}]}
        }))
        time.sleep(0.1)
        assert "temp_tool" in mcp_service.registered_tools
        
    # After exiting the 'with' block, client is disconnected
    time.sleep(0.1)
    assert "temp_tool" not in mcp_service.registered_tools
