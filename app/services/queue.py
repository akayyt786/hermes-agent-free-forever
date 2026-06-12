import asyncio
import json
import time
from typing import Any, Dict, Optional
import redis.asyncio as redis
import structlog

from app.core.config import settings
from app.core.exceptions import RateLimitError

log = structlog.get_logger(__name__)

class QueueService:
    """Manages request queuing and rate limiting using Redis."""
    
    def __init__(self):
        try:
            self.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
            self.enabled = True
        except Exception as e:
            log.warning("redis_disabled", error=str(e))
            self.enabled = False
        self.provider_lock_timeout = 60 

    async def check_rate_limit(self, user_id: str, limit: int = 10, window: int = 60):
        if not self.enabled:
            return
        
        key = f"rate_limit:{user_id}"
        try:
            current = await self.redis.get(key)
            if current and int(current) >= limit:
                log.warning("user_rate_limited", user_id=user_id)
                raise RateLimitError(f"User rate limit exceeded: {limit} requests per {window}s")
                
            async with self.redis.pipeline(transaction=True) as pipe:
                await pipe.incr(key)
                await pipe.expire(key, window)
                await pipe.execute()
        except Exception:
            pass # Fail open if redis dies

    async def acquire_provider_lock(self, provider_name: str):
        if not self.enabled:
            return True
            
        lock_key = f"lock:provider:{provider_name}"
        """
        Ensures we only send one request at a time to certain unofficial providers 
        to avoid detection/rate-limiting.
        """
        if not self.enabled:
            return True

        lock_key = f"lock:provider:{provider_name}"
        
        # Wait up to 30 seconds for the lock
        start_time = time.time()
        try:
            while time.time() - start_time < 30:
                acquired = await self.redis.set(lock_key, "locked", ex=self.provider_lock_timeout, nx=True)
                if acquired:
                    log.debug("provider_lock_acquired", provider=provider_name)
                    return True
                await asyncio.sleep(0.5)
        except Exception:
            return True # Fail open
            
        log.error("provider_lock_timeout", provider=provider_name)
        raise RateLimitError("Provider is currently busy. Please try again in a few seconds.")

    async def release_provider_lock(self, provider_name: str):
        if not self.enabled:
            return
        lock_key = f"lock:provider:{provider_name}"
        try:
            await self.redis.delete(lock_key)
            log.debug("provider_lock_released", provider=provider_name)
        except Exception:
            pass

    async def get_session_metadata(self, session_id: str) -> Dict[str, Any]:
        if not self.enabled:
            return {}
        try:
            data = await self.redis.get(f"session:{session_id}")
            return json.loads(data) if data else {}
        except Exception:
            return {}

    async def save_session_metadata(self, session_id: str, metadata: Dict[str, Any]):
        if not self.enabled:
            return
        try:
            await self.redis.set(f"session:{session_id}", json.dumps(metadata), ex=86400 * 7)
        except Exception:
            pass

queue_service = QueueService()
