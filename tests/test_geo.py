"""Tests for geospatial utilities."""

import pytest

from app.core.geo import (
    bearing_difference,
    calculate_bearing_volatility,
    geohash_key,
    haversine_distance,
    is_within_radius,
)


class TestHaversineDistance:
    """Tests for Haversine distance calculation."""

    def test_same_point_returns_zero(self):
        """Distance from a point to itself should be zero."""
        distance = haversine_distance(32.0853, 34.7818, 32.0853, 34.7818)
        assert distance == pytest.approx(0, abs=0.01)

    def test_known_distance_tel_aviv_to_jerusalem(self):
        """Test known distance between Tel Aviv and Jerusalem (~54km)."""
        # Tel Aviv
        tel_aviv_lat, tel_aviv_lon = 32.0853, 34.7818
        # Jerusalem
        jerusalem_lat, jerusalem_lon = 31.7683, 35.2137

        distance = haversine_distance(
            tel_aviv_lat, tel_aviv_lon,
            jerusalem_lat, jerusalem_lon
        )

        # Known distance is approximately 54km
        assert distance == pytest.approx(54000, rel=0.05)  # 5% tolerance

    def test_short_distance(self):
        """Test short distances (~50m) for home zone filtering."""
        # Two points approximately 50m apart
        lat1, lon1 = 32.0853, 34.7818
        # Approximately 50m north
        lat2 = lat1 + 0.00045  # ~50m in latitude
        lon2 = lon1

        distance = haversine_distance(lat1, lon1, lat2, lon2)
        assert distance == pytest.approx(50, rel=0.1)  # 10% tolerance

    def test_symmetric(self):
        """Distance A->B should equal B->A."""
        dist_ab = haversine_distance(32.0, 34.0, 33.0, 35.0)
        dist_ba = haversine_distance(33.0, 35.0, 32.0, 34.0)
        assert dist_ab == pytest.approx(dist_ba, rel=0.001)


class TestIsWithinRadius:
    """Tests for radius check function."""

    def test_point_within_radius(self):
        """Point should be within specified radius."""
        assert is_within_radius(32.0, 34.0, 32.0001, 34.0001, 100) is True

    def test_point_outside_radius(self):
        """Point should be outside specified radius."""
        assert is_within_radius(32.0, 34.0, 33.0, 35.0, 100) is False

    def test_edge_case_exactly_at_radius(self):
        """Point at exactly the radius distance."""
        # Create a point ~50m away
        lat1, lon1 = 32.0, 34.0
        lat2 = lat1 + 0.00045  # ~50m
        lon2 = lon1

        # Should be within 60m
        assert is_within_radius(lat1, lon1, lat2, lon2, 60) is True
        # Should not be within 40m
        assert is_within_radius(lat1, lon1, lat2, lon2, 40) is False


class TestGeohashKey:
    """Tests for geohash key generation."""

    def test_same_area_produces_same_key(self):
        """Nearby coordinates should produce the same cache key."""
        # Coordinates that round to same values at precision=2
        key1 = geohash_key(32.081, 34.781, precision=2)
        key2 = geohash_key(32.083, 34.784, precision=2)
        assert key1 == key2  # Both round to 32.08:34.78

    def test_different_areas_produce_different_keys(self):
        """Distant coordinates should produce different cache keys."""
        key1 = geohash_key(32.08, 34.78, precision=2)
        key2 = geohash_key(32.10, 34.80, precision=2)
        assert key1 != key2

    def test_key_format(self):
        """Key should be in expected format."""
        key = geohash_key(32.0853, 34.7818, precision=2)
        assert ":" in key
        assert key == "32.09:34.78"


class TestBearingDifference:
    """Tests for bearing difference calculation."""

    def test_same_bearing(self):
        """Same bearing should have zero difference."""
        assert bearing_difference(45.0, 45.0) == 0

    def test_opposite_bearings(self):
        """Opposite bearings should have 180 degree difference."""
        assert bearing_difference(0, 180) == 180
        assert bearing_difference(90, 270) == 180

    def test_wrap_around(self):
        """Difference should handle 360 degree wrap-around."""
        assert bearing_difference(350, 10) == 20
        assert bearing_difference(10, 350) == 20

    def test_always_returns_smallest_angle(self):
        """Should always return the smallest angle (0-180)."""
        assert bearing_difference(0, 270) == 90
        assert bearing_difference(0, 359) == 1


class TestBearingVolatility:
    """Tests for bearing volatility calculation."""

    def test_constant_bearing(self):
        """Constant bearing should have zero volatility."""
        bearings = [45.0, 45.0, 45.0, 45.0]
        volatility = calculate_bearing_volatility(bearings)
        assert volatility == 0

    def test_varying_bearing(self):
        """Varying bearings should produce non-zero volatility."""
        bearings = [0.0, 90.0, 180.0, 270.0]
        volatility = calculate_bearing_volatility(bearings)
        assert volatility == 90.0

    def test_insufficient_data_returns_none(self):
        """Less than 2 bearings should return None."""
        assert calculate_bearing_volatility([45.0]) is None
        assert calculate_bearing_volatility([]) is None

    def test_wrap_around_volatility(self):
        """Volatility should handle wrap-around correctly."""
        # 350 -> 10 should be 20 degrees, not 340
        bearings = [350.0, 10.0]
        volatility = calculate_bearing_volatility(bearings)
        assert volatility == 20.0
