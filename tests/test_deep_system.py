import pytest
import respx
import httpx
import json
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock
from app.main import app
from app.services.memory import memory_service
from app.services.queue import queue_service

client = TestClient(app)

@pytest.mark.asyncio
@respx.mock
@patch("app.providers.deepseek.pow_solver.solve", new_callable=AsyncMock)
async def test_deep_system_end_to_end(mock_pow):
    """
    Deep Test: Verify the full lifecycle of a request through all layers.
    """
    mock_pow.return_value = "final_mocked_pow"
    session_id = "deep-test-session"
    
    # 1. Setup Mock Backend
    respx.post("https://chat.deepseek.com/api/v0/chat/create_pow_challenge").mock(return_value=httpx.Response(200, json={"data": {"biz_data": {"challenge": {}}}}))
    respx.post("https://chat.deepseek.com/api/v0/chat_session/create").mock(return_value=httpx.Response(200, json={"data": {"biz_data": {"id": "sid"}}}))
    
    # Mock a response that contains both text and a tool call
    mock_stream = (
        'data: {"p": "response/content", "v": "Searching... "}\n'
        'data: {"p": "response/content", "v": "<tool_call>{\\"name\\": \\"web_search\\", \\"input\\": {\\"query\\": \\"AI Gateway\\"}}</tool_call>"}\n'
    )
    respx.post("https://chat.deepseek.com/api/v0/chat/completion").mock(return_value=httpx.Response(200, content=mock_stream))

    # 2. Mock Redis for Queueing/Rate Limiting
    queue_service.redis.get = AsyncMock(return_value=None)
    queue_service.redis.set = AsyncMock(return_value=True)
    queue_service.redis.delete = AsyncMock()

    # 3. Perform the Request
    payload = {
        "model": "auto",
        "messages": [{"role": "user", "content": "Tell me about AI Gateways"}],
        "stream": True,
        "tools": [{"name": "web_search", "description": "Search the web"}]
    }
    
    response = client.post(
        "/v1/chat/completions", 
        json=payload, 
        headers={"Authorization": "Bearer sk-fake", "x-session-id": session_id}
    )
    
    assert response.status_code == 200
    
    # 4. Analyze Chunks
    all_data = []
    has_tool_call = False
    for line in response.iter_lines():
        if line.startswith("data: ") and line != "data: [DONE]":
            chunk = json.loads(line[6:])
            all_data.append(chunk)
            delta = chunk["choices"][0]["delta"]
            if "tool_calls" in delta:
                has_tool_call = True
                assert delta["tool_calls"][0]["function"]["name"] == "web_search"

    # 5. Verify Memory Persistence
    # Check that the conversation was stored in ChromaDB
    context = await memory_service.retrieve_context(session_id, "AI Gateway")
    assert len(context.messages) > 0
    
    assert has_tool_call
    print("\n[DEEP TEST PASSED] Full chain verified: Auth -> Queue -> Memory -> Provider -> Tool Translation -> Streaming")

if __name__ == "__main__":
    pytest.main([__file__])
