# app/api/middleware/security_headers.py

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Adds standard security headers to every HTTP response.

    Headers added:
        X-Content-Type-Options     — prevent MIME sniffing
        X-Frame-Options            — prevent clickjacking
        X-XSS-Protection           — legacy XSS filter (belt-and-suspenders)
        Referrer-Policy            — control referrer leakage
        Content-Security-Policy    — restrict resource loading
        Permissions-Policy         — disable unused browser features
        Strict-Transport-Security  — enforce HTTPS (omitted in dev)
    """

    def __init__(self, app, is_production: bool = False):
        super().__init__(app)
        self.is_production = is_production

    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)

        response.headers["X-Content-Type-Options"]  = "nosniff"
        response.headers["X-Frame-Options"]         = "DENY"
        response.headers["X-XSS-Protection"]        = "1; mode=block"
        response.headers["Referrer-Policy"]         = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "   # Swagger UI needs this
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "frame-ancestors 'none';"
        )
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=(), payment=()"
        )

        # Only add HSTS on production (where HTTPS is enforced)
        if self.is_production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )

        return response
