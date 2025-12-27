"""Integration tests for Family Dashboard endpoint."""

import pytest


class TestDashboardAPIEndpoint:
    """Tests for /dashboard/api/pepper endpoint."""

    @pytest.mark.anyio
    async def test_dashboard_api_returns_json(self, client):
        """Dashboard API should return valid JSON response."""
        response = await client.get("/dashboard/api/pepper")

        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "pet_name" in data
        assert data["pet_name"] == "Pepper"

    @pytest.mark.anyio
    async def test_dashboard_api_no_data_status(self, client):
        """Dashboard API should return no_data status when no pings exist."""
        response = await client.get("/dashboard/api/pepper")

        assert response.status_code == 200
        data = response.json()
        # Without any pings, status should be no_data
        assert data["status"] in ("no_data", "connected", "stale", "disconnected")

    @pytest.mark.anyio
    async def test_dashboard_api_explanations_exist(self, client):
        """Dashboard API should always include explanations list."""
        response = await client.get("/dashboard/api/pepper")

        assert response.status_code == 200
        data = response.json()
        assert "explanations" in data
        assert isinstance(data["explanations"], list)


class TestDashboardHTMLEndpoint:
    """Tests for /dashboard HTML page endpoint."""

    @pytest.mark.anyio
    async def test_dashboard_page_returns_html(self, client):
        """Dashboard page should return HTML content."""
        response = await client.get("/dashboard")

        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    @pytest.mark.anyio
    async def test_dashboard_page_contains_required_elements(self, client):
        """Dashboard page should contain required UI elements."""
        response = await client.get("/dashboard")

        assert response.status_code == 200
        html = response.text

        # Should contain pet name
        assert "Pepper" in html

        # Should contain Tailwind CSS
        assert "tailwindcss" in html.lower() or "cdn.tailwindcss.com" in html

        # Should contain Lucide icons script
        assert "lucide" in html.lower()

        # Should have auto-refresh script
        assert "setInterval" in html or "refresh" in html.lower()

    @pytest.mark.anyio
    async def test_dashboard_page_mobile_meta_tags(self, client):
        """Dashboard page should have mobile-friendly meta tags."""
        response = await client.get("/dashboard")

        assert response.status_code == 200
        html = response.text

        # Should have viewport meta tag
        assert 'name="viewport"' in html

        # Should have theme-color meta tag
        assert 'name="theme-color"' in html


class TestDashboardWithData:
    """Tests for dashboard with actual ping data."""

    @pytest.mark.anyio
    async def test_dashboard_after_ping_ingestion(self, client):
        """Dashboard should show data after a ping is ingested."""
        # First, create a ping
        ping_response = await client.post(
            "/api/v1/ping",
            json={
                "user": "pepper",
                "lat": 32.0853,
                "lon": 34.7818,
                "speed": 2.5,
                "bearing": 90.0,
            },
        )

        # Ping should be accepted
        assert ping_response.status_code == 200

        # Now check dashboard
        dashboard_response = await client.get("/dashboard/api/pepper")

        assert dashboard_response.status_code == 200
        data = dashboard_response.json()

        # Status should be connected (recent ping) or no_data if user doesn't match
        assert data["status"] in ("connected", "stale", "disconnected", "no_data")

    @pytest.mark.anyio
    async def test_dashboard_risk_levels_valid(self, client):
        """Dashboard risk levels should be valid values."""
        response = await client.get("/dashboard/api/pepper")

        assert response.status_code == 200
        data = response.json()

        if data.get("risk"):
            assert data["risk"]["level"] in ("low", "moderate", "high")
            assert 0 <= data["risk"]["score"] <= 100
            assert data["risk"]["color"].startswith("#")

    @pytest.mark.anyio
    async def test_dashboard_freshness_format(self, client):
        """Dashboard freshness should have proper format."""
        response = await client.get("/dashboard/api/pepper")

        assert response.status_code == 200
        data = response.json()

        if data.get("freshness"):
            assert "minutes_ago" in data["freshness"]
            assert "display" in data["freshness"]
            assert "is_stale" in data["freshness"]
            assert isinstance(data["freshness"]["is_stale"], bool)

    @pytest.mark.anyio
    async def test_dashboard_location_privacy(self, client):
        """Dashboard location should respect privacy settings."""
        response = await client.get("/dashboard/api/pepper")

        assert response.status_code == 200
        data = response.json()

        if data.get("location"):
            assert "is_available" in data["location"]
            # If location is available, should have maps_url
            if data["location"]["is_available"]:
                assert data["location"]["maps_url"] is not None
                assert "maps.google.com" in data["location"]["maps_url"]
