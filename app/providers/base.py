from abc import ABC, abstractmethod
from typing import List, AsyncGenerator
from app.schemas.internal import InternalRequest, InternalResponse, InternalChunk

class BaseProvider(ABC):
    """Abstract base class for all LLM providers"""
    
    @abstractmethod
    async def complete(self, request: InternalRequest) -> InternalResponse:
        """Non-streaming completion"""
        pass
    
    @abstractmethod
    async def stream(self, request: InternalRequest) -> AsyncGenerator[InternalChunk, None]:
        """Streaming completion"""
        pass
    
    @abstractmethod
    async def list_models(self) -> List[str]:
        """List models supported by this provider"""
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """Check if provider is available"""
        pass
