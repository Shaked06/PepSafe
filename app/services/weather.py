"""OpenWeatherMap integration with Redis caching."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.config import get_settings
from app.core.geo import geohash_key
from app.services.cache import cache_service

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class WeatherData:
    """
    Weather data structure with XGBoost-relevant features.

    All fields are designed to be useful predictors for behavioral analysis:
    - Temperature affects walking speed and outdoor activity
    - Rain/precipitation affects route choices
    - Humidity combined with temp gives "feels like" conditions
    - Wind affects cycling/walking patterns
    - Visibility affects driving behavior
    """

    temp_c: float
    feels_like_c: float
    humidity_pct: float
    rain_1h_mm: float
    wind_speed_ms: float
    wind_gust_ms: Optional[float]
    visibility_m: float
    condition: str
    condition_id: int  # OpenWeatherMap condition code for ML encoding
    is_daylight: bool
    fetched_at: datetime


class WeatherService:
    """
    OpenWeatherMap API client with intelligent caching.

    Caching Strategy:
    - Uses geohash bucketing (~1km precision) to reduce unique API calls
    - 10-minute TTL balances freshness vs API quota
    - Graceful degradation when cache/API unavailable
    """

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None
        self._cache_hits = 0
        self._cache_misses = 0
        self._api_errors = 0

    async def start(self) -> None:
        """Initialize HTTP client with connection pooling."""
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )
        logger.info("WeatherService started")

    async def stop(self) -> None:
        """Close HTTP client and log stats."""
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info(
            f"WeatherService stopped - Cache hits: {self._cache_hits}, "
            f"misses: {self._cache_misses}, API errors: {self._api_errors}"
        )

    def _cache_key(self, lat: float, lon: float) -> str:
        """
        Generate cache key using geohash for ~1km bucketing.

        This reduces API calls by sharing cached weather data
        for nearby coordinates within the same ~1km² area.
        """
        geo = geohash_key(lat, lon, precision=2)
        return f"weather:v2:{geo}"

    @property
    def stats(self) -> dict:
        """Get cache/API statistics."""
        total = self._cache_hits + self._cache_misses
        hit_rate = (self._cache_hits / total * 100) if total > 0 else 0
        return {
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "api_errors": self._api_errors,
            "hit_rate_pct": round(hit_rate, 1),
        }

    async def get_weather(self, lat: float, lon: float) -> Optional[WeatherData]:
        """
        Fetch weather data for coordinates.

        Uses Redis cache with geohash bucketing to reduce API calls.
        Falls back gracefully if cache or API unavailable.

        Args:
            lat: Latitude (NEVER from home zone - enforced by caller)
            lon: Longitude (NEVER from home zone - enforced by caller)

        Returns:
            WeatherData or None if unavailable
        """
        cache_key = self._cache_key(lat, lon)

        # Try cache first
        cached = await cache_service.get(cache_key)
        if cached:
            self._cache_hits += 1
            logger.debug(f"Weather cache hit for {cache_key}")
            return WeatherData(
                temp_c=cached["temp_c"],
                feels_like_c=cached.get("feels_like_c", cached["temp_c"]),
                humidity_pct=cached.get("humidity_pct", 50.0),
                rain_1h_mm=cached["rain_1h_mm"],
                wind_speed_ms=cached.get("wind_speed_ms", 0.0),
                wind_gust_ms=cached.get("wind_gust_ms"),
                visibility_m=cached.get("visibility_m", 10000.0),
                condition=cached["condition"],
                condition_id=cached.get("condition_id", 800),
                is_daylight=cached.get("is_daylight", True),
                fetched_at=datetime.fromisoformat(cached["fetched_at"]),
            )

        self._cache_misses += 1

        # Fetch from API
        if not self._client:
            logger.warning("Weather HTTP client not initialized")
            return None

        if not settings.openweathermap_api_key:
            logger.warning("Weather API not configured")
            return None

        try:
            response = await self._client.get(
                f"{settings.openweathermap_base_url}/weather",
                params={
                    "lat": lat,
                    "lon": lon,
                    "appid": settings.openweathermap_api_key,
                    "units": "metric",
                },
            )
            response.raise_for_status()
            data = response.json()

            now = datetime.now(timezone.utc)

            # Extract sunrise/sunset for daylight calculation
            sys_data = data.get("sys", {})
            sunrise = sys_data.get("sunrise", 0)
            sunset = sys_data.get("sunset", 0)
            current_ts = int(now.timestamp())
            is_daylight = sunrise < current_ts < sunset if sunrise and sunset else True

            # Extract weather condition
            weather_list = data.get("weather", [])
            condition = weather_list[0]["main"].lower() if weather_list else "unknown"
            condition_id = weather_list[0]["id"] if weather_list else 800

            weather = WeatherData(
                temp_c=data["main"]["temp"],
                feels_like_c=data["main"].get("feels_like", data["main"]["temp"]),
                humidity_pct=data["main"].get("humidity", 50.0),
                rain_1h_mm=data.get("rain", {}).get("1h", 0.0),
                wind_speed_ms=data.get("wind", {}).get("speed", 0.0),
                wind_gust_ms=data.get("wind", {}).get("gust"),
                visibility_m=data.get("visibility", 10000.0),
                condition=condition,
                condition_id=condition_id,
                is_daylight=is_daylight,
                fetched_at=now,
            )

            # Cache the result
            await cache_service.set(
                cache_key,
                {
                    "temp_c": weather.temp_c,
                    "feels_like_c": weather.feels_like_c,
                    "humidity_pct": weather.humidity_pct,
                    "rain_1h_mm": weather.rain_1h_mm,
                    "wind_speed_ms": weather.wind_speed_ms,
                    "wind_gust_ms": weather.wind_gust_ms,
                    "visibility_m": weather.visibility_m,
                    "condition": weather.condition,
                    "condition_id": weather.condition_id,
                    "is_daylight": weather.is_daylight,
                    "fetched_at": weather.fetched_at.isoformat(),
                },
            )

            logger.debug(f"Weather fetched and cached for {cache_key}")
            return weather

        except httpx.TimeoutException:
            self._api_errors += 1
            logger.warning("Weather API timeout")
            return None
        except httpx.HTTPStatusError as e:
            self._api_errors += 1
            logger.warning(f"Weather API error: {e.response.status_code}")
            return None
        except Exception as e:
            self._api_errors += 1
            logger.warning(f"Weather fetch failed: {e}")
            return None


# Global weather service instance
weather_service = WeatherService()
