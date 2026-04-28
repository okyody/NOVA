"""
NOVA Security Middleware
========================
JWT authentication, rate limiting, CORS, security headers, input validation.
Enterprise-grade protection for the API layer.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

log = logging.getLogger("nova.security")


# ─── JWT Authentication ──────────────────────────────────────────────────────

try:
    import jwt as pyjwt
    HAS_JWT = True
except ImportError:
    HAS_JWT = False


class JWTAuth:
    """JWT token creation and validation."""

    def __init__(self, secret: str, algorithm: str = "HS256", expire_minutes: int = 1440) -> None:
        self._secret = secret
        self._algorithm = algorithm
        self._expire_minutes = expire_minutes

    def create_token(
        self,
        subject: str,
        roles: list[str] | None = None,
        permissions: list[str] | None = None,
        tenant_ids: list[str] | None = None,
    ) -> str:
        if not HAS_JWT:
            raise RuntimeError("PyJWT not installed. Run: pip install PyJWT")
        payload = {
            "sub": subject,
            "roles": roles or ["viewer"],
            "permissions": permissions or [],
            "tenant_ids": tenant_ids or [],
            "iat": int(time.time()),
            "exp": int(time.time()) + self._expire_minutes * 60,
        }
        return pyjwt.encode(payload, self._secret, algorithm=self._algorithm)

    def verify_token(self, token: str) -> dict[str, Any] | None:
        if not HAS_JWT:
            return None
        try:
            payload = pyjwt.decode(token, self._secret, algorithms=[self._algorithm])
            return payload
        except pyjwt.ExpiredSignatureError:
            log.warning("JWT token expired")
            return None
        except pyjwt.InvalidTokenError as e:
            log.warning("Invalid JWT token: %s", e)
            return None


# ─── Rate Limiter (in-memory, production should use Redis) ───────────────────

class RateLimiter:
    """
    Sliding window rate limiter.
    Production: replace with Redis-backed limiter for multi-instance.
    """

    def __init__(self, max_requests: int = 60, window_seconds: int = 60) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._requests: dict[str, list[float]] = {}

    def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        window_start = now - self._window_seconds

        if key not in self._requests:
            self._requests[key] = []

        # Remove expired entries
        self._requests[key] = [t for t in self._requests[key] if t > window_start]

        if len(self._requests[key]) >= self._max_requests:
            return False

        self._requests[key].append(now)
        return True

    def remaining(self, key: str) -> int:
        now = time.monotonic()
        window_start = now - self._window_seconds
        if key not in self._requests:
            return self._max_requests
        active = [t for t in self._requests[key] if t > window_start]
        return max(0, self._max_requests - len(active))


# ─── Input Validator ─────────────────────────────────────────────────────────

_MAX_TEXT_LENGTH = 50000
_MAX_JSON_DEPTH = 10


class InputValidator:
    """Validate incoming requests to prevent injection and abuse."""

    # Patterns that indicate potential injection
    _DANGEROUS_PATTERNS = [
        "__import__", "exec(", "eval(", "compile(", "open(",
        "os.system", "subprocess", "pickle.loads",
        "<script", "javascript:", "onerror=", "onload=",
    ]

    @classmethod
    def validate_text(cls, text: str, max_length: int = _MAX_TEXT_LENGTH) -> tuple[bool, str]:
        """Validate text input. Returns (is_valid, reason)."""
        if not text or not text.strip():
            return False, "Text cannot be empty"
        if len(text) > max_length:
            return False, f"Text exceeds maximum length ({max_length})"
        text_lower = text.lower()
        for pattern in cls._DANGEROUS_PATTERNS:
            if pattern in text_lower:
                return False, f"Potentially dangerous input detected"
        return True, ""

    @classmethod
    def validate_json_depth(cls, data: Any, max_depth: int = _MAX_JSON_DEPTH, current: int = 0) -> bool:
        """Check JSON nesting depth to prevent deep nesting attacks."""
        if current > max_depth:
            return False
        if isinstance(data, dict):
            return all(cls.validate_json_depth(v, max_depth, current + 1) for v in data.values())
        if isinstance(data, list):
            return all(cls.validate_json_depth(v, max_depth, current + 1) for v in data)
        return True

    @classmethod
    def sanitize_filename(cls, name: str) -> str:
        """Sanitize a filename to prevent path traversal."""
        import re
        name = name.replace("..", "").replace("/", "").replace("\\", "")
        name = re.sub(r'[^\w\-.]', '_', name)
        return name[:255]


# ─── API Key Authentication ──────────────────────────────────────────────────

class APIKeyAuth:
    """Simple API key authentication."""

    def __init__(self, valid_keys: set[str] | None = None) -> None:
        self._valid_keys = valid_keys or set()

    def add_key(self, key: str) -> None:
        self._valid_keys.add(key)

    def verify(self, key: str) -> bool:
        if not self._valid_keys:
            return True  # No keys configured = no auth required
        for valid_key in self._valid_keys:
            if hmac.compare_digest(key, valid_key):
                return True
        return False


# ─── FastAPI Middleware ───────────────────────────────────────────────────────

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self' ws: wss:"
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limit middleware per client IP."""

    def __init__(self, app: Any, limiter: RateLimiter | None = None) -> None:
        super().__init__(app)
        self._limiter = limiter or RateLimiter(max_requests=120, window_seconds=60)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        key = f"rate:{client_ip}"

        if not self._limiter.is_allowed(key):
            log.warning("Rate limit exceeded for %s", client_ip)
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Please try again later."},
                headers={"Retry-After": str(self._limiter._window_seconds)},
            )

        response = await call_next(request)
        remaining = self._limiter.remaining(key)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response


class AuthMiddleware(BaseHTTPMiddleware):
    """JWT / API key authentication middleware."""

    # Paths that don't require authentication
    PUBLIC_PATHS = {
        "/health", "/metrics", "/docs", "/openapi.json", "/redoc",
        "/studio/", "/favicon.ico", "/api/auth/token",
    }

    def __init__(
        self,
        app: Any,
        jwt_auth: JWTAuth | None = None,
        api_key_auth: APIKeyAuth | None = None,
        enabled: bool = False,
    ) -> None:
        super().__init__(app)
        self._jwt = jwt_auth
        self._api_key = api_key_auth or APIKeyAuth()
        self._enabled = enabled

    def _attach_api_key_user(self, request: Request, api_key: str) -> bool:
        if api_key and self._api_key.verify(api_key):
            request.state.user = {
                "sub": "api_key",
                "roles": ["service_admin"],
                "permissions": ["*"],
                "tenant_ids": [],
                "auth_type": "api_key",
            }
            return True
        return False

    def _attach_bearer_user(self, request: Request, auth_header: str) -> bool:
        if auth_header.startswith("Bearer ") and self._jwt:
            token = auth_header[7:]
            payload = self._jwt.verify_token(token)
            if payload:
                request.state.user = payload
                return True
        return False

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self._enabled:
            return await call_next(request)

        path = request.url.path
        api_key = request.headers.get("X-API-Key", "")
        auth_header = request.headers.get("Authorization", "")

        # Best-effort identity attachment for public endpoints like Studio.
        self._attach_api_key_user(request, api_key) or self._attach_bearer_user(request, auth_header)

        # Allow public paths and WebSocket upgrades
        if path in self.PUBLIC_PATHS or any(path.startswith(p) for p in self.PUBLIC_PATHS):
            return await call_next(request)
        if request.url.path.startswith("/ws/"):
            return await call_next(request)
        if request.method == "GET" and path.startswith("/studio"):
            return await call_next(request)

        # Check API key header
        if self._attach_api_key_user(request, api_key):
            return await call_next(request)

        # Check JWT Bearer token
        if self._attach_bearer_user(request, auth_header):
            return await call_next(request)

        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required. Provide X-API-Key or Bearer token."},
        )


class RequestValidationMiddleware(BaseHTTPMiddleware):
    """Validate request size and content."""

    MAX_BODY_SIZE = 10 * 1024 * 1024  # 10MB

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Check content length
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.MAX_BODY_SIZE:
            return JSONResponse(
                status_code=413,
                content={"detail": "Request body too large"},
            )
        return await call_next(request)


# ─── Setup helper ────────────────────────────────────────────────────────────

def setup_security_middleware(
    app: FastAPI,
    auth_enabled: bool = False,
    jwt_secret: str = "change-me-in-production",
    jwt_expire_minutes: int = 1440,
    api_keys: set[str] | None = None,
    allowed_origins: list[str] | None = None,
    rate_limit_max: int = 120,
    rate_limit_window: int = 60,
) -> JWTAuth | None:
    """
    Configure all security middleware on a FastAPI app.

    Returns the JWTAuth instance (for token creation) if auth is enabled.
    """
    # CORS
    origins = allowed_origins or ["http://localhost:3000", "http://localhost:8765"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Security headers
    app.add_middleware(SecurityHeadersMiddleware)

    # Rate limiting
    limiter = RateLimiter(max_requests=rate_limit_max, window_seconds=rate_limit_window)
    app.add_middleware(RateLimitMiddleware, limiter=limiter)

    # Request validation
    app.add_middleware(RequestValidationMiddleware)

    # Authentication
    jwt_auth = None
    if auth_enabled:
        if jwt_secret == "change-me-in-production":
            log.critical(
                "⚠️  JWT secret is still the default value! "
                "Set NOVA_AUTH_JWT_SECRET to a strong random string in production."
            )
        jwt_auth = JWTAuth(secret=jwt_secret, expire_minutes=jwt_expire_minutes)
        api_key_auth = APIKeyAuth(valid_keys=api_keys or set())
        app.add_middleware(AuthMiddleware, jwt_auth=jwt_auth, api_key_auth=api_key_auth, enabled=True)
        log.info("API authentication enabled (JWT + API key)")
    else:
        log.info("API authentication disabled (set NOVA_AUTH_ENABLED=true to enable)")

    return jwt_auth
