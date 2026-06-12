import pytest
import respx
import httpx
import json
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
from app.main import app
from app.core.config import settings

client = TestClient(app)

@pytest.mark.asyncio
@respx.mock
@patch("app.providers.deepseek.pow_solver.solve", new_callable=AsyncMock)
async def test_streaming_normalization(mock_pow):
    """Verify that streaming output is normalized to OpenAI SSE format."""
    mock_pow.return_value = "mocked_pow"
    
    # Mock DeepSeek Stream with XML Tool Call
    xml_tool_call = '<tool_call>{"name": "bash", "input": {"command": "ls"}}</tool_call>'
    mock_stream_content = (
        'data: {"p": "response/content", "v": "I will run ls: "}\n'
        f'data: {{"p": "response/content", "v": {json.dumps(xml_tool_call)}}}\n'
    )
    
    respx.post("https://chat.deepseek.com/api/v0/chat/create_pow_challenge").mock(return_value=httpx.Response(200, json={"data": {"biz_data": {"challenge": {}}}}))
    respx.post("https://chat.deepseek.com/api/v0/chat_session/create").mock(return_value=httpx.Response(200, json={"data": {"biz_data": {"id": "sid"}}}))
    respx.post("https://chat.deepseek.com/api/v0/chat/completion").mock(return_value=httpx.Response(200, content=mock_stream_content))

    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": "run ls"}],
        "stream": True,
        "tools": [{"name": "bash", "description": "run command"}]
    }
    
    response = client.post("/v1/chat/completions", json=payload, headers={"Authorization": "Bearer sk-fake"})
    
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    
    chunks = []
    for line in response.iter_lines():
        if line.startswith("data: ") and line != "data: [DONE]":
            chunks.append(json.loads(line[6:]))
            
    # Verify OpenAI Chunk Format
    assert len(chunks) > 0
    assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
    
    # Find the chunk with tool calls
    tool_chunk = next((c for c in chunks if "tool_calls" in c["choices"][0]["delta"]), None)
    assert tool_chunk is not None
    assert tool_chunk["choices"][0]["delta"]["tool_calls"][0]["function"]["name"] == "bash"
