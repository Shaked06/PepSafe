"""Pydantic schemas for ping API validation."""

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class PingRequest(BaseModel):
    """Incoming GPS ping request schema."""

    user: str = Field(..., min_length=1, description="User identifier")
    lat: float = Field(..., ge=-90, le=90, description="Latitude")
    lon: float = Field(..., ge=-180, le=180, description="Longitude")
    speed: Optional[float] = Field(default=None, ge=0, description="Speed in m/s")
    bearing: Optional[float] = Field(
        default=None, ge=0, lt=360, description="Bearing in degrees"
    )
    accuracy: Optional[float] = Field(
        default=None, ge=0, description="GPS accuracy in meters"
    )
    timestamp: Optional[datetime] = Field(
        default=None, description="ISO8601 timestamp, defaults to server time"
    )

    @model_validator(mode="after")
    def set_default_timestamp(self) -> "PingRequest":
        """Set timestamp to current UTC time if not provided."""
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)
        return self


class PingResponse(BaseModel):
    """Response schema for ping ingestion."""

    status: str = Field(
        ..., description="'accepted' for stored pings, 'filtered' for home zone"
    )
    ping_id: Optional[int] = Field(
        default=None, description="Database ID, null if filtered"
    )
    enrichment_pending: bool = Field(
        default=False, description="True if enrichment will be processed"
    )


class ErrorResponse(BaseModel):
    """Standard error response schema."""

    error: str
    retry_after: Optional[int] = Field(
        default=None, description="Seconds to wait before retry (for rate limiting)"
    )
