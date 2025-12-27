"""Security middleware for API authentication and rate limiting."""

import hashlib
import logging
import time
from collections import defaultdict
from typing import Callable, Optional

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class APIKeyMiddleware(BaseHTTPMiddleware):
    """
    Middleware to validate X-API-KEY header on protected endpoints.

    Protected paths: /api/v1/ping/*
    Unprotected: /health, /docs, /openapi.json, /
    """

    PROTECTED_PREFIXES = ("/api/v1/ping",)

    async def dispatch(self, request: Request, call_next: Callable):
        path = request.url.path

        # Skip auth for non-protected endpoints
        if not any(path.startswith(prefix) for prefix in self.PROTECTED_PREFIXES):
            return await call_next(request)

        # Skip auth if no API key is configured (development mode)
        if not settings.pepsafe_api_key:
            logger.warning("API key not configured - running in INSECURE mode")
            return await call_next(request)

        # Get API key from header
        api_key = request.headers.get(settings.api_key_header_name)

        if not api_key:
            # PRIVACY: Never log the path (may contain sensitive query params)
            logger.warning("API request rejected: missing API key")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Missing API key. Include X-API-KEY header."},
            )

        # Constant-time comparison to prevent timing attacks
        if not _secure_compare(api_key, settings.pepsafe_api_key):
            logger.warning("API request rejected: invalid API key")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid API key."},
            )

        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Simple in-memory rate limiting middleware.

    Uses a sliding window algorithm with per-IP tracking.
    For production with multiple workers, use Redis-based limiting.
    """

    def __init__(self, app, requests_per_minute: int = 60, burst: int = 10):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.burst = burst
        self.window_seconds = 60
        # In-memory storage: {ip: [(timestamp, count), ...]}
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._last_cleanup = time.time()

    async def dispatch(self, request: Request, call_next: Callable):
        # Only rate limit ping endpoints
        if not request.url.path.startswith("/api/v1/ping"):
            return await call_next(request)

        # Get client IP (handle proxies)
        client_ip = self._get_client_ip(request)

        # Clean up old entries periodically
        now = time.time()
        if now - self._last_cleanup > 60:
            self._cleanup_old_entries(now)
            self._last_cleanup = now

        # Check rate limit
        if self._is_rate_limited(client_ip, now):
            logger.warning(f"Rate limit exceeded for client")  # No IP in logs
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "detail": "Rate limit exceeded. Try again later.",
                    "retry_after_seconds": 60,
                },
                headers={"Retry-After": "60"},
            )

        # Record this request
        self._requests[client_ip].append(now)

        return await call_next(request)

    def _get_client_ip(self, request: Request) -> str:
        """Get client IP, handling reverse proxies."""
        # Check X-Forwarded-For header (set by reverse proxies)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Take the first IP (original client)
            return forwarded_for.split(",")[0].strip()

        # Check X-Real-IP header
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        # Fall back to direct client IP
        return request.client.host if request.client else "unknown"

    def _is_rate_limited(self, client_ip: str, now: float) -> bool:
        """Check if client has exceeded rate limit."""
        window_start = now - self.window_seconds

        # Filter to requests within window
        recent = [ts for ts in self._requests[client_ip] if ts > window_start]
        self._requests[client_ip] = recent

        # Check if over limit
        return len(recent) >= self.requests_per_minute + self.burst

    def _cleanup_old_entries(self, now: float) -> None:
        """Remove old entries to prevent memory growth."""
        window_start = now - self.window_seconds * 2

        for ip in list(self._requests.keys()):
            self._requests[ip] = [ts for ts in self._requests[ip] if ts > window_start]
            if not self._requests[ip]:
                del self._requests[ip]


def _secure_compare(a: str, b: str) -> bool:
    """
    Constant-time string comparison to prevent timing attacks.

    Uses HMAC comparison which is constant-time regardless of
    where the strings differ.
    """
    if len(a) != len(b):
        return False

    # Hash both strings to get constant-time comparison
    a_hash = hashlib.sha256(a.encode()).digest()
    b_hash = hashlib.sha256(b.encode()).digest()

    # Use XOR to compare (constant time)
    result = 0
    for x, y in zip(a_hash, b_hash):
        result |= x ^ y

    return result == 0
