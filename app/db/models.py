"""SQLModel database models for Project Pepper."""

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlmodel import Field, Relationship, SQLModel


class User(SQLModel, table=True):
    """User model with home zone configuration."""

    __tablename__ = "users"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    name: str = Field(index=True)
    home_lat: Optional[float] = Field(default=None)
    home_lon: Optional[float] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    pings: list["RawPing"] = Relationship(back_populates="user")


class RawPing(SQLModel, table=True):
    """
    Raw GPS ping storage.

    PRIVACY CONSTRAINT: When is_home_zone=True, lat/lon/speed/bearing MUST be NULL.
    Only user_id, timestamp, and the flag are stored for home zone pings.
    """

    __tablename__ = "raw_pings"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    timestamp: datetime = Field(index=True)

    # Nullable for privacy - NULL when is_home_zone=True
    lat: Optional[float] = Field(default=None)
    lon: Optional[float] = Field(default=None)
    speed: Optional[float] = Field(default=None)
    bearing: Optional[float] = Field(default=None)
    accuracy: Optional[float] = Field(default=None)

    is_home_zone: bool = Field(default=False, index=True)

    # Relationships
    user: Optional[User] = Relationship(back_populates="pings")
    enrichment: Optional["EnrichedPing"] = Relationship(back_populates="ping")
    choke_proximities: list["PingChokeProximity"] = Relationship(back_populates="ping")


class EnrichedPing(SQLModel, table=True):
    """
    Enriched ping data with weather, busyness, and statistical features.

    Only created for non-home-zone pings.
    """

    __tablename__ = "enriched_pings"

    ping_id: int = Field(foreign_key="raw_pings.id", primary_key=True)

    # Weather enrichment (OpenWeatherMap)
    temp_c: Optional[float] = Field(default=None)
    feels_like_c: Optional[float] = Field(default=None)
    humidity_pct: Optional[float] = Field(default=None)
    rain_1h_mm: Optional[float] = Field(default=None)
    wind_speed_ms: Optional[float] = Field(default=None)
    wind_gust_ms: Optional[float] = Field(default=None)
    visibility_m: Optional[float] = Field(default=None)
    weather_condition: Optional[str] = Field(default=None)
    weather_condition_id: Optional[int] = Field(default=None)
    is_daylight: Optional[bool] = Field(default=None)

    # Busyness enrichment (Google Live Busyness mock)
    busyness_pct: Optional[float] = Field(default=None)
    usual_busyness_pct: Optional[float] = Field(default=None)
    busyness_delta: Optional[float] = Field(default=None)
    busyness_trend: Optional[str] = Field(default=None)
    location_type: Optional[str] = Field(default=None)
    busyness_confidence: Optional[float] = Field(default=None)
    busyness_is_mock: Optional[bool] = Field(default=None)

    # Dual sliding window statistical features
    # Short window (30s) - Immediate behavioral spikes
    velocity_jitter_30s: Optional[float] = Field(default=None)
    bearing_volatility_30s: Optional[float] = Field(default=None)
    ping_count_30s: Optional[int] = Field(default=None)

    # Long window (5m) - Baseline context
    velocity_jitter_5m: Optional[float] = Field(default=None)
    bearing_volatility_5m: Optional[float] = Field(default=None)
    ping_count_5m: Optional[int] = Field(default=None)

    # Derived features - Spike detection ratios
    jitter_ratio: Optional[float] = Field(default=None)  # 30s/5m (>1 = spike)
    volatility_ratio: Optional[float] = Field(default=None)  # 30s/5m (>1 = erratic)

    # Stop event detection
    is_stop_event: bool = Field(default=False)
    stop_duration_sec: Optional[int] = Field(default=None)

    # Relationships
    ping: Optional[RawPing] = Relationship(back_populates="enrichment")


class ChokePoint(SQLModel, table=True):
    """Predefined geographic points of interest for proximity tracking."""

    __tablename__ = "choke_points"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    lat: float
    lon: float
    radius_m: float = Field(default=50.0)
    category: Optional[str] = Field(default=None)

    # Relationships
    ping_proximities: list["PingChokeProximity"] = Relationship(back_populates="choke_point")


class PingChokeProximity(SQLModel, table=True):
    """Junction table storing distance from each ping to each choke point."""

    __tablename__ = "ping_choke_proximity"

    ping_id: int = Field(foreign_key="raw_pings.id", primary_key=True)
    choke_point_id: int = Field(foreign_key="choke_points.id", primary_key=True)
    distance_m: float

    # Relationships
    ping: Optional[RawPing] = Relationship(back_populates="choke_proximities")
    choke_point: Optional[ChokePoint] = Relationship(back_populates="ping_proximities")
