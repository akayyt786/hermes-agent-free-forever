from app.providers.base import BaseProvider
from app.schemas.internal import InternalRequest, InternalResponse, InternalChunk
from typing import List, AsyncGenerator

class OllamaProvider(BaseProvider):
    async def complete(self, request: InternalRequest) -> InternalResponse:
        raise NotImplementedError()
    async def stream(self, request: InternalRequest) -> AsyncGenerator[InternalChunk, None]:
        yield InternalChunk()
    async def list_models(self) -> List[str]:
        return []
    async def health_check(self) -> bool:
        return True
