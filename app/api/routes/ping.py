"""Ping ingestion endpoint."""

import logging
from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import get_settings
from app.db.session import get_session
from app.schemas.ping import ErrorResponse, PingRequest, PingResponse
from app.services.enrichment import process_ping

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/v1/ping", tags=["ingestion"])


class OwnTracksLocation(BaseModel):
    """OwnTracks location payload schema."""

    model_config = {"extra": "ignore"}  # Ignore extra fields like _type

    lat: float = Field(..., description="Latitude")
    lon: float = Field(..., description="Longitude")
    vel: Optional[int] = Field(default=None, description="Velocity in km/h")
    cog: Optional[int] = Field(default=None, description="Course over ground (bearing)")
    acc: Optional[int] = Field(default=None, description="Accuracy in meters")
    tst: Optional[int] = Field(default=None, description="Unix timestamp")
    tid: Optional[str] = Field(default=None, description="Tracker ID (2 chars)")
    batt: Optional[int] = Field(default=None, description="Battery percentage")


@router.post(
    "",
    response_model=PingResponse,
    responses={
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
        503: {"model": ErrorResponse, "description": "Service temporarily unavailable"},
    },
)
async def ingest_ping(
    request: PingRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PingResponse:
    """
    Ingest a GPS ping and process through enrichment pipeline.

    The ping goes through:
    1. Privacy filtering (home zone check)
    2. Weather enrichment (cached)
    3. Choke point proximity calculation
    4. Sliding window statistical features

    If the ping is within the user's home zone (50m radius),
    coordinates are nullified and enrichment is skipped.
    """
    try:
        return await process_ping(request, session)
    except Exception as e:
        # PRIVACY: Never log request details that might contain coordinates
        # Log error type and message for debugging (no coords)
        logger.error(f"Ping processing failed: {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service temporarily unavailable",
        )


@router.post(
    "/owntracks",
    response_model=PingResponse,
    responses={
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
        503: {"model": ErrorResponse, "description": "Service temporarily unavailable"},
    },
)
async def owntracks_webhook(
    payload: OwnTracksLocation,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PingResponse:
    """
    OwnTracks HTTP webhook endpoint.

    Receives location data from OwnTracks app and converts to internal format.
    Configure OwnTracks in HTTP mode pointing to this endpoint.

    OwnTracks payload conversion:
    - vel (km/h) -> speed (m/s)
    - cog (degrees) -> bearing
    - tst (unix) -> timestamp (datetime)
    - tid -> ignored (uses configured pepper_user_id)
    """
    # Convert OwnTracks format to internal PingRequest
    # Speed: OwnTracks sends km/h, we store m/s
    speed_ms = None
    if payload.vel is not None:
        speed_ms = payload.vel / 3.6  # km/h to m/s

    # Bearing: OwnTracks sends as "cog" (course over ground)
    bearing = float(payload.cog) if payload.cog is not None else None

    # Timestamp: OwnTracks sends Unix timestamp
    timestamp = datetime.now(timezone.utc)
    if payload.tst is not None:
        timestamp = datetime.fromtimestamp(payload.tst, tz=timezone.utc)

    # Create internal ping request
    ping_request = PingRequest(
        user=settings.pepper_user_id,  # Always use configured Pepper user
        lat=payload.lat,
        lon=payload.lon,
        speed=speed_ms,
        bearing=bearing,
        accuracy=float(payload.acc) if payload.acc is not None else None,
        timestamp=timestamp,
    )

    try:
        return await process_ping(ping_request, session)
    except Exception as e:
        logger.error(f"OwnTracks ping processing failed: {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service temporarily unavailable",
        )
