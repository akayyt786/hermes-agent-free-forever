import json
import time
import uuid
from typing import AsyncGenerator, Optional
import structlog

from app.schemas.internal import InternalChunk
from app.schemas.openai import ChatCompletionChunk, StreamChoice, Delta

log = structlog.get_logger(__name__)

class StreamingService:
    """Orchestrates and normalizes streaming chunks into OpenAI format."""
    
    async def normalize_stream(
        self, 
        raw_stream: AsyncGenerator[InternalChunk, None], 
        model: str
    ) -> AsyncGenerator[str, None]:
        """
        Wraps a provider stream and yields formatted OpenAI SSE strings.
        """
        request_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        created_time = int(time.time())
        
        # 1. Send the initial role chunk
        role_chunk = ChatCompletionChunk(
            id=request_id,
            created=created_time,
            model=model,
            choices=[StreamChoice(index=0, delta=Delta(role="assistant"), finish_reason=None)]
        )
        yield f"data: {role_chunk.model_dump_json(exclude_none=True)}\n\n"

        async for chunk in raw_stream:
            # Skip empty chunks but DO NOT skip tool calls
            if not chunk.content and not chunk.finish_reason and not chunk.tool_calls:
                continue
                
            # Skip DeepSeek's internal "thinking" blocks so the user only sees the final answer
            if chunk.role == "thinking":
                continue
                
            # Ensure explicitly empty strings are cast to None (required for tool call streams)
            content_val = chunk.content if chunk.content else None
            
            # Create OpenAI formatted choice
            choice = StreamChoice(
                index=0,
                delta=Delta(content=content_val),
                finish_reason=chunk.finish_reason # type: ignore
            )
            
            # If we have tool calls (Phase 3.2 logic), they will be injected here
            if chunk.tool_calls:
                choice.delta.tool_calls = chunk.tool_calls
            
            openai_chunk = ChatCompletionChunk(
                id=request_id,
                created=created_time,
                model=model,
                choices=[choice]
            )
            
            yield f"data: {openai_chunk.model_dump_json(exclude_none=True)}\n\n"

        # 2. Send the final [DONE] signal
        yield "data: [DONE]\n\n"

streaming_service = StreamingService()
