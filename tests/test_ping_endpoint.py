"""Integration tests for /api/v1/ping endpoint."""

import uuid

import pytest


def unique_user() -> str:
    """Generate a unique user ID for each test."""
    return f"test_user_{uuid.uuid4().hex[:8]}"


class TestPingEndpoint:
    """Tests for /api/v1/ping POST endpoint."""

    @pytest.mark.anyio
    async def test_valid_ping_accepted(self, client):
        """Valid ping should be accepted."""
        response = await client.post(
            "/api/v1/ping",
            json={
                "user": unique_user(),
                "lat": 32.0853,
                "lon": 34.7818,
                "speed": 5.0,
                "bearing": 90.0,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("accepted", "filtered", "ok")
        assert "ping_id" in data

    @pytest.mark.anyio
    async def test_minimal_ping_accepted(self, client):
        """Ping with only required fields should be accepted."""
        response = await client.post(
            "/api/v1/ping",
            json={
                "user": unique_user(),
                "lat": 32.0853,
                "lon": 34.7818,
            },
        )

        assert response.status_code == 200

    @pytest.mark.anyio
    async def test_invalid_latitude_rejected(self, client):
        """Latitude outside valid range should be rejected."""
        response = await client.post(
            "/api/v1/ping",
            json={
                "user": "test_user",
                "lat": 91.0,  # Invalid: > 90
                "lon": 34.7818,
            },
        )

        assert response.status_code == 422  # Validation error

    @pytest.mark.anyio
    async def test_invalid_longitude_rejected(self, client):
        """Longitude outside valid range should be rejected."""
        response = await client.post(
            "/api/v1/ping",
            json={
                "user": "test_user",
                "lat": 32.0853,
                "lon": 181.0,  # Invalid: > 180
            },
        )

        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_invalid_bearing_rejected(self, client):
        """Bearing outside valid range should be rejected."""
        response = await client.post(
            "/api/v1/ping",
            json={
                "user": "test_user",
                "lat": 32.0853,
                "lon": 34.7818,
                "bearing": 400.0,  # Invalid: >= 360
            },
        )

        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_negative_speed_rejected(self, client):
        """Negative speed should be rejected."""
        response = await client.post(
            "/api/v1/ping",
            json={
                "user": "test_user",
                "lat": 32.0853,
                "lon": 34.7818,
                "speed": -5.0,  # Invalid: < 0
            },
        )

        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_missing_user_rejected(self, client):
        """Missing user field should be rejected."""
        response = await client.post(
            "/api/v1/ping",
            json={
                "lat": 32.0853,
                "lon": 34.7818,
            },
        )

        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_empty_user_rejected(self, client):
        """Empty user string should be rejected."""
        response = await client.post(
            "/api/v1/ping",
            json={
                "user": "",
                "lat": 32.0853,
                "lon": 34.7818,
            },
        )

        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_custom_timestamp_accepted(self, client):
        """Custom timestamp should be accepted."""
        response = await client.post(
            "/api/v1/ping",
            json={
                "user": unique_user(),
                "lat": 32.0853,
                "lon": 34.7818,
                "timestamp": "2024-01-15T10:30:00Z",
            },
        )

        assert response.status_code == 200


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    @pytest.mark.anyio
    async def test_health_check(self, client):
        """Health check should return status."""
        response = await client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "cache_available" in data


class TestChokePointsEndpoint:
    """Tests for /api/v1/choke-points endpoints."""

    @pytest.mark.anyio
    async def test_create_choke_point(self, client):
        """Should create a new choke point."""
        response = await client.post(
            "/api/v1/choke-points",
            json={
                "name": "Test Point",
                "lat": 32.0853,
                "lon": 34.7818,
                "radius_m": 50.0,
                "category": "intersection",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Point"
        assert data["id"] is not None

    @pytest.mark.anyio
    async def test_list_choke_points(self, client):
        """Should list all choke points."""
        response = await client.get("/api/v1/choke-points")

        assert response.status_code == 200
        assert isinstance(response.json(), list)

    @pytest.mark.anyio
    async def test_delete_nonexistent_choke_point(self, client):
        """Should return 404 for nonexistent choke point."""
        response = await client.delete("/api/v1/choke-points/99999")

        assert response.status_code == 404
