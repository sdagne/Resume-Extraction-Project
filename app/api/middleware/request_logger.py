# Request logger middleware
# app/api/middleware/request_logger.py

import time
import uuid
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.utils.logger import get_logger

logger = get_logger(__name__)

# ─── Paths to skip logging ─────────────────────────────────────────────────────
SKIP_PATHS = {
    "/health",
    "/metrics",
    "/favicon.ico",
    "/docs",
    "/redoc",
    "/openapi.json",
}


class RequestLoggerMiddleware(BaseHTTPMiddleware):
    """
    Middleware that logs every HTTP request and response.

    Captures:
      - Request method, path, client IP
      - Response status code
      - Request duration
      - Unique request ID (added to response headers)
    """

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(
        self,
        request:  Request,
        call_next: Callable,
    ) -> Response:
        # Skip logging for health/static paths
        if request.url.path in SKIP_PATHS:
            return await call_next(request)

        # Generate unique request ID
        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id

        # Capture request details
        start_time  = time.time()
        client_ip   = self._get_client_ip(request)
        method      = request.method
        path        = request.url.path
        query       = str(request.url.query) if request.url.query else ""

        logger.info(
            f"→ {method} {path}"
            f"{'?' + query if query else ''} | "
            f"ip={client_ip} | "
            f"id={request_id}"
        )

        # Process request
        try:
            response = await call_next(request)
        except Exception as e:
            duration = round(time.time() - start_time, 3)
            logger.error(
                f"✗ {method} {path} | "
                f"error={type(e).__name__} | "
                f"duration={duration}s | "
                f"id={request_id}"
            )
            raise

        # Log response
        duration    = round(time.time() - start_time, 3)
        status_code = response.status_code

        log_fn = logger.info if status_code < 400 else logger.warning
        if status_code >= 500:
            log_fn = logger.error

        log_fn(
            f"← {method} {path} | "
            f"status={status_code} | "
            f"duration={duration}s | "
            f"id={request_id}"
        )

        # Add request ID to response headers
        response.headers["X-Request-ID"]    = request_id
        response.headers["X-Process-Time"]  = str(duration)

        return response

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP, handling proxies."""
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"
