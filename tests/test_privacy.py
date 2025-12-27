"""Tests for privacy enforcement (Drop-at-Gateway)."""

import pytest

from app.core.privacy import (
    PrivacyFilterResult,
    check_home_zone,
    filter_ping_for_privacy,
)


class TestCheckHomeZone:
    """Tests for home zone detection."""

    def test_within_home_zone(self):
        """Ping within 50m of home should be detected."""
        home_lat, home_lon = 32.0853, 34.7818
        # Ping 30m away (within 50m radius)
        ping_lat = home_lat + 0.00027  # ~30m
        ping_lon = home_lon

        assert check_home_zone(ping_lat, ping_lon, home_lat, home_lon, 50.0) is True

    def test_outside_home_zone(self):
        """Ping outside 50m radius should not be detected."""
        home_lat, home_lon = 32.0853, 34.7818
        # Ping 100m away (outside 50m radius)
        ping_lat = home_lat + 0.0009  # ~100m
        ping_lon = home_lon

        assert check_home_zone(ping_lat, ping_lon, home_lat, home_lon, 50.0) is False

    def test_no_home_configured(self):
        """If home is not configured, should return False."""
        assert check_home_zone(32.0, 34.0, None, None, 50.0) is False
        assert check_home_zone(32.0, 34.0, 32.0, None, 50.0) is False
        assert check_home_zone(32.0, 34.0, None, 34.0, 50.0) is False

    def test_exactly_at_boundary(self):
        """Ping exactly at 50m should be included in home zone."""
        home_lat, home_lon = 32.0, 34.0
        # Ping at ~50m
        ping_lat = home_lat + 0.00045
        ping_lon = home_lon

        # Should be within 51m but not 49m (edge case)
        assert check_home_zone(ping_lat, ping_lon, home_lat, home_lon, 51.0) is True


class TestFilterPingForPrivacy:
    """Tests for the Drop-at-Gateway privacy filter."""

    def test_home_zone_ping_nullifies_coordinates(self):
        """Pings in home zone should have coordinates nullified."""
        result = filter_ping_for_privacy(
            ping_lat=32.0853,
            ping_lon=34.7818,
            ping_speed=5.0,
            ping_bearing=90.0,
            home_lat=32.0853,  # Same location = in home zone
            home_lon=34.7818,
            radius_m=50.0,
        )

        assert result.is_home_zone is True
        assert result.lat is None
        assert result.lon is None
        assert result.speed is None
        assert result.bearing is None

    def test_non_home_zone_ping_preserves_coordinates(self):
        """Pings outside home zone should preserve all data."""
        result = filter_ping_for_privacy(
            ping_lat=33.0,  # Far from home
            ping_lon=35.0,
            ping_speed=5.0,
            ping_bearing=90.0,
            home_lat=32.0853,
            home_lon=34.7818,
            radius_m=50.0,
        )

        assert result.is_home_zone is False
        assert result.lat == 33.0
        assert result.lon == 35.0
        assert result.speed == 5.0
        assert result.bearing == 90.0

    def test_no_home_configured_preserves_coordinates(self):
        """If no home zone configured, coordinates are preserved."""
        result = filter_ping_for_privacy(
            ping_lat=32.0853,
            ping_lon=34.7818,
            ping_speed=5.0,
            ping_bearing=90.0,
            home_lat=None,
            home_lon=None,
            radius_m=50.0,
        )

        assert result.is_home_zone is False
        assert result.lat == 32.0853
        assert result.lon == 34.7818

    def test_custom_radius(self):
        """Custom radius should be respected."""
        # Ping 40m from home
        home_lat, home_lon = 32.0, 34.0
        ping_lat = home_lat + 0.00036  # ~40m

        # With 50m radius - should be in home zone
        result_50m = filter_ping_for_privacy(
            ping_lat=ping_lat,
            ping_lon=home_lon,
            ping_speed=None,
            ping_bearing=None,
            home_lat=home_lat,
            home_lon=home_lon,
            radius_m=50.0,
        )
        assert result_50m.is_home_zone is True

        # With 30m radius - should NOT be in home zone
        result_30m = filter_ping_for_privacy(
            ping_lat=ping_lat,
            ping_lon=home_lon,
            ping_speed=None,
            ping_bearing=None,
            home_lat=home_lat,
            home_lon=home_lon,
            radius_m=30.0,
        )
        assert result_30m.is_home_zone is False


class TestPrivacyFilterResultDataclass:
    """Tests for PrivacyFilterResult dataclass."""

    def test_home_zone_result(self):
        """Home zone result should only have is_home_zone set."""
        result = PrivacyFilterResult(is_home_zone=True)
        assert result.is_home_zone is True
        assert result.lat is None
        assert result.lon is None
        assert result.speed is None
        assert result.bearing is None

    def test_non_home_zone_result(self):
        """Non-home zone result should have all fields."""
        result = PrivacyFilterResult(
            is_home_zone=False,
            lat=32.0,
            lon=34.0,
            speed=5.0,
            bearing=90.0,
        )
        assert result.is_home_zone is False
        assert result.lat == 32.0
        assert result.lon == 34.0
        assert result.speed == 5.0
        assert result.bearing == 90.0
