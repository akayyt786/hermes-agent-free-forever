import pytest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from app.services.queue import queue_service
from app.core.exceptions import RateLimitError

@pytest.mark.asyncio
async def test_rate_limiter():
    """Verify that the rate limiter correctly tracks and blocks users."""
    user_id = "user_123"
    
    # Mock redis incr and expire
    queue_service.redis.get = AsyncMock(side_effect=["1", "5", "10", "11"])
    queue_service.redis.pipeline = MagicMock()
    
    # Under limit
    await queue_service.check_rate_limit(user_id, limit=10) # uses "1"
    await queue_service.check_rate_limit(user_id, limit=10) # uses "5"
    
    # Hits/Over limit
    with pytest.raises(RateLimitError):
        await queue_service.check_rate_limit(user_id, limit=10) # uses "10" (>=10)

@pytest.mark.asyncio
async def test_provider_lock():
    """Verify that the provider lock prevents concurrent execution."""
    provider = "DeepSeekProvider"
    
    # Mock redis set nx=True
    # First call succeeds, second fails (returns None)
    queue_service.redis.set = AsyncMock(side_effect=[True, None, True])
    queue_service.redis.delete = AsyncMock()
    
    # 1. Acquire lock
    await queue_service.acquire_provider_lock(provider)
    
    # 2. Try to acquire again (should fail/retry)
    # We use a short sleep in the service, so this should trigger retries
    # In this mock, the 3rd call to set returns True, simulating a successful retry
    lock_task = asyncio.create_task(queue_service.acquire_provider_lock(provider))
    
    # Wait for the task to complete
    await lock_task
    
    assert queue_service.redis.set.call_count == 3
    await queue_service.release_provider_lock(provider)
