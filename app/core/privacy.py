"""
Privacy enforcement module - DROP-AT-GATEWAY implementation.

HARD CONSTRAINT: This module enforces the privacy policy that coordinates
within 50m of a user's home zone are NEVER stored or logged.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from app.core.geo import haversine_distance

logger = logging.getLogger(__name__)


@dataclass
class PrivacyFilterResult:
    """Result of privacy filtering operation."""

    is_home_zone: bool
    # These are only set if is_home_zone is False
    lat: Optional[float] = None
    lon: Optional[float] = None
    speed: Optional[float] = None
    bearing: Optional[float] = None


def check_home_zone(
    ping_lat: float,
    ping_lon: float,
    home_lat: Optional[float],
    home_lon: Optional[float],
    radius_m: float = 50.0,
) -> bool:
    """
    Check if coordinates fall within the home zone.

    Args:
        ping_lat: Incoming ping latitude
        ping_lon: Incoming ping longitude
        home_lat: User's home latitude (None if not configured)
        home_lon: User's home longitude (None if not configured)
        radius_m: Home zone radius in meters (default 50m)

    Returns:
        True if within home zone, False otherwise
    """
    if home_lat is None or home_lon is None:
        return False

    distance = haversine_distance(ping_lat, ping_lon, home_lat, home_lon)
    return distance <= radius_m


def filter_ping_for_privacy(
    ping_lat: float,
    ping_lon: float,
    ping_speed: Optional[float],
    ping_bearing: Optional[float],
    home_lat: Optional[float],
    home_lon: Optional[float],
    radius_m: float = 50.0,
) -> PrivacyFilterResult:
    """
    Apply DROP-AT-GATEWAY privacy filter to incoming ping.

    If the ping is within the home zone radius, coordinates are nullified.
    This function runs BEFORE any persistence or logging of coordinates.

    Args:
        ping_lat: Incoming ping latitude
        ping_lon: Incoming ping longitude
        ping_speed: Incoming ping speed (m/s)
        ping_bearing: Incoming ping bearing (degrees)
        home_lat: User's configured home latitude
        home_lon: User's configured home longitude
        radius_m: Home zone radius in meters

    Returns:
        PrivacyFilterResult with nullified coords if in home zone
    """
    is_home = check_home_zone(ping_lat, ping_lon, home_lat, home_lon, radius_m)

    if is_home:
        # CRITICAL: Log only the fact that filtering occurred, NEVER coordinates
        logger.info("HOME_ZONE_FILTERED: ping dropped at gateway")
        return PrivacyFilterResult(is_home_zone=True)

    return PrivacyFilterResult(
        is_home_zone=False,
        lat=ping_lat,
        lon=ping_lon,
        speed=ping_speed,
        bearing=ping_bearing,
    )
