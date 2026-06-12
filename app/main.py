import time
from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging import setup_logging, setup_telemetry
from app.api.v1 import completions, models
from app.api.mcp import router as mcp_router

setup_logging()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Production-grade Universal AI Gateway"
)

setup_telemetry(app)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Exception handler for general errors
@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": {"message": str(exc), "type": "server_error", "param": None, "code": None}}
    )

# Routers
app.include_router(completions.router, prefix="/v1")
app.include_router(models.router, prefix="/v1")
app.include_router(mcp_router, prefix="/mcp")

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": settings.APP_VERSION,
        "uptime": "not_implemented_yet",
        "timestamp": int(time.time())
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
