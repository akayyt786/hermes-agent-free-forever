import pytest
from unittest.mock import patch, AsyncMock
from app.services.memory import memory_service

@pytest.mark.asyncio
async def test_memory_storage_and_retrieval():
    """Verify that messages are stored and semantically retrieved from ChromaDB."""
    session_id = "test-session-123"
    
    # Clear any old data
    await memory_service.clear_session(session_id)
    
    # Store some messages
    await memory_service.store_message(session_id, "user", "My favorite color is blue.")
    await memory_service.store_message(session_id, "assistant", "That is a nice color!")
    await memory_service.store_message(session_id, "user", "I live in Paris.")
    
    # Retrieve based on semantic query
    context = await memory_service.retrieve_context(session_id, "What do I like?")
    
    # Check if the "blue" message is retrieved (semantic match)
    texts = [m["content"] for m in context.messages]
    assert any("blue" in t for t in texts)
    
    # Check that unrelated sessions don't leak
    other_context = await memory_service.retrieve_context("different-session", "What do I like?")
    assert len(other_context.messages) == 0

    await memory_service.clear_session(session_id)
