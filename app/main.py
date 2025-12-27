"""FastAPI application entry point for Project Pepper."""

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Depends
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.routes import choke_points, ping, users
from app.config import get_settings
from app.db.models import EnrichedPing, RawPing, User
from app.db.session import init_db, get_session
from app.middleware.security import APIKeyMiddleware, RateLimitMiddleware
from app.services.cache import cache_service
from app.services.weather import weather_service

settings = get_settings()

# Configure logging - PRIVACY: Never log coordinates
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def compute_risk_score(enriched: EnrichedPing) -> float:
    """
    Compute risk score (0-100) from enriched ping features.

    Feature Weights:
    - Behavioral (60%): velocity_jitter, bearing_volatility, stop patterns
    - Environmental (40%): busyness_delta (30%), busyness_pct (10%)

    Uses dual-window features when available, falls back to 5m window.
    """
    risk = 0.0

    # Get jitter value (prefer 30s for immediate spike detection)
    jitter = enriched.velocity_jitter_30s or enriched.velocity_jitter_5m or 0
    volatility = enriched.bearing_volatility_30s or enriched.bearing_volatility_5m or 0

    # Velocity Jitter (0-25 points)
    risk += min(25, (jitter / 2.0) * 25)

    # Bearing Volatility (0-25 points)
    risk += min(25, (volatility / 90) * 25)

    # Stop Event (0-10 points)
    if enriched.is_stop_event and enriched.stop_duration_sec:
        risk += min(10, (enriched.stop_duration_sec / 180) * 10)

    # Busyness Delta (0-30 points) - Unexpected crowd changes
    if enriched.busyness_delta:
        abs_delta = abs(enriched.busyness_delta)
        if enriched.busyness_delta > 0:
            risk += min(30, (abs_delta / 40) * 30)
        else:
            risk += min(20, (abs_delta / 40) * 20)

    # Busyness Percentage (0-10 points)
    if enriched.busyness_pct and enriched.busyness_pct > 70:
        risk += min(10, ((enriched.busyness_pct - 70) / 30) * 10)

    # Spike ratio boost (if recent spike detected)
    if enriched.jitter_ratio and enriched.jitter_ratio > 1.5:
        risk *= 1.2  # 20% boost for behavioral spike

    return min(100, max(0, round(risk, 1)))


async def setup_default_user(session: AsyncSession) -> None:
    """Create default Pepper user with home coordinates if configured."""
    if not settings.pepper_home_lat or not settings.pepper_home_lon:
        return

    result = await session.exec(
        select(User).where(User.id == settings.pepper_user_id)
    )
    user = result.one_or_none()

    if not user:
        user = User(
            id=settings.pepper_user_id,
            name="Pepper",
            home_lat=settings.pepper_home_lat,
            home_lon=settings.pepper_home_lon,
        )
        session.add(user)
        await session.commit()
        logger.info(f"Created default user: {settings.pepper_user_id}")
    elif user.home_lat is None:
        user.home_lat = settings.pepper_home_lat
        user.home_lon = settings.pepper_home_lon
        session.add(user)
        await session.commit()
        logger.info(f"Updated home coordinates for: {settings.pepper_user_id}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management."""
    # Startup
    logger.info("Starting Project Pepper...")
    await init_db()
    await cache_service.connect()
    await weather_service.start()

    # Setup default user
    async for session in get_session():
        await setup_default_user(session)
        break

    logger.info("Project Pepper ready")

    yield

    # Shutdown
    logger.info("Shutting down Project Pepper...")
    await weather_service.stop()
    await cache_service.disconnect()
    logger.info("Project Pepper stopped")


app = FastAPI(
    title="Project Pepper",
    description="GPS Ingestion & Enrichment Pipeline with Privacy-First Design",
    version="0.1.0",
    lifespan=lifespan,
)

# Security middleware (order matters: rate limit first, then auth)
app.add_middleware(APIKeyMiddleware)
app.add_middleware(
    RateLimitMiddleware,
    requests_per_minute=settings.rate_limit_requests_per_minute,
    burst=settings.rate_limit_burst,
)

# Include routers
app.include_router(ping.router)
app.include_router(choke_points.router)
app.include_router(users.router)


@app.get("/health")
async def health_check() -> dict:
    """
    Health check endpoint with latest risk status.

    Returns:
    - status: API health status
    - cache_available: Redis connection status
    - pepper: Latest walk data for Pepper (if available)
    """
    return {
        "status": "healthy",
        "cache_available": cache_service.is_available,
        "version": "0.1.0",
    }


@app.get("/health/pepper")
async def pepper_status(session: AsyncSession = Depends(get_session)) -> dict:
    """
    Get Pepper's latest risk score and walk status.

    This endpoint is designed for quick mobile browser checks.
    Shows the most recent GPS ping and computed risk score.

    Returns:
    - risk_score: Current risk level (0-100)
    - risk_level: Human-readable risk category
    - last_ping: Timestamp of most recent ping
    - features: Key behavioral/environmental metrics
    - status: Walk status (active/inactive)
    """
    # Get latest enriched ping for Pepper
    result = await session.exec(
        select(EnrichedPing, RawPing)
        .join(RawPing, EnrichedPing.ping_id == RawPing.id)
        .where(RawPing.user_id == settings.pepper_user_id)
        .order_by(RawPing.timestamp.desc())
        .limit(1)
    )
    row = result.one_or_none()

    if not row:
        return {
            "status": "no_data",
            "message": "No walk data available for Pepper yet",
            "user_id": settings.pepper_user_id,
        }

    enriched, raw_ping = row

    # Compute risk score
    risk_score = compute_risk_score(enriched)

    # Determine risk level
    if risk_score >= 70:
        risk_level = "HIGH"
        risk_emoji = "!!!"
    elif risk_score >= 40:
        risk_level = "MODERATE"
        risk_emoji = "!"
    else:
        risk_level = "LOW"
        risk_emoji = "ok"

    # Calculate time since last ping
    now = datetime.now(timezone.utc)
    ping_time = raw_ping.timestamp
    if ping_time.tzinfo is None:
        ping_time = ping_time.replace(tzinfo=timezone.utc)
    time_since = now - ping_time
    minutes_ago = int(time_since.total_seconds() / 60)

    # Determine walk status
    if minutes_ago < 5:
        walk_status = "active"
    elif minutes_ago < 30:
        walk_status = "recent"
    else:
        walk_status = "inactive"

    return {
        "status": walk_status,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "risk_emoji": risk_emoji,
        "last_ping": raw_ping.timestamp.isoformat(),
        "minutes_ago": minutes_ago,
        "features": {
            # Behavioral (30s window - immediate)
            "jitter_30s": round(enriched.velocity_jitter_30s, 2) if enriched.velocity_jitter_30s else None,
            "volatility_30s": round(enriched.bearing_volatility_30s, 1) if enriched.bearing_volatility_30s else None,
            # Behavioral (5m window - baseline)
            "jitter_5m": round(enriched.velocity_jitter_5m, 2) if enriched.velocity_jitter_5m else None,
            "volatility_5m": round(enriched.bearing_volatility_5m, 1) if enriched.bearing_volatility_5m else None,
            # Spike ratios
            "jitter_ratio": round(enriched.jitter_ratio, 2) if enriched.jitter_ratio else None,
            "volatility_ratio": round(enriched.volatility_ratio, 2) if enriched.volatility_ratio else None,
            # Stop event
            "is_stopped": enriched.is_stop_event,
            "stop_duration": enriched.stop_duration_sec,
            # Environment
            "busyness": enriched.busyness_pct,
            "busyness_delta": enriched.busyness_delta,
            "weather": enriched.weather_condition,
        },
        "user_id": settings.pepper_user_id,
    }


@app.get("/")
async def root() -> dict:
    """Root endpoint with API info."""
    return {
        "name": "Project Pepper",
        "description": "Canine Reactivity Detection Pipeline",
        "version": "0.1.0",
        "endpoints": {
            "health": "/health",
            "pepper_status": "/health/pepper",
            "ingest_ping": "POST /api/v1/ping",
            "docs": "/docs",
        },
    }
