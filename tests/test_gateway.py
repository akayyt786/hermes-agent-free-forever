import pytest
import respx
import httpx
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
from app.main import app
from app.core.config import settings

client = TestClient(app)

@pytest.mark.asyncio
@respx.mock
@patch("app.providers.deepseek.pow_solver.solve", new_callable=AsyncMock)
async def test_chat_completions_routing(mock_pow):
    """Verify that a request to /v1/chat/completions is routed and returns 200."""
    mock_pow.return_value = "mocked_pow_response"
    
    # Mock DeepSeek Web Endpoints
    deepseek_api = respx.route(url__startswith=settings.DEEPSEEK_AUTH_TOKEN or "https://chat.deepseek.com/api/v0")
    
    # 1. Mock PoW Challenge
    respx.post("https://chat.deepseek.com/api/v0/chat/create_pow_challenge").mock(return_value=httpx.Response(
        200, json={"data": {"biz_data": {"challenge": {"algorithm": "sha256", "challenge": "abc", "salt": "123", "signature": "sig", "expire_at": 9999999999}}}}
    ))
    
    # 2. Mock Session Creation
    respx.post("https://chat.deepseek.com/api/v0/chat_session/create").mock(return_value=httpx.Response(
        200, json={"data": {"biz_data": {"id": "test_session_id"}}}
    ))
    
    # 3. Mock Chat Completion (Streaming)
    # The DeepSeek web-chat returns a custom JSON patch stream
    mock_stream_content = (
        'data: {"p": "response/content", "v": "Hello"}\n'
        'data: {"p": "response/content", "v": " world!"}\n'
    )
    respx.post("https://chat.deepseek.com/api/v0/chat/completion").mock(return_value=httpx.Response(
        200, content=mock_stream_content
    ))

    # Perform Request to Gateway
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False
    }
    headers = {"Authorization": "Bearer sk-fake"}
    
    response = client.post("/v1/chat/completions", json=payload, headers=headers)
    
    assert response.status_code == 200
    data = response.json()
    assert "Hello world!" in data["content"]
    assert data["role"] == "assistant"

@pytest.mark.asyncio
async def test_auth_failure():
    """Verify that invalid API keys are rejected."""
    payload = {"model": "deepseek", "messages": [{"role": "user", "content": "hi"}]}
    headers = {"Authorization": "Bearer invalid-key"}
    response = client.post("/v1/chat/completions", json=payload, headers=headers)
    assert response.status_code == 401
