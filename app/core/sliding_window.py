"""
Dual sliding window aggregation for statistical features.

Implements a two-window approach optimized for canine reactivity detection:
- Short Window (30s): Captures immediate behavioral spikes (freeze, stalking)
- Long Window (5m): Provides environmental and baseline context

This granularity is critical for XGBoost model performance.
"""

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Sequence

from app.core.geo import calculate_bearing_volatility


@dataclass
class DualWindowFeatures:
    """
    Statistical features computed over dual sliding windows.

    Short window (30s) captures:
    - Immediate behavioral spikes
    - Freeze events (sudden stop)
    - Stalking patterns (slow, deliberate movement)

    Long window (5m) captures:
    - Baseline behavioral context
    - Environmental patterns
    - Overall walk characteristics
    """

    # Short window features (30 seconds) - Immediate behavior
    velocity_jitter_30s: Optional[float]  # Speed variance in last 30s
    bearing_volatility_30s: Optional[float]  # Direction changes in last 30s
    ping_count_30s: int  # Data density in short window

    # Long window features (5 minutes) - Baseline context
    velocity_jitter_5m: Optional[float]  # Speed variance over 5 min
    bearing_volatility_5m: Optional[float]  # Direction changes over 5 min
    ping_count_5m: int  # Data density in long window

    # Derived features - Behavioral spike detection
    jitter_ratio: Optional[float]  # 30s/5m ratio (>1 = recent spike)
    volatility_ratio: Optional[float]  # 30s/5m ratio (>1 = recent erratic)

    # Stop event detection (uses current ping)
    is_stop_event: bool  # Speed below threshold
    stop_duration_sec: Optional[int]  # Consecutive stop time


# Legacy dataclass for backward compatibility
@dataclass
class WindowFeatures:
    """Statistical features computed over a sliding window (legacy)."""

    velocity_jitter: Optional[float]
    bearing_volatility: Optional[float]
    is_stop_event: bool
    stop_duration_sec: Optional[int]


@dataclass
class PingData:
    """Minimal ping data needed for window calculations."""

    timestamp: datetime
    speed: Optional[float]
    bearing: Optional[float]


# Speed threshold for stop detection (m/s)
# 0.5 m/s = 1.8 km/h - typical freeze/stop threshold
STOP_SPEED_THRESHOLD = 0.5

# Window sizes
SHORT_WINDOW_SECONDS = 30  # Immediate behavioral spikes
LONG_WINDOW_MINUTES = 5  # Baseline context


def _filter_pings_to_window(
    current_ping: PingData,
    recent_pings: Sequence[PingData],
    window_seconds: int,
) -> list[PingData]:
    """Filter pings to those within the specified time window."""
    window_start = current_ping.timestamp - timedelta(seconds=window_seconds)
    return [
        p for p in recent_pings
        if p.timestamp >= window_start and p.timestamp <= current_ping.timestamp
    ]


def _compute_window_stats(
    pings: list[PingData],
) -> tuple[Optional[float], Optional[float]]:
    """
    Compute velocity jitter and bearing volatility for a set of pings.

    Returns:
        Tuple of (velocity_jitter, bearing_volatility)
    """
    speeds = [p.speed for p in pings if p.speed is not None]
    bearings = [p.bearing for p in pings if p.bearing is not None]

    velocity_jitter: Optional[float] = None
    if len(speeds) >= 2:
        velocity_jitter = statistics.stdev(speeds)

    bearing_volatility = calculate_bearing_volatility(bearings)

    return velocity_jitter, bearing_volatility


def compute_dual_window_features(
    current_ping: PingData,
    recent_pings: Sequence[PingData],
    short_window_seconds: int = SHORT_WINDOW_SECONDS,
    long_window_minutes: int = LONG_WINDOW_MINUTES,
) -> DualWindowFeatures:
    """
    Compute statistical features over dual sliding time windows.

    PRIVACY NOTE: This function should NEVER receive home zone pings.
    The caller must filter out is_home_zone=True pings before calling.

    Args:
        current_ping: The current ping being processed
        recent_pings: Recent pings for the same user (already privacy-filtered)
        short_window_seconds: Short window size in seconds (default 30)
        long_window_minutes: Long window size in minutes (default 5)

    Returns:
        DualWindowFeatures with statistics for both windows
    """
    # Get pings for each window
    short_pings = _filter_pings_to_window(
        current_ping, recent_pings, short_window_seconds
    )
    long_pings = _filter_pings_to_window(
        current_ping, recent_pings, long_window_minutes * 60
    )

    # Include current ping in calculations
    all_short = short_pings + [current_ping]
    all_long = long_pings + [current_ping]

    # Compute stats for each window
    jitter_30s, volatility_30s = _compute_window_stats(all_short)
    jitter_5m, volatility_5m = _compute_window_stats(all_long)

    # Compute ratios for spike detection
    # Ratio > 1.0 indicates recent spike compared to baseline
    jitter_ratio: Optional[float] = None
    if jitter_30s is not None and jitter_5m is not None and jitter_5m > 0:
        jitter_ratio = jitter_30s / jitter_5m

    volatility_ratio: Optional[float] = None
    if volatility_30s is not None and volatility_5m is not None and volatility_5m > 0:
        volatility_ratio = volatility_30s / volatility_5m

    # Stop detection
    current_speed = current_ping.speed or 0.0
    is_stop = current_speed < STOP_SPEED_THRESHOLD

    # Calculate stop duration using long window
    stop_duration: Optional[int] = None
    if is_stop:
        stop_duration = _calculate_stop_duration(current_ping, long_pings)

    return DualWindowFeatures(
        # Short window (30s)
        velocity_jitter_30s=jitter_30s,
        bearing_volatility_30s=volatility_30s,
        ping_count_30s=len(all_short),
        # Long window (5m)
        velocity_jitter_5m=jitter_5m,
        bearing_volatility_5m=volatility_5m,
        ping_count_5m=len(all_long),
        # Derived ratios
        jitter_ratio=jitter_ratio,
        volatility_ratio=volatility_ratio,
        # Stop events
        is_stop_event=is_stop,
        stop_duration_sec=stop_duration,
    )


def compute_window_features(
    current_ping: PingData,
    recent_pings: Sequence[PingData],
    window_minutes: int = LONG_WINDOW_MINUTES,
) -> WindowFeatures:
    """
    Compute statistical features over a sliding time window (legacy API).

    DEPRECATED: Use compute_dual_window_features() for better granularity.

    This function is maintained for backward compatibility.
    It returns only the 5-minute window features.

    Args:
        current_ping: The current ping being processed
        recent_pings: Recent pings for the same user (already privacy-filtered)
        window_minutes: Window size in minutes (default 5)

    Returns:
        WindowFeatures with computed statistics
    """
    dual = compute_dual_window_features(
        current_ping=current_ping,
        recent_pings=recent_pings,
        long_window_minutes=window_minutes,
    )

    return WindowFeatures(
        velocity_jitter=dual.velocity_jitter_5m,
        bearing_volatility=dual.bearing_volatility_5m,
        is_stop_event=dual.is_stop_event,
        stop_duration_sec=dual.stop_duration_sec,
    )


def _calculate_stop_duration(
    current_ping: PingData,
    recent_pings: Sequence[PingData],
) -> int:
    """
    Calculate duration of consecutive stop events ending at current ping.

    Returns duration in seconds.
    """
    if not recent_pings:
        return 0

    # Sort by timestamp descending (most recent first)
    sorted_pings = sorted(recent_pings, key=lambda p: p.timestamp, reverse=True)

    stop_start = current_ping.timestamp
    for ping in sorted_pings:
        ping_speed = ping.speed or 0.0
        if ping_speed < STOP_SPEED_THRESHOLD:
            stop_start = ping.timestamp
        else:
            break

    duration = current_ping.timestamp - stop_start
    return int(duration.total_seconds())
