from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, List

class Settings(BaseSettings):
    # App Settings
    APP_NAME: str = "Universal AI Gateway"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    
    # Security
    API_KEY_HEADER_NAME: str = "Authorization"
    # For now, allow sk-fake, but in prod this would be a real list or DB check
    ALLOWED_API_KEYS: List[str] = ["sk-fake"]
    
    # Provider Settings
    DEEPSEEK_AUTH_TOKEN: str = ""
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    
    # Cache & State
    REDIS_URL: str = "redis://localhost:6379"
    
    # Gateway behavior
    MAX_CONTEXT_CHARS: int = 1000000
    DEFAULT_MODEL_ALIAS: str = "auto"
    
    # Cloudflare / Stealth
    CHROME_PATH: Optional[str] = None
    USE_HEADLESS: bool = True
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
