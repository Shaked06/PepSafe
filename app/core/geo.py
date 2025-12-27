"""Geospatial utilities including Haversine distance calculation."""

import math
from typing import Optional


# Earth's radius in meters
EARTH_RADIUS_M = 6_371_000


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great-circle distance between two points on Earth.

    Uses the Haversine formula for accurate distance calculation.

    Args:
        lat1: Latitude of first point in degrees
        lon1: Longitude of first point in degrees
        lat2: Latitude of second point in degrees
        lon2: Longitude of second point in degrees

    Returns:
        Distance in meters between the two points
    """
    # Convert to radians
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    # Haversine formula
    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return EARTH_RADIUS_M * c


def is_within_radius(
    lat1: float, lon1: float, lat2: float, lon2: float, radius_m: float
) -> bool:
    """
    Check if two points are within a given radius of each other.

    Args:
        lat1: Latitude of first point
        lon1: Longitude of first point
        lat2: Latitude of second point
        lon2: Longitude of second point
        radius_m: Maximum distance in meters

    Returns:
        True if distance <= radius_m
    """
    return haversine_distance(lat1, lon1, lat2, lon2) <= radius_m


def geohash_key(lat: float, lon: float, precision: int = 2) -> str:
    """
    Generate a simple geohash-like key for cache bucketing.

    Uses decimal truncation for ~1km precision at precision=2.
    This reduces unique weather API calls by grouping nearby coordinates.

    Args:
        lat: Latitude
        lon: Longitude
        precision: Decimal places (2 = ~1km, 3 = ~100m)

    Returns:
        String key like "32.07:34.78"
    """
    lat_truncated = round(lat, precision)
    lon_truncated = round(lon, precision)
    return f"{lat_truncated}:{lon_truncated}"


def bearing_difference(bearing1: float, bearing2: float) -> float:
    """
    Calculate the smallest angle between two bearings.

    Handles the wrap-around at 360 degrees correctly.

    Args:
        bearing1: First bearing in degrees (0-360)
        bearing2: Second bearing in degrees (0-360)

    Returns:
        Smallest angle between bearings (0-180)
    """
    diff = abs(bearing1 - bearing2) % 360
    return min(diff, 360 - diff)


def calculate_bearing_volatility(bearings: list[float]) -> Optional[float]:
    """
    Calculate bearing volatility as the mean of consecutive bearing differences.

    Higher values indicate more erratic direction changes.

    Args:
        bearings: List of bearing values in degrees

    Returns:
        Mean bearing difference, or None if insufficient data
    """
    if len(bearings) < 2:
        return None

    differences = [
        bearing_difference(bearings[i], bearings[i + 1])
        for i in range(len(bearings) - 1)
    ]
    return sum(differences) / len(differences)
