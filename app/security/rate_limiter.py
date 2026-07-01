# app/security/rate_limiter.py

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from fastapi import Request
from fastapi.responses import JSONResponse

# Shared limiter instance (keyed by client IP)
limiter = Limiter(key_func=get_remote_address)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """
    Custom JSON response for rate-limit violations instead of the default plain-text.
    """
    return JSONResponse(
        status_code=429,
        content={
            "error":   "Too Many Requests",
            "detail":  f"Rate limit exceeded: {exc.detail}",
            "hint":    "Slow down requests or contact admin to increase your limit.",
        },
        headers={"Retry-After": "60"},
    )
