import json
import asyncio
from typing import Dict, List, Any, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import structlog

log = structlog.get_logger(__name__)

class MCPService:
    """Manages Model Context Protocol (MCP) tool registration and execution."""
    
    def __init__(self):
        self.active_clients: Dict[str, WebSocket] = {}
        self.registered_tools: Dict[str, Dict[str, Any]] = {}

    async def handle_connection(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_clients[client_id] = websocket
        log.info("mcp_client_connected", client_id=client_id)
        
        try:
            while True:
                data = await websocket.receive_text()
                message = json.loads(data)
                
                # Handle MCP JSON-RPC messages
                method = message.get("method")
                if method == "tools/list":
                    await self._handle_tools_list(client_id, message)
                elif method == "tools/call":
                    # Handle response from a previously sent tool call
                    pass
        except WebSocketDisconnect:
            log.info("mcp_client_disconnected", client_id=client_id)
            self.active_clients.pop(client_id, None)
            # Cleanup tools for this client
            self.registered_tools = {k: v for k, v in self.registered_tools.items() if v.get("client_id") != client_id}

    async def _handle_tools_list(self, client_id: str, message: Dict[str, Any]):
        tools = message.get("params", {}).get("tools", [])
        for tool in tools:
            name = tool["name"]
            self.registered_tools[name] = {
                "client_id": client_id,
                "schema": tool
            }
        log.info("mcp_tools_registered", client_id=client_id, count=len(tools))

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Invokes a tool on a connected MCP client."""
        tool_info = self.registered_tools.get(name)
        if not tool_info:
            raise ValueError(f"Tool {name} not found in MCP registry")
            
        client_id = tool_info["client_id"]
        websocket = self.active_clients.get(client_id)
        
        if not websocket:
            raise ValueError(f"MCP client {client_id} for tool {name} is disconnected")
            
        call_id = f"call_{uuid.uuid4().hex[:8]}"
        request = {
            "jsonrpc": "2.0",
            "id": call_id,
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments
            }
        }
        
        await websocket.send_text(json.dumps(request))
        # In a real implementation, we'd wait for the response here with a future
        return {"status": "sent", "call_id": call_id}

mcp_service = MCPService()

router = APIRouter()

@router.websocket("/ws/{client_id}")
async def mcp_websocket_endpoint(websocket: WebSocket, client_id: str):
    await mcp_service.handle_connection(websocket, client_id)
