from typing import Dict, Type
import structlog

from app.providers.base import BaseProvider
from app.providers.deepseek import DeepSeekProvider
from app.providers.openai import OpenAIProvider
from app.providers.anthropic import AnthropicProvider
from app.providers.ollama import OllamaProvider
from app.services.memory import memory_service
from app.services.queue import queue_service
from app.schemas.internal import InternalRequest, InternalResponse
from app.core.config import settings

log = structlog.get_logger(__name__)

class RouterService:
    """Intelligent engine to route requests to the best available provider."""
    
    def __init__(self):
        self.providers: Dict[str, BaseProvider] = {
            "deepseek": DeepSeekProvider(auth_token=settings.DEEPSEEK_AUTH_TOKEN),
            # Other providers will be initialized here as implemented
        }
        
    def get_provider(self, model_name: str) -> BaseProvider:
        """Determines the provider based on model name or routing rules."""
        
        # Simple routing logic for now
        if model_name == "auto" or "deepseek" in model_name:
            return self.providers["deepseek"]
            
        # Default fallback
        return self.providers["deepseek"]

    async def route_request(self, request: InternalRequest, session_id: str = "default") -> InternalResponse:
        provider = self.get_provider(request.model)
        
        # 1. Store user message in memory
        user_msg = next((m.content for m in reversed(request.messages) if m.role == "user"), "")
        if user_msg:
            await memory_service.store_message(session_id, "user", user_msg)
        
        # 2. Retrieve relevant context (RAG)
        context = await memory_service.retrieve_context(session_id, user_msg)
        
        # 3. Augment prompt (simplified for Phase 4)
        # In a real scenario, we'd merge context messages avoiding duplicates
        
        log.info("routing_request", model=request.model, provider=provider.__class__.__name__, context_count=len(context.messages))
        
        # 3.5 Acquire Provider Lock (Phase 5)
        provider_name = provider.__class__.__name__
        await queue_service.acquire_provider_lock(provider_name)
        
        try:
            response = await provider.complete(request)
            
            # 4. Store assistant response
            await memory_service.store_message(session_id, "assistant", response.content)
            return response
        finally:
            await queue_service.release_provider_lock(provider_name)

    async def route_stream(self, request: InternalRequest, session_id: str = "default"):
        provider = self.get_provider(request.model)
        
        # Store user message
        user_msg = next((m.content for m in reversed(request.messages) if m.role == "user"), "")
        if user_msg:
            await memory_service.store_message(session_id, "user", user_msg)
            
        provider_name = provider.__class__.__name__
        await queue_service.acquire_provider_lock(provider_name)
        
        full_response = ""
        try:
            log.info("routing_stream", model=request.model, provider=provider_name)
            async for chunk in provider.stream(request):
                if chunk.content:
                    full_response += chunk.content
                yield chunk
            
            # Store full assistant response after stream ends
            await memory_service.store_message(session_id, "assistant", full_response)
        finally:
            await queue_service.release_provider_lock(provider_name)

router_service = RouterService()
