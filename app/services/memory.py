import uuid
from typing import List, Dict, Any, Optional
import chromadb
from chromadb.utils import embedding_functions
import structlog

from app.schemas.memory import MemoryContext, VectorDocument
from app.core.config import settings

log = structlog.get_logger(__name__)

class MemoryService:
    """Manages long-term memory and context retrieval using ChromaDB."""
    
    def __init__(self):
        self.client = chromadb.PersistentClient(path="app/infra/chroma_db")
        # Using a lightweight local embedding function
        self.ef = embedding_functions.DefaultEmbeddingFunction()
        
        # Collection for conversation history
        self.chat_history = self.client.get_or_create_collection(
            name="chat_history",
            embedding_function=self.ef
        )
        
        # Collection for repository knowledge
        self.repo_knowledge = self.client.get_or_create_collection(
            name="repo_knowledge",
            embedding_function=self.ef
        )

    async def store_message(self, session_id: str, role: str, content: str, metadata: Optional[Dict[str, Any]] = None):
        """Stores a message in the vector database."""
        doc_id = f"{session_id}-{uuid.uuid4().hex[:8]}"
        meta = metadata or {}
        meta.update({"session_id": session_id, "role": role})
        
        self.chat_history.add(
            ids=[doc_id],
            documents=[content],
            metadatas=[meta]
        )
        log.debug("message_stored", session_id=session_id, role=role)

    async def retrieve_context(self, session_id: str, query: str, limit: int = 5) -> MemoryContext:
        """Retrieves semantically relevant messages for the current query."""
        
        # Query specifically for this session
        results = self.chat_history.query(
            query_texts=[query],
            n_results=limit,
            where={"session_id": session_id}
        )
        
        messages = []
        # Results are returned in order of relevance
        if results["documents"]:
            for i in range(len(results["documents"][0])):
                messages.append({
                    "role": results["metadatas"][0][i]["role"],
                    "content": results["documents"][0][i]
                })
                
        return MemoryContext(
            messages=messages,
            relevance_scores=results["distances"][0] if results["distances"] else None
        )

    async def clear_session(self, session_id: str):
        """Clears memory for a specific session."""
        self.chat_history.delete(where={"session_id": session_id})
        log.info("session_cleared", session_id=session_id)

memory_service = MemoryService()
