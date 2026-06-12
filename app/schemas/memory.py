from pydantic import BaseModel
from typing import List, Optional, Dict, Any

class MemoryContext(BaseModel):
    messages: List[Dict[str, Any]]
    summary: Optional[str] = None
    relevance_scores: Optional[List[float]] = None

class VectorDocument(BaseModel):
    id: str
    text: str
    metadata: Dict[str, Any]
    embedding: Optional[List[float]] = None
