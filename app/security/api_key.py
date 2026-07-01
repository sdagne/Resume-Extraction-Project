# app/security/api_key.py

import secrets
from typing import Optional

from fastapi import Security, HTTPException, status
from fastapi.security.api_key import APIKeyHeader

from app.utils.logger import get_logger

logger = get_logger(__name__)

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(api_key: Optional[str] = Security(_API_KEY_HEADER)) -> str:
    """
    FastAPI dependency that validates the X-API-Key header.

    Raises:
        401 — if the header is missing.
        403 — if the key does not match.

    Usage:
        @router.post("/endpoint")
        async def endpoint(key: str = Depends(require_api_key)):
            ...
    """
    from app.config import settings

    # Auth disabled — allow all traffic
    if not settings.ENABLE_API_KEY_AUTH:
        return "auth-disabled"

    if not api_key:
        logger.warning("API request rejected: missing X-API-Key header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-Key header is required.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # Constant-time comparison to prevent timing attacks
    valid = secrets.compare_digest(api_key, settings.API_KEY)
    if not valid:
        logger.warning(f"API request rejected: invalid API key (first 8 chars: {api_key[:8]}...)")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key.",
        )

    return api_key
