from fastapi import APIRouter, Depends
from app.core.security import validate_api_key

router = APIRouter()

@router.get("/models", dependencies=[Depends(validate_api_key)])
async def list_models():
    # This will be delegated to the Provider Aggregator in Phase 2
    return {"object": "list", "data": []}
