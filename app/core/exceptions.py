class GatewayError(Exception):
    """Base exception for the gateway"""
    def __init__(self, message: str, code: str = "internal_error", status_code: int = 500):
        self.message = message
        self.code = code
        self.status_code = status_code
        super().__init__(self.message)

class ProviderError(GatewayError):
    """Raised when a provider returns an error"""
    def __init__(self, message: str, provider: str, status_code: int = 500):
        super().__init__(message, code=f"provider_error_{provider}", status_code=status_code)

class RateLimitError(GatewayError):
    """Raised when the gateway or provider rate limit is hit"""
    def __init__(self, message: str = "Rate limit exceeded"):
        super().__init__(message, code="rate_limit_exceeded", status_code=429)

class AuthError(GatewayError):
    """Raised when authentication fails"""
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, code="unauthorized", status_code=401)
