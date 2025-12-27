"""Family Dashboard API endpoint."""

import logging
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.config import get_settings
from app.db.models import EnrichedPing, RawPing
from app.db.session import get_session
from app.schemas.dashboard import (
    ActivityInfo,
    DashboardResponse,
    EnvironmentInfo,
    FreshnessInfo,
    LocationInfo,
    RiskInfo,
)
from app.services.feature_translator import translate_features

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Templates directory
templates = Jinja2Templates(directory="app/templates")

# Staleness thresholds (in minutes)
STALE_THRESHOLD_MINUTES = 2
DISCONNECTED_THRESHOLD_MINUTES = 10

# Risk level colors (Tailwind CSS compatible hex)
RISK_COLORS = {
    "low": "#22c55e",      # green-500
    "moderate": "#eab308",  # yellow-500
    "high": "#ef4444",      # red-500
}


def _compute_risk_score(enriched: EnrichedPing) -> float:
    """
    Compute risk score (0-100) from enriched ping features.

    Factors:
    - Velocity jitter (erratic movement)
    - Bearing volatility (direction changes)
    - Stop events (frozen behavior)
    - Busyness (crowded areas)
    - Spike ratios (sudden changes)
    """
    risk = 0.0

    # Movement metrics (prefer 30s window for reactivity)
    jitter = enriched.velocity_jitter_30s or enriched.velocity_jitter_5m or 0
    volatility = enriched.bearing_volatility_30s or enriched.bearing_volatility_5m or 0

    # Jitter contribution (max 25 points)
    risk += min(25, (jitter / 2.0) * 25)

    # Volatility contribution (max 25 points)
    risk += min(25, (volatility / 90) * 25)

    # Stop event contribution (max 10 points)
    if enriched.is_stop_event and enriched.stop_duration_sec:
        risk += min(10, (enriched.stop_duration_sec / 180) * 10)

    # Busyness contribution
    if enriched.busyness_delta:
        abs_delta = abs(enriched.busyness_delta)
        if enriched.busyness_delta > 0:
            # Getting busier is higher risk
            risk += min(30, (abs_delta / 40) * 30)
        else:
            risk += min(20, (abs_delta / 40) * 20)

    # High absolute busyness
    if enriched.busyness_pct and enriched.busyness_pct > 70:
        risk += min(10, ((enriched.busyness_pct - 70) / 30) * 10)

    # Spike multiplier (jitter spike indicates sudden change)
    if enriched.jitter_ratio and enriched.jitter_ratio > 1.5:
        risk *= 1.2

    return min(100, max(0, round(risk, 1)))


def _format_freshness(minutes_ago: float) -> str:
    """Format minutes_ago into human-readable string."""
    if minutes_ago < 1:
        seconds = int(minutes_ago * 60)
        if seconds < 5:
            return "Just now"
        return f"{seconds} seconds ago"
    elif minutes_ago < 60:
        mins = int(minutes_ago)
        return f"{mins} minute{'s' if mins != 1 else ''} ago"
    else:
        hours = int(minutes_ago / 60)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"


def _get_maps_url(lat: float, lon: float) -> str:
    """Generate Google Maps deep-link URL."""
    return f"https://maps.google.com/?q={lat},{lon}"


@router.get("/api/pepper", response_model=DashboardResponse)
async def get_pepper_dashboard(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DashboardResponse:
    """
    Get Pepper's current status for the Family Dashboard.

    Returns risk assessment, activity status, environment context,
    and human-readable explanations.
    """
    # Fetch latest enriched ping for Pepper
    result = await session.exec(
        select(EnrichedPing, RawPing)
        .join(RawPing, EnrichedPing.ping_id == RawPing.id)
        .where(RawPing.user_id == settings.pepper_user_id)
        .order_by(RawPing.timestamp.desc())
        .limit(1)
    )
    row = result.one_or_none()

    # No data case
    if not row:
        return DashboardResponse(
            status="no_data",
            explanations=["No walk data available for Pepper yet."],
            pet_name="Pepper",
        )

    enriched, raw_ping = row

    # Calculate freshness
    now = datetime.now(timezone.utc)
    ping_time = raw_ping.timestamp
    if ping_time.tzinfo is None:
        ping_time = ping_time.replace(tzinfo=timezone.utc)

    minutes_ago = (now - ping_time).total_seconds() / 60

    # Determine connection status
    if minutes_ago > DISCONNECTED_THRESHOLD_MINUTES:
        status = "disconnected"
    elif minutes_ago > STALE_THRESHOLD_MINUTES:
        status = "stale"
    else:
        status = "connected"

    # Compute risk score
    risk_score = _compute_risk_score(enriched)

    # Determine risk level
    if risk_score >= 70:
        risk_level = "high"
    elif risk_score >= 40:
        risk_level = "moderate"
    else:
        risk_level = "low"

    # Translate features to human-readable
    translated = translate_features(enriched, pet_name="Pepper")

    # Build location info (privacy-aware)
    location: Optional[LocationInfo] = None
    if raw_ping.lat is not None and raw_ping.lon is not None:
        # Only expose location if data is fresh enough
        if minutes_ago <= DISCONNECTED_THRESHOLD_MINUTES:
            location = LocationInfo(
                lat=raw_ping.lat,
                lon=raw_ping.lon,
                maps_url=_get_maps_url(raw_ping.lat, raw_ping.lon),
                is_available=True,
            )
        else:
            location = LocationInfo(
                lat=None,
                lon=None,
                maps_url=None,
                is_available=False,
            )
    else:
        # Home zone - no location available
        location = LocationInfo(
            lat=None,
            lon=None,
            maps_url=None,
            is_available=False,
        )

    return DashboardResponse(
        status=status,
        risk=RiskInfo(
            score=risk_score,
            level=risk_level,
            color=RISK_COLORS[risk_level],
        ),
        freshness=FreshnessInfo(
            minutes_ago=round(minutes_ago, 1),
            display=_format_freshness(minutes_ago),
            is_stale=minutes_ago > STALE_THRESHOLD_MINUTES,
        ),
        activity=ActivityInfo(
            label=translated.activity_label,
            movement=translated.movement_type,
            is_stopped=translated.is_stopped,
            stop_duration=translated.stop_duration,
        ),
        environment=EnvironmentInfo(
            crowding=translated.crowding_level,
            weather=translated.weather_description,
            busyness_pct=translated.busyness_pct,
        ),
        explanations=translated.explanations,
        location=location,
        pet_name="Pepper",
    )


@router.get("", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    """
    Serve the Family Dashboard HTML page.

    This endpoint returns a server-rendered HTML page that auto-refreshes
    via JavaScript polling every 15 seconds.
    """
    # Get dashboard data
    dashboard_data = await get_pepper_dashboard(session)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "data": dashboard_data,
        },
    )
