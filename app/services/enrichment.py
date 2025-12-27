"""Enrichment orchestration service."""

import logging
from datetime import datetime
from typing import Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import get_settings
from app.core.geo import haversine_distance
from app.core.privacy import PrivacyFilterResult, filter_ping_for_privacy
from app.core.sliding_window import PingData, compute_dual_window_features
from app.db.models import ChokePoint, EnrichedPing, PingChokeProximity, RawPing, User
from app.schemas.ping import PingRequest, PingResponse
from app.services.busyness import busyness_service
from app.services.weather import weather_service

logger = logging.getLogger(__name__)
settings = get_settings()


async def process_ping(
    request: PingRequest,
    session: AsyncSession,
) -> PingResponse:
    """
    Process an incoming GPS ping through the full enrichment pipeline.

    Pipeline order:
    1. Lookup user (create if not exists)
    2. PRIVACY FILTER (Drop-at-Gateway) - runs FIRST before any processing
    3. Persist raw ping (with nullified coords if home zone)
    4. If NOT home zone:
       a. Weather enrichment
       b. Choke point proximity
       c. Sliding window features
       d. Persist enriched ping

    Args:
        request: Validated ping request
        session: Database session

    Returns:
        PingResponse with status and ping_id
    """
    # Step 1: Get or create user
    user = await _get_or_create_user(request.user, session)

    # Step 2: PRIVACY FILTER - MUST run before ANY logging or processing
    privacy_result = filter_ping_for_privacy(
        ping_lat=request.lat,
        ping_lon=request.lon,
        ping_speed=request.speed,
        ping_bearing=request.bearing,
        home_lat=user.home_lat,
        home_lon=user.home_lon,
        radius_m=settings.home_zone_radius_meters,
    )

    # Step 3: Create raw ping with privacy-filtered data
    raw_ping = RawPing(
        user_id=user.id,
        timestamp=request.timestamp,
        lat=privacy_result.lat,  # NULL if home zone
        lon=privacy_result.lon,  # NULL if home zone
        speed=privacy_result.speed,  # NULL if home zone
        bearing=privacy_result.bearing,  # NULL if home zone
        accuracy=request.accuracy if not privacy_result.is_home_zone else None,
        is_home_zone=privacy_result.is_home_zone,
    )

    session.add(raw_ping)
    await session.commit()
    await session.refresh(raw_ping)

    # If home zone, return early - NO enrichment for privacy
    if privacy_result.is_home_zone:
        # Safe log: only user and timestamp, NEVER coordinates
        logger.info(f"Ping filtered: user={user.id}, home_zone=True")
        return PingResponse(
            status="filtered",
            ping_id=raw_ping.id,
            enrichment_pending=False,
        )

    # Step 4: Enrichment (only for non-home-zone pings)
    await _enrich_ping(raw_ping, privacy_result, session)

    # Safe log: only user and ping ID
    logger.info(f"Ping accepted: user={user.id}, ping_id={raw_ping.id}")

    return PingResponse(
        status="accepted",
        ping_id=raw_ping.id,
        enrichment_pending=False,
    )


async def _get_or_create_user(user_id: str, session: AsyncSession) -> User:
    """Get existing user or create new one."""
    result = await session.exec(select(User).where(User.id == user_id))
    user = result.one_or_none()

    if not user:
        user = User(id=user_id, name=user_id)
        session.add(user)
        await session.commit()
        await session.refresh(user)

    return user


async def _enrich_ping(
    raw_ping: RawPing,
    privacy_result: PrivacyFilterResult,
    session: AsyncSession,
) -> None:
    """
    Apply all enrichments to a non-home-zone ping.

    PRIVACY NOTE: This function should NEVER be called for home zone pings.

    Enrichments applied:
    1. Weather data (OpenWeatherMap via Redis cache)
    2. Busyness data (Google Live Busyness mock)
    3. Sliding window statistical features
    4. Choke point proximity
    """
    # Weather enrichment (OpenWeatherMap with Redis caching)
    weather = await weather_service.get_weather(
        lat=privacy_result.lat,
        lon=privacy_result.lon,
    )

    # Busyness enrichment (Mock service for XGBoost training)
    busyness = await busyness_service.get_busyness(
        lat=privacy_result.lat,
        lon=privacy_result.lon,
        timestamp=raw_ping.timestamp,
    )

    # Dual sliding window features (30s immediate + 5m baseline)
    recent_pings = await _get_recent_pings(
        user_id=raw_ping.user_id,
        before_timestamp=raw_ping.timestamp,
        session=session,
    )
    window_features = compute_dual_window_features(
        current_ping=PingData(
            timestamp=raw_ping.timestamp,
            speed=raw_ping.speed,
            bearing=raw_ping.bearing,
        ),
        recent_pings=recent_pings,
    )

    # Create enriched ping record with all features
    enriched = EnrichedPing(
        ping_id=raw_ping.id,
        # Weather features (OpenWeatherMap)
        temp_c=weather.temp_c if weather else None,
        feels_like_c=weather.feels_like_c if weather else None,
        humidity_pct=weather.humidity_pct if weather else None,
        rain_1h_mm=weather.rain_1h_mm if weather else None,
        wind_speed_ms=weather.wind_speed_ms if weather else None,
        wind_gust_ms=weather.wind_gust_ms if weather else None,
        visibility_m=weather.visibility_m if weather else None,
        weather_condition=weather.condition if weather else None,
        weather_condition_id=weather.condition_id if weather else None,
        is_daylight=weather.is_daylight if weather else None,
        # Busyness features (Google Live Busyness mock)
        busyness_pct=busyness.busyness_pct,
        usual_busyness_pct=busyness.usual_busyness_pct,
        busyness_delta=busyness.busyness_delta,
        busyness_trend=busyness.trend,
        location_type=busyness.location_type.value,
        busyness_confidence=busyness.confidence,
        busyness_is_mock=busyness.is_mock,
        # Dual sliding window features
        # Short window (30s) - Immediate behavioral spikes
        velocity_jitter_30s=window_features.velocity_jitter_30s,
        bearing_volatility_30s=window_features.bearing_volatility_30s,
        ping_count_30s=window_features.ping_count_30s,
        # Long window (5m) - Baseline context
        velocity_jitter_5m=window_features.velocity_jitter_5m,
        bearing_volatility_5m=window_features.bearing_volatility_5m,
        ping_count_5m=window_features.ping_count_5m,
        # Derived ratios for spike detection
        jitter_ratio=window_features.jitter_ratio,
        volatility_ratio=window_features.volatility_ratio,
        # Stop events
        is_stop_event=window_features.is_stop_event,
        stop_duration_sec=window_features.stop_duration_sec,
    )
    session.add(enriched)

    # Choke point proximity
    await _calculate_choke_proximities(raw_ping, privacy_result, session)

    await session.commit()


async def _get_recent_pings(
    user_id: str,
    before_timestamp: datetime,
    session: AsyncSession,
    window_minutes: int = 10,
) -> list[PingData]:
    """
    Get recent non-home-zone pings for sliding window calculation.

    PRIVACY: Only returns pings where is_home_zone=False.
    """
    from datetime import timedelta

    window_start = before_timestamp - timedelta(minutes=window_minutes)

    result = await session.exec(
        select(RawPing)
        .where(RawPing.user_id == user_id)
        .where(RawPing.is_home_zone == False)  # noqa: E712
        .where(RawPing.timestamp >= window_start)
        .where(RawPing.timestamp < before_timestamp)
        .order_by(RawPing.timestamp.desc())
    )
    pings = list(result)

    return [
        PingData(
            timestamp=p.timestamp,
            speed=p.speed,
            bearing=p.bearing,
        )
        for p in pings
    ]


async def _calculate_choke_proximities(
    raw_ping: RawPing,
    privacy_result: PrivacyFilterResult,
    session: AsyncSession,
) -> None:
    """Calculate and store distances to all choke points."""
    result = await session.exec(select(ChokePoint))
    choke_points = list(result)

    for cp in choke_points:
        distance = haversine_distance(
            privacy_result.lat,
            privacy_result.lon,
            cp.lat,
            cp.lon,
        )
        proximity = PingChokeProximity(
            ping_id=raw_ping.id,
            choke_point_id=cp.id,
            distance_m=distance,
        )
        session.add(proximity)
