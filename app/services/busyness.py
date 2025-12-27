"""
Google Live Busyness placeholder service for XGBoost training.

This module provides mock busyness data that simulates what would come from
Google's Popular Times / Live Busyness API. The mock data follows realistic
patterns based on:
- Time of day (rush hours, lunch, evening)
- Day of week (weekday vs weekend)
- Location type (commercial, residential, transit)

For production, this would integrate with:
- Google Places API (Popular Times)
- Scraping live busyness data
- Alternative sources like SafeGraph, Placer.ai
"""

import hashlib
import logging
import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from app.core.geo import geohash_key, haversine_distance
from app.services.cache import cache_service

logger = logging.getLogger(__name__)


class LocationType(str, Enum):
    """Location classification for busyness modeling."""

    COMMERCIAL = "commercial"  # Shopping areas, business districts
    RESIDENTIAL = "residential"  # Neighborhoods, suburbs
    TRANSIT = "transit"  # Train stations, bus terminals
    RECREATION = "recreation"  # Parks, beaches, sports facilities
    MIXED = "mixed"  # Mixed-use areas
    UNKNOWN = "unknown"


@dataclass
class BusynessData:
    """
    Busyness data structure for XGBoost features.

    Fields designed for behavioral prediction:
    - busyness_pct: Current crowd level (0-100)
    - usual_busyness_pct: Historical average for this time
    - busyness_delta: Deviation from usual (positive = busier than normal)
    - trend: Whether busyness is increasing/decreasing
    - location_type: Classification of the area
    - is_mock: Flag indicating this is simulated data
    """

    busyness_pct: float  # 0-100, current busyness level
    usual_busyness_pct: float  # 0-100, typical for this hour/day
    busyness_delta: float  # Current - usual (can be negative)
    trend: str  # "increasing", "decreasing", "stable"
    location_type: LocationType
    confidence: float  # 0-1, confidence in the estimate
    is_mock: bool  # True for simulated data


class BusynessService:
    """
    Service for estimating location busyness.

    Current Implementation (Mock):
    - Generates realistic busyness patterns based on time/location
    - Uses deterministic seeding for reproducibility in ML training
    - Caches results for consistency within time windows

    Future Implementation:
    - Google Places API integration
    - Live scraping with anti-bot measures
    - ML-based interpolation between known points
    """

    # Known Points of Interest with typical busyness patterns
    # Format: (lat, lon, name, location_type, peak_hours, base_busyness)
    KNOWN_POIS = [
        # Example: Add your actual choke points here
        # (32.0853, 34.7818, "Dizengoff Center", LocationType.COMMERCIAL, [12, 13, 18, 19], 70),
    ]

    def __init__(self) -> None:
        self._cache_hits = 0
        self._cache_misses = 0

    def _cache_key(self, lat: float, lon: float, hour: int) -> str:
        """Generate cache key with hour granularity."""
        geo = geohash_key(lat, lon, precision=3)  # ~100m precision for busyness
        return f"busyness:v1:{geo}:{hour}"

    def _location_seed(self, lat: float, lon: float) -> int:
        """
        Generate deterministic seed from coordinates.

        This ensures the same location always gets the same
        "personality" for busyness patterns, making mock data
        consistent and reproducible for ML training.
        """
        coord_str = f"{lat:.4f},{lon:.4f}"
        return int(hashlib.md5(coord_str.encode()).hexdigest()[:8], 16)

    def _classify_location(self, lat: float, lon: float) -> LocationType:
        """
        Classify location type based on coordinates.

        In production, this would use:
        - Reverse geocoding
        - Land use databases
        - POI density analysis
        """
        seed = self._location_seed(lat, lon)

        # Check proximity to known POIs
        for poi_lat, poi_lon, _, loc_type, _, _ in self.KNOWN_POIS:
            if haversine_distance(lat, lon, poi_lat, poi_lon) < 200:
                return loc_type

        # Pseudo-random classification based on location
        # This creates consistent "zones" across the map
        types = list(LocationType)
        return types[seed % len(types)]

    def _base_pattern(self, hour: int, day_of_week: int, loc_type: LocationType) -> float:
        """
        Generate base busyness pattern for hour/day/location combination.

        Returns busyness percentage (0-100) based on typical patterns.
        """
        # Weekday vs weekend multiplier
        is_weekend = day_of_week >= 5
        weekend_mult = 0.7 if loc_type == LocationType.COMMERCIAL else 1.2

        # Hour-based patterns
        if loc_type == LocationType.COMMERCIAL:
            # Commercial: peaks at lunch and after work
            if 11 <= hour <= 14:
                base = 75
            elif 17 <= hour <= 20:
                base = 85
            elif 9 <= hour <= 21:
                base = 50
            else:
                base = 15
        elif loc_type == LocationType.TRANSIT:
            # Transit: rush hour peaks
            if hour in [7, 8, 9]:
                base = 90
            elif hour in [17, 18, 19]:
                base = 85
            elif 6 <= hour <= 22:
                base = 40
            else:
                base = 10
        elif loc_type == LocationType.RECREATION:
            # Recreation: afternoon/evening peaks
            if is_weekend:
                if 10 <= hour <= 18:
                    base = 70
                else:
                    base = 20
            else:
                if 16 <= hour <= 20:
                    base = 50
                else:
                    base = 20
        elif loc_type == LocationType.RESIDENTIAL:
            # Residential: evening presence
            if 18 <= hour <= 22:
                base = 60
            elif 7 <= hour <= 9:
                base = 40
            else:
                base = 30
        else:
            # Mixed/Unknown: moderate throughout
            base = 40 + (10 if 10 <= hour <= 20 else 0)

        # Apply weekend multiplier
        if is_weekend:
            base *= weekend_mult

        return min(100, max(0, base))

    def _add_noise(self, base: float, seed: int, minute: int) -> float:
        """
        Add deterministic noise to busyness value.

        Uses sine waves with location-specific phase to create
        realistic fluctuations while remaining reproducible.
        """
        # Primary wave: ~15 minute cycle
        phase1 = (seed % 100) / 100 * 2 * math.pi
        wave1 = math.sin(minute / 15 * 2 * math.pi + phase1) * 8

        # Secondary wave: ~7 minute cycle
        phase2 = ((seed >> 8) % 100) / 100 * 2 * math.pi
        wave2 = math.sin(minute / 7 * 2 * math.pi + phase2) * 4

        # Location-specific offset
        offset = (seed % 20) - 10

        result = base + wave1 + wave2 + offset
        return min(100, max(0, result))

    def _calculate_trend(self, current: float, previous: float) -> str:
        """Determine busyness trend."""
        delta = current - previous
        if delta > 5:
            return "increasing"
        elif delta < -5:
            return "decreasing"
        return "stable"

    async def get_busyness(
        self,
        lat: float,
        lon: float,
        timestamp: Optional[datetime] = None,
    ) -> BusynessData:
        """
        Get busyness estimate for a location.

        Args:
            lat: Latitude (NEVER from home zone - enforced by caller)
            lon: Longitude (NEVER from home zone - enforced by caller)
            timestamp: Time for the estimate (defaults to now)

        Returns:
            BusynessData with current and historical busyness levels
        """
        if timestamp is None:
            from datetime import timezone
            timestamp = datetime.now(timezone.utc)

        hour = timestamp.hour
        minute = timestamp.minute
        day_of_week = timestamp.weekday()

        cache_key = self._cache_key(lat, lon, hour)

        # Check cache (5-minute granularity within same hour)
        cache_minute_bucket = (minute // 5) * 5
        full_cache_key = f"{cache_key}:{cache_minute_bucket}"

        cached = await cache_service.get(full_cache_key)
        if cached:
            self._cache_hits += 1
            return BusynessData(
                busyness_pct=cached["busyness_pct"],
                usual_busyness_pct=cached["usual_busyness_pct"],
                busyness_delta=cached["busyness_delta"],
                trend=cached["trend"],
                location_type=LocationType(cached["location_type"]),
                confidence=cached["confidence"],
                is_mock=True,
            )

        self._cache_misses += 1

        # Generate mock busyness data
        seed = self._location_seed(lat, lon)
        loc_type = self._classify_location(lat, lon)

        # Calculate usual (historical average) busyness
        usual = self._base_pattern(hour, day_of_week, loc_type)

        # Calculate current busyness with noise
        current = self._add_noise(usual, seed, minute)

        # Calculate previous hour for trend
        prev_hour = (hour - 1) % 24
        prev_usual = self._base_pattern(prev_hour, day_of_week, loc_type)
        prev_current = self._add_noise(prev_usual, seed, 30)  # Mid-hour sample

        trend = self._calculate_trend(current, prev_current)
        delta = current - usual

        # Confidence based on location type knowledge
        confidence = 0.7 if loc_type != LocationType.UNKNOWN else 0.4

        result = BusynessData(
            busyness_pct=round(current, 1),
            usual_busyness_pct=round(usual, 1),
            busyness_delta=round(delta, 1),
            trend=trend,
            location_type=loc_type,
            confidence=confidence,
            is_mock=True,
        )

        # Cache for 5 minutes
        await cache_service.set(
            full_cache_key,
            {
                "busyness_pct": result.busyness_pct,
                "usual_busyness_pct": result.usual_busyness_pct,
                "busyness_delta": result.busyness_delta,
                "trend": result.trend,
                "location_type": result.location_type.value,
                "confidence": result.confidence,
            },
            ttl_seconds=300,  # 5 minutes
        )

        return result

    @property
    def stats(self) -> dict:
        """Get cache statistics."""
        total = self._cache_hits + self._cache_misses
        hit_rate = (self._cache_hits / total * 100) if total > 0 else 0
        return {
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "hit_rate_pct": round(hit_rate, 1),
            "is_mock_service": True,
        }


# Global busyness service instance
busyness_service = BusynessService()
