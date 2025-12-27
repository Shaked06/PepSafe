"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable loading."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str = "sqlite+aiosqlite:///./pepper.db"

    # Redis
    redis_url: str = "redis://localhost:6379"
    redis_weather_ttl_seconds: int = 600  # 10 minutes

    # OpenWeatherMap
    openweathermap_api_key: str = ""
    openweathermap_base_url: str = "https://api.openweathermap.org/data/2.5"

    # Privacy (HARD CONSTRAINT)
    home_zone_radius_meters: float = 50.0

    # Pepper's home coordinates (for default user setup)
    pepper_home_lat: float | None = None
    pepper_home_lon: float | None = None
    pepper_user_id: str = "pepper"

    # Rate Limiting
    rate_limit_requests_per_minute: int = 60

    # Logging
    log_level: str = "INFO"

    # Server
    port: int = 8000


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
