from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from app.schemas.openai import ChatCompletionRequest, ChatCompletionResponse
from app.core.security import validate_api_key
from app.services.router import router_service
from app.services.streaming import streaming_service
from app.schemas.internal import InternalRequest, InternalMessage

router = APIRouter()

@router.post("/chat/completions", dependencies=[Depends(validate_api_key)])
async def create_chat_completion(request: ChatCompletionRequest, req: Request):
    session_id = req.headers.get("x-session-id", "default")
    
    # Convert OpenAI request to Internal request
    internal_msgs = [
        InternalMessage(role=m.role, content=str(m.content)) 
        for m in request.messages
    ]
    internal_req = InternalRequest(
        model=request.model,
        messages=internal_msgs,
        stream=request.stream or False,
        tools=request.tools,
        temperature=request.temperature or 1.0
    )
    
    if request.stream:
        raw_stream = router_service.route_stream(internal_req, session_id=session_id)
        return StreamingResponse(
            streaming_service.normalize_stream(raw_stream, request.model), 
            media_type="text/event-stream"
        )
    
    response = await router_service.route_request(internal_req, session_id=session_id)
    return response
