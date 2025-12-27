"""Tests for sliding window statistical features."""

from datetime import datetime, timedelta

import pytest

from app.core.sliding_window import (
    LONG_WINDOW_MINUTES,
    SHORT_WINDOW_SECONDS,
    STOP_SPEED_THRESHOLD,
    DualWindowFeatures,
    PingData,
    WindowFeatures,
    compute_dual_window_features,
    compute_window_features,
)


def make_ping(
    seconds_ago: int = 0,
    speed: float = 5.0,
    bearing: float = 90.0,
) -> PingData:
    """Helper to create test ping data."""
    return PingData(
        timestamp=datetime.utcnow() - timedelta(seconds=seconds_ago),
        speed=speed,
        bearing=bearing,
    )


def make_ping_minutes(
    minutes_ago: int = 0,
    speed: float = 5.0,
    bearing: float = 90.0,
) -> PingData:
    """Helper to create test ping data with minutes offset."""
    return PingData(
        timestamp=datetime.utcnow() - timedelta(minutes=minutes_ago),
        speed=speed,
        bearing=bearing,
    )


class TestDualWindowFeatures:
    """Tests for dual sliding window feature computation."""

    def test_empty_window(self):
        """Single ping with no history should handle gracefully."""
        current = make_ping(seconds_ago=0, speed=5.0, bearing=90.0)
        result = compute_dual_window_features(current, [])

        # Both windows should have just the current ping
        assert result.ping_count_30s == 1
        assert result.ping_count_5m == 1
        assert result.velocity_jitter_30s is None  # Need 2+ for stddev
        assert result.velocity_jitter_5m is None
        assert result.bearing_volatility_30s is None  # Need 2+ for volatility
        assert result.bearing_volatility_5m is None
        assert result.jitter_ratio is None
        assert result.volatility_ratio is None
        assert result.is_stop_event is False
        assert result.stop_duration_sec is None

    def test_short_window_only(self):
        """Pings only within 30s window."""
        current = make_ping(seconds_ago=0, speed=10.0, bearing=90.0)
        recent = [
            make_ping(seconds_ago=10, speed=8.0, bearing=80.0),
            make_ping(seconds_ago=20, speed=12.0, bearing=100.0),
        ]

        result = compute_dual_window_features(current, recent)

        assert result.ping_count_30s == 3
        assert result.ping_count_5m == 3  # Same pings in both windows
        assert result.velocity_jitter_30s is not None
        assert result.velocity_jitter_5m is not None
        # With same data, both should be equal
        assert result.velocity_jitter_30s == result.velocity_jitter_5m

    def test_dual_window_differentiation(self):
        """Long window should capture more data than short window."""
        current = make_ping(seconds_ago=0, speed=10.0, bearing=90.0)
        recent = [
            # Within 30s window
            make_ping(seconds_ago=10, speed=8.0, bearing=80.0),
            make_ping(seconds_ago=20, speed=12.0, bearing=100.0),
            # Outside 30s but within 5min window
            make_ping(seconds_ago=60, speed=5.0, bearing=45.0),
            make_ping(seconds_ago=120, speed=15.0, bearing=180.0),
            make_ping(seconds_ago=180, speed=3.0, bearing=270.0),
        ]

        result = compute_dual_window_features(current, recent)

        # Short window: current + 2 pings within 30s
        assert result.ping_count_30s == 3
        # Long window: current + all 5 recent pings
        assert result.ping_count_5m == 6
        # Both should have valid jitter (enough data)
        assert result.velocity_jitter_30s is not None
        assert result.velocity_jitter_5m is not None

    def test_jitter_ratio_spike_detection(self):
        """High jitter_ratio indicates recent behavioral spike."""
        current = make_ping(seconds_ago=0, speed=10.0, bearing=90.0)
        recent = [
            # Erratic speeds in short window
            make_ping(seconds_ago=5, speed=2.0, bearing=90.0),
            make_ping(seconds_ago=15, speed=15.0, bearing=90.0),
            make_ping(seconds_ago=25, speed=1.0, bearing=90.0),
            # Stable speeds outside short window
            make_ping(seconds_ago=60, speed=5.0, bearing=90.0),
            make_ping(seconds_ago=90, speed=5.0, bearing=90.0),
            make_ping(seconds_ago=120, speed=5.0, bearing=90.0),
            make_ping(seconds_ago=150, speed=5.0, bearing=90.0),
        ]

        result = compute_dual_window_features(current, recent)

        # Short window jitter should be much higher than long window
        assert result.jitter_ratio is not None
        assert result.jitter_ratio > 1.0  # Spike detected

    def test_volatility_ratio_erratic_detection(self):
        """High volatility_ratio indicates recent erratic behavior."""
        current = make_ping(seconds_ago=0, speed=5.0, bearing=180.0)
        recent = [
            # Large bearing changes in short window
            make_ping(seconds_ago=10, speed=5.0, bearing=0.0),
            make_ping(seconds_ago=20, speed=5.0, bearing=270.0),
            # Stable bearing outside short window
            make_ping(seconds_ago=60, speed=5.0, bearing=90.0),
            make_ping(seconds_ago=90, speed=5.0, bearing=92.0),
            make_ping(seconds_ago=120, speed=5.0, bearing=88.0),
        ]

        result = compute_dual_window_features(current, recent)

        assert result.volatility_ratio is not None
        assert result.volatility_ratio > 1.0  # Erratic behavior detected

    def test_steady_behavior_ratios_near_one(self):
        """Steady behavior should have ratios near 1.0."""
        current = make_ping(seconds_ago=0, speed=5.0, bearing=90.0)
        recent = [
            make_ping(seconds_ago=10, speed=5.2, bearing=92.0),
            make_ping(seconds_ago=20, speed=4.8, bearing=88.0),
            make_ping(seconds_ago=60, speed=5.1, bearing=91.0),
            make_ping(seconds_ago=90, speed=4.9, bearing=89.0),
            make_ping(seconds_ago=120, speed=5.0, bearing=90.0),
        ]

        result = compute_dual_window_features(current, recent)

        # Both ratios should be close to 1.0 for steady behavior
        if result.jitter_ratio is not None:
            assert 0.5 < result.jitter_ratio < 2.0
        if result.volatility_ratio is not None:
            assert 0.5 < result.volatility_ratio < 2.0


class TestComputeWindowFeatures:
    """Tests for legacy sliding window feature computation."""

    def test_empty_window(self):
        """Single ping with no history should handle gracefully."""
        current = make_ping_minutes(minutes_ago=0, speed=5.0, bearing=90.0)
        result = compute_window_features(current, [])

        assert result.velocity_jitter is None  # Need 2+ for stddev
        assert result.bearing_volatility is None  # Need 2+ for volatility
        assert result.is_stop_event is False
        assert result.stop_duration_sec is None

    def test_velocity_jitter_calculation(self):
        """Velocity jitter should be standard deviation of speeds."""
        current = make_ping_minutes(minutes_ago=0, speed=10.0, bearing=90.0)
        recent = [
            make_ping_minutes(minutes_ago=1, speed=8.0, bearing=90.0),
            make_ping_minutes(minutes_ago=2, speed=12.0, bearing=90.0),
            make_ping_minutes(minutes_ago=3, speed=6.0, bearing=90.0),
        ]

        result = compute_window_features(current, recent)

        assert result.velocity_jitter is not None
        assert result.velocity_jitter > 0

    def test_constant_speed_zero_jitter(self):
        """Constant speed should have zero jitter."""
        current = make_ping_minutes(minutes_ago=0, speed=5.0, bearing=90.0)
        recent = [
            make_ping_minutes(minutes_ago=1, speed=5.0, bearing=90.0),
            make_ping_minutes(minutes_ago=2, speed=5.0, bearing=90.0),
        ]

        result = compute_window_features(current, recent)

        assert result.velocity_jitter == pytest.approx(0, abs=0.001)

    def test_bearing_volatility_calculation(self):
        """Bearing volatility should reflect direction changes."""
        current = make_ping_minutes(minutes_ago=0, speed=5.0, bearing=180.0)
        recent = [
            make_ping_minutes(minutes_ago=1, speed=5.0, bearing=90.0),
            make_ping_minutes(minutes_ago=2, speed=5.0, bearing=0.0),
        ]

        result = compute_window_features(current, recent)

        assert result.bearing_volatility is not None
        # Bearings in order: [90, 0, 180] -> diffs: [90, 180] -> mean: 135
        assert result.bearing_volatility == 135.0

    def test_stop_event_detection(self):
        """Speed below threshold should trigger stop event."""
        current = make_ping_minutes(minutes_ago=0, speed=0.2, bearing=90.0)  # Below 0.5 m/s
        recent = []

        result = compute_window_features(current, recent)

        assert result.is_stop_event is True

    def test_moving_not_stop_event(self):
        """Speed above threshold should not be stop event."""
        current = make_ping_minutes(minutes_ago=0, speed=5.0, bearing=90.0)
        recent = []

        result = compute_window_features(current, recent)

        assert result.is_stop_event is False

    def test_stop_duration_calculation(self):
        """Stop duration should count consecutive stop pings."""
        current = make_ping_minutes(minutes_ago=0, speed=0.1, bearing=90.0)
        recent = [
            make_ping_minutes(minutes_ago=1, speed=0.2, bearing=90.0),  # Also stopped
            make_ping_minutes(minutes_ago=2, speed=0.1, bearing=90.0),  # Also stopped
            make_ping_minutes(minutes_ago=3, speed=5.0, bearing=90.0),  # Was moving
        ]

        result = compute_window_features(current, recent)

        assert result.is_stop_event is True
        assert result.stop_duration_sec is not None
        # Should be approximately 2 minutes (120 seconds)
        assert result.stop_duration_sec == pytest.approx(120, rel=0.1)

    def test_window_respects_time_boundary(self):
        """Only pings within window should be included."""
        current = make_ping_minutes(minutes_ago=0, speed=10.0, bearing=90.0)
        recent = [
            make_ping_minutes(minutes_ago=1, speed=8.0, bearing=90.0),  # In 5-min window
            make_ping_minutes(minutes_ago=4, speed=6.0, bearing=90.0),  # In 5-min window
            make_ping_minutes(minutes_ago=10, speed=100.0, bearing=90.0),  # Outside window
        ]

        result = compute_window_features(current, recent, window_minutes=5)

        # The outlier (100 m/s) should not affect the result much
        # if it's properly excluded
        assert result.velocity_jitter is not None
        assert result.velocity_jitter < 10  # Would be huge if 100 was included

    def test_none_speed_handling(self):
        """None speeds should be gracefully ignored."""
        current = make_ping_minutes(minutes_ago=0, speed=5.0, bearing=90.0)
        recent = [
            PingData(
                timestamp=datetime.utcnow() - timedelta(minutes=1),
                speed=None,
                bearing=90.0,
            ),
            make_ping_minutes(minutes_ago=2, speed=5.0, bearing=90.0),
        ]

        # Should not raise, should compute with available data
        result = compute_window_features(current, recent)
        assert result is not None

    def test_none_bearing_handling(self):
        """None bearings should be gracefully ignored."""
        current = make_ping_minutes(minutes_ago=0, speed=5.0, bearing=90.0)
        recent = [
            PingData(
                timestamp=datetime.utcnow() - timedelta(minutes=1),
                speed=5.0,
                bearing=None,
            ),
        ]

        result = compute_window_features(current, recent)
        assert result is not None


class TestStopSpeedThreshold:
    """Tests for stop speed threshold constant."""

    def test_threshold_value(self):
        """Threshold should be 0.5 m/s as specified."""
        assert STOP_SPEED_THRESHOLD == 0.5

    def test_just_below_threshold(self):
        """Speed just below threshold should be stop."""
        current = make_ping_minutes(minutes_ago=0, speed=0.49, bearing=90.0)
        result = compute_window_features(current, [])
        assert result.is_stop_event is True

    def test_just_above_threshold(self):
        """Speed just above threshold should not be stop."""
        current = make_ping_minutes(minutes_ago=0, speed=0.51, bearing=90.0)
        result = compute_window_features(current, [])
        assert result.is_stop_event is False


class TestWindowConstants:
    """Tests for window size constants."""

    def test_short_window_is_30_seconds(self):
        """Short window should be 30 seconds."""
        assert SHORT_WINDOW_SECONDS == 30

    def test_long_window_is_5_minutes(self):
        """Long window should be 5 minutes."""
        assert LONG_WINDOW_MINUTES == 5


class TestFreezeAndStalkingDetection:
    """Tests for canine reactivity patterns."""

    def test_freeze_detection(self):
        """Sudden stop (freeze) should be captured in short window."""
        # Dog was walking normally, then suddenly stops
        current = make_ping(seconds_ago=0, speed=0.1, bearing=45.0)  # Frozen
        recent = [
            make_ping(seconds_ago=5, speed=0.2, bearing=45.0),   # Just stopped
            make_ping(seconds_ago=10, speed=1.5, bearing=45.0),  # Was walking
            make_ping(seconds_ago=15, speed=1.4, bearing=45.0),  # Was walking
            make_ping(seconds_ago=20, speed=1.6, bearing=44.0),  # Was walking
        ]

        result = compute_dual_window_features(current, recent)

        assert result.is_stop_event is True
        assert result.stop_duration_sec is not None
        assert result.stop_duration_sec >= 4  # At least a few seconds of freeze

    def test_stalking_pattern(self):
        """Stalking: slow deliberate movement with fixed bearing."""
        # Dog fixating: very slow, consistent direction
        current = make_ping(seconds_ago=0, speed=0.6, bearing=90.0)
        recent = [
            make_ping(seconds_ago=5, speed=0.55, bearing=90.0),
            make_ping(seconds_ago=10, speed=0.65, bearing=91.0),
            make_ping(seconds_ago=15, speed=0.60, bearing=89.0),
            make_ping(seconds_ago=20, speed=0.58, bearing=90.0),
        ]

        result = compute_dual_window_features(current, recent)

        # Very low jitter (consistent slow speed)
        assert result.velocity_jitter_30s is not None
        assert result.velocity_jitter_30s < 0.1

        # Very low bearing volatility (fixed direction)
        assert result.bearing_volatility_30s is not None
        assert result.bearing_volatility_30s < 5.0

    def test_normal_walk_vs_reactive_spike(self):
        """Compare normal walk to reactive spike patterns."""
        # Normal relaxed walk
        normal_current = make_ping(seconds_ago=0, speed=1.2, bearing=95.0)
        normal_recent = [
            make_ping(seconds_ago=10, speed=1.3, bearing=90.0),
            make_ping(seconds_ago=20, speed=1.1, bearing=85.0),
            make_ping(seconds_ago=60, speed=1.2, bearing=80.0),
            make_ping(seconds_ago=90, speed=1.4, bearing=88.0),
        ]
        normal_result = compute_dual_window_features(normal_current, normal_recent)

        # Reactive spike: erratic in short window
        reactive_current = make_ping(seconds_ago=0, speed=3.0, bearing=180.0)
        reactive_recent = [
            make_ping(seconds_ago=5, speed=0.5, bearing=0.0),    # Lunging
            make_ping(seconds_ago=10, speed=2.5, bearing=270.0),  # Pulling
            make_ping(seconds_ago=15, speed=0.2, bearing=90.0),   # Held back
            make_ping(seconds_ago=60, speed=1.2, bearing=80.0),   # Was calm
            make_ping(seconds_ago=90, speed=1.1, bearing=82.0),   # Was calm
        ]
        reactive_result = compute_dual_window_features(reactive_current, reactive_recent)

        # Reactive should have higher jitter ratio
        if normal_result.jitter_ratio and reactive_result.jitter_ratio:
            assert reactive_result.jitter_ratio > normal_result.jitter_ratio

        # Reactive should have higher volatility ratio
        if normal_result.volatility_ratio and reactive_result.volatility_ratio:
            assert reactive_result.volatility_ratio > normal_result.volatility_ratio
