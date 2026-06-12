from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Literal, Union

class InternalMessage(BaseModel):
    role: str
    content: str
    tool_calls: Optional[List[Dict[str, Any]]] = None

class InternalRequest(BaseModel):
    model: str
    messages: List[InternalMessage]
    stream: bool = False
    tools: Optional[List[Dict[str, Any]]] = None
    temperature: float = 1.0

class InternalChunk(BaseModel):
    content: Optional[str] = None
    role: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    finish_reason: Optional[str] = None

class InternalResponse(BaseModel):
    content: str
    role: str = "assistant"
    tool_calls: Optional[List[Dict[str, Any]]] = None
    finish_reason: str = "stop"
    usage: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0}
