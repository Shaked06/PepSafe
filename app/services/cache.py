"""Redis caching service for weather data."""

import json
import logging
from typing import Any, Optional

import redis.asyncio as redis

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class CacheService:
    """Async Redis cache wrapper with graceful degradation."""

    def __init__(self) -> None:
        self._client: Optional[redis.Redis] = None

    async def connect(self) -> None:
        """Initialize Redis connection."""
        try:
            self._client = redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            await self._client.ping()
            logger.info("Redis connection established")
        except Exception as e:
            logger.warning(f"Redis connection failed, cache disabled: {e}")
            self._client = None

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None

    async def get(self, key: str) -> Optional[dict[str, Any]]:
        """
        Get cached value by key.

        Returns None if key doesn't exist or Redis unavailable.
        """
        if not self._client:
            return None

        try:
            value = await self._client.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.warning(f"Cache get failed: {e}")
            return None

    async def set(
        self, key: str, value: dict[str, Any], ttl_seconds: Optional[int] = None
    ) -> bool:
        """
        Set cached value with optional TTL.

        Returns True if successful, False otherwise.
        """
        if not self._client:
            return False

        try:
            ttl = ttl_seconds or settings.redis_weather_ttl_seconds
            await self._client.setex(key, ttl, json.dumps(value))
            return True
        except Exception as e:
            logger.warning(f"Cache set failed: {e}")
            return False

    @property
    def is_available(self) -> bool:
        """Check if cache is available."""
        return self._client is not None


# Global cache instance
cache_service = CacheService()
