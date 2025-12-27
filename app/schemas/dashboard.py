"""Pydantic schemas for Family Dashboard API."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class RiskInfo(BaseModel):
    """Risk assessment information."""

    score: float = Field(..., ge=0, le=100, description="Risk score 0-100")
    level: Literal["low", "moderate", "high"] = Field(
        ..., description="Risk level category"
    )
    color: str = Field(..., description="Hex color for UI display")


class FreshnessInfo(BaseModel):
    """Data freshness information."""

    minutes_ago: float = Field(..., description="Minutes since last ping")
    display: str = Field(..., description="Human-readable time display")
    is_stale: bool = Field(..., description="True if data may be outdated")


class ActivityInfo(BaseModel):
    """Pepper's current activity status."""

    label: str = Field(..., description="Human-readable activity label")
    movement: Literal["steady", "active", "playing", "erratic", "frozen"] = Field(
        ..., description="Movement pattern category"
    )
    is_stopped: bool = Field(..., description="True if Pepper is stationary")
    stop_duration: Optional[int] = Field(
        None, description="Seconds stopped, if applicable"
    )


class EnvironmentInfo(BaseModel):
    """Environmental context around Pepper."""

    crowding: Literal["quiet", "moderate", "busy"] = Field(
        ..., description="Area crowding level"
    )
    weather: Optional[str] = Field(None, description="Weather condition")
    busyness_pct: Optional[float] = Field(None, description="Busyness percentage 0-100")


class LocationInfo(BaseModel):
    """Location data for Find Pepper feature."""

    lat: Optional[float] = Field(None, description="Latitude (null if home zone)")
    lon: Optional[float] = Field(None, description="Longitude (null if home zone)")
    maps_url: Optional[str] = Field(None, description="Deep-link URL to maps app")
    is_available: bool = Field(
        ..., description="False if location hidden for privacy or stale"
    )


class DashboardResponse(BaseModel):
    """Complete dashboard response for Family Dashboard UI."""

    status: Literal["connected", "stale", "disconnected", "no_data"] = Field(
        ..., description="Connection status for UI state"
    )
    risk: Optional[RiskInfo] = Field(None, description="Risk assessment, null if no data")
    freshness: Optional[FreshnessInfo] = Field(
        None, description="Data freshness, null if no data"
    )
    activity: Optional[ActivityInfo] = Field(
        None, description="Activity info, null if no data"
    )
    environment: Optional[EnvironmentInfo] = Field(
        None, description="Environment info, null if no data"
    )
    explanations: list[str] = Field(
        default_factory=list, description="Human-readable status explanations"
    )
    location: Optional[LocationInfo] = Field(
        None, description="Location for Find Pepper feature"
    )
    pet_name: str = Field(default="Pepper", description="Pet name for personalization")
