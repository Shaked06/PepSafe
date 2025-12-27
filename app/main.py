"""FastAPI application entry point for Project Pepper.

CRITICAL FOR RENDER DEPLOYMENT:
- Server must bind to port IMMEDIATELY (within 1-2 seconds)
- Health check must respond BEFORE any DB/Redis/ML initialization
- All heavy initialization is done lazily on first request
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Depends, Request
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

# =============================================================================
# IMMEDIATE STARTUP - Print port binding message FIRST
# =============================================================================
PORT = int(os.environ.get("PORT", 10000))
print(f"🚀 Server starting on port {PORT}", flush=True)
sys.stdout.flush()

# =============================================================================
# CREATE APP IMMEDIATELY - No initialization blocking
# =============================================================================
app = FastAPI(
    title="Project Pepper",
    description="GPS Ingestion & Enrichment Pipeline with Privacy-First Design",
    version="0.1.0",
    # NO lifespan - we use lazy initialization instead
)

# =============================================================================
# HEALTH CHECK - MUST BE FIRST, RESPONDS INSTANTLY
# =============================================================================
@app.get("/health")
async def health_check() -> dict:
    """Instant health check for Render port scanning. No dependencies."""
    return {"status": "ok"}


@app.get("/")
async def root() -> dict:
    """Root endpoint - also instant, no dependencies."""
    return {
        "name": "Project Pepper",
        "version": "0.1.0",
        "status": "running",
    }


# =============================================================================
# LAZY INITIALIZATION STATE
# =============================================================================
_initialized = False
_init_lock = asyncio.Lock()


async def ensure_initialized():
    """Lazy initialization - only runs on first real request."""
    global _initialized

    if _initialized:
        return

    async with _init_lock:
        if _initialized:  # Double-check after acquiring lock
            return

        print("📦 Initializing services (lazy load)...", flush=True)

        try:
            from app.db.session import init_db
            from app.services.cache import cache_service
            from app.services.weather import weather_service

            await init_db()
            print("  ✓ Database initialized", flush=True)

            await cache_service.connect()
            print("  ✓ Cache connected", flush=True)

            await weather_service.start()
            print("  ✓ Weather service started", flush=True)

            # Setup default user
            from app.db.session import get_session
            from app.config import get_settings
            settings = get_settings()

            if settings.pepper_home_lat and settings.pepper_home_lon:
                async for session in get_session():
                    await _setup_default_user(session, settings)
                    break

            print("✅ All services initialized", flush=True)
            _initialized = True

        except Exception as e:
            print(f"⚠️ Initialization warning: {e}", flush=True)
            # Don't fail - allow app to continue, will retry on next request
            _initialized = True  # Prevent retry loop


async def _setup_default_user(session: AsyncSession, settings) -> None:
    """Create default Pepper user with home coordinates if configured."""
    from app.db.models import User

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
        print(f"  ✓ Created default user: {settings.pepper_user_id}", flush=True)


# =============================================================================
# INITIALIZATION MIDDLEWARE - Lazy init on first real request
# =============================================================================
@app.middleware("http")
async def lazy_init_middleware(request: Request, call_next):
    """Initialize services lazily on first non-health request."""
    # Skip initialization for health checks
    if request.url.path in ("/health", "/"):
        return await call_next(request)

    # Ensure initialized for all other requests
    await ensure_initialized()
    return await call_next(request)


# =============================================================================
# DEFERRED IMPORTS AND SETUP - Only after app is created
# =============================================================================
from app.config import get_settings
settings = get_settings()

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Security middleware
from app.middleware.security import APIKeyMiddleware, RateLimitMiddleware
app.add_middleware(APIKeyMiddleware)
app.add_middleware(
    RateLimitMiddleware,
    requests_per_minute=settings.rate_limit_requests_per_minute,
    burst=settings.rate_limit_burst,
)

# Include routers
from app.api.routes import choke_points, ping, users
app.include_router(ping.router)
app.include_router(choke_points.router)
app.include_router(users.router)


# =============================================================================
# ADDITIONAL ENDPOINTS (after routers)
# =============================================================================
@app.get("/health/ready")
async def readiness_check() -> dict:
    """Full readiness check - triggers initialization if needed."""
    await ensure_initialized()

    from app.services.cache import cache_service
    return {
        "status": "ready",
        "initialized": _initialized,
        "cache_available": cache_service.is_available,
        "version": "0.1.0",
    }


@app.get("/health/pepper")
async def pepper_status(session: AsyncSession = Depends(get_session)) -> dict:
    """Get Pepper's latest risk score and walk status."""
    from app.db.models import EnrichedPing, RawPing
    from app.db.session import get_session

    await ensure_initialized()

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
    risk_score = _compute_risk_score(enriched)

    # Determine risk level
    if risk_score >= 70:
        risk_level, risk_emoji = "HIGH", "!!!"
    elif risk_score >= 40:
        risk_level, risk_emoji = "MODERATE", "!"
    else:
        risk_level, risk_emoji = "LOW", "ok"

    # Calculate time since last ping
    now = datetime.now(timezone.utc)
    ping_time = raw_ping.timestamp
    if ping_time.tzinfo is None:
        ping_time = ping_time.replace(tzinfo=timezone.utc)
    minutes_ago = int((now - ping_time).total_seconds() / 60)

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
            "jitter_30s": round(enriched.velocity_jitter_30s, 2) if enriched.velocity_jitter_30s else None,
            "volatility_30s": round(enriched.bearing_volatility_30s, 1) if enriched.bearing_volatility_30s else None,
            "jitter_5m": round(enriched.velocity_jitter_5m, 2) if enriched.velocity_jitter_5m else None,
            "volatility_5m": round(enriched.bearing_volatility_5m, 1) if enriched.bearing_volatility_5m else None,
            "jitter_ratio": round(enriched.jitter_ratio, 2) if enriched.jitter_ratio else None,
            "volatility_ratio": round(enriched.volatility_ratio, 2) if enriched.volatility_ratio else None,
            "is_stopped": enriched.is_stop_event,
            "stop_duration": enriched.stop_duration_sec,
            "busyness": enriched.busyness_pct,
            "busyness_delta": enriched.busyness_delta,
            "weather": enriched.weather_condition,
        },
        "user_id": settings.pepper_user_id,
    }


def _compute_risk_score(enriched) -> float:
    """Compute risk score (0-100) from enriched ping features."""
    risk = 0.0

    jitter = enriched.velocity_jitter_30s or enriched.velocity_jitter_5m or 0
    volatility = enriched.bearing_volatility_30s or enriched.bearing_volatility_5m or 0

    risk += min(25, (jitter / 2.0) * 25)
    risk += min(25, (volatility / 90) * 25)

    if enriched.is_stop_event and enriched.stop_duration_sec:
        risk += min(10, (enriched.stop_duration_sec / 180) * 10)

    if enriched.busyness_delta:
        abs_delta = abs(enriched.busyness_delta)
        if enriched.busyness_delta > 0:
            risk += min(30, (abs_delta / 40) * 30)
        else:
            risk += min(20, (abs_delta / 40) * 20)

    if enriched.busyness_pct and enriched.busyness_pct > 70:
        risk += min(10, ((enriched.busyness_pct - 70) / 30) * 10)

    if enriched.jitter_ratio and enriched.jitter_ratio > 1.5:
        risk *= 1.2

    return min(100, max(0, round(risk, 1)))


# Import for type hints in health/pepper endpoint
from app.db.session import get_session

print(f"✅ App created, ready to accept connections on port {PORT}", flush=True)
