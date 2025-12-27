"""Tests for the feature translation service."""

import pytest

from app.services.feature_translator import (
    BUSYNESS_BUSY_THRESHOLD,
    BUSYNESS_QUIET_THRESHOLD,
    JITTER_ACTIVE_THRESHOLD,
    JITTER_CALM_THRESHOLD,
    STOP_LONG_DURATION_SEC,
    VOLATILITY_ERRATIC_THRESHOLD,
    generate_explanations,
    translate_activity,
    translate_crowding,
)


class TestTranslateActivity:
    """Tests for activity translation logic."""

    def test_stopped_short_duration(self):
        """Stopped with short duration should return Paused."""
        label, movement = translate_activity(
            jitter_ratio=0.5,
            volatility_ratio=0.5,
            is_stop_event=True,
            stop_duration_sec=30,
        )
        assert label == "Paused"
        assert movement == "frozen"

    def test_stopped_long_duration(self):
        """Stopped for long time should return Resting."""
        label, movement = translate_activity(
            jitter_ratio=0.5,
            volatility_ratio=0.5,
            is_stop_event=True,
            stop_duration_sec=STOP_LONG_DURATION_SEC + 10,
        )
        assert label == "Resting"
        assert movement == "frozen"

    def test_calm_walk(self):
        """Low jitter ratio should return Calm walk."""
        label, movement = translate_activity(
            jitter_ratio=JITTER_CALM_THRESHOLD - 0.1,
            volatility_ratio=0.5,
            is_stop_event=False,
            stop_duration_sec=None,
        )
        assert label == "Calm walk"
        assert movement == "steady"

    def test_active(self):
        """Medium jitter ratio should return Active."""
        label, movement = translate_activity(
            jitter_ratio=(JITTER_CALM_THRESHOLD + JITTER_ACTIVE_THRESHOLD) / 2,
            volatility_ratio=0.5,
            is_stop_event=False,
            stop_duration_sec=None,
        )
        assert label == "Active"
        assert movement == "active"

    def test_playing(self):
        """High jitter ratio should return Playing."""
        label, movement = translate_activity(
            jitter_ratio=JITTER_ACTIVE_THRESHOLD + 0.5,
            volatility_ratio=0.5,
            is_stop_event=False,
            stop_duration_sec=None,
        )
        assert label == "Playing"
        assert movement == "playing"

    def test_erratic_movement(self):
        """High volatility ratio should return erratic."""
        label, movement = translate_activity(
            jitter_ratio=0.5,
            volatility_ratio=VOLATILITY_ERRATIC_THRESHOLD + 0.5,
            is_stop_event=False,
            stop_duration_sec=None,
        )
        assert label == "Exploring actively"
        assert movement == "erratic"

    def test_none_jitter_defaults_to_walking(self):
        """None jitter ratio should return Walking."""
        label, movement = translate_activity(
            jitter_ratio=None,
            volatility_ratio=0.5,
            is_stop_event=False,
            stop_duration_sec=None,
        )
        assert label == "Walking"
        assert movement == "steady"


class TestTranslateCrowding:
    """Tests for crowding translation logic."""

    def test_quiet_area(self):
        """Low busyness should return quiet."""
        result = translate_crowding(BUSYNESS_QUIET_THRESHOLD - 10)
        assert result == "quiet"

    def test_moderate_area(self):
        """Medium busyness should return moderate."""
        result = translate_crowding(
            (BUSYNESS_QUIET_THRESHOLD + BUSYNESS_BUSY_THRESHOLD) / 2
        )
        assert result == "moderate"

    def test_busy_area(self):
        """High busyness should return busy."""
        result = translate_crowding(BUSYNESS_BUSY_THRESHOLD + 10)
        assert result == "busy"

    def test_none_defaults_to_moderate(self):
        """None busyness should default to moderate."""
        result = translate_crowding(None)
        assert result == "moderate"


class TestGenerateExplanations:
    """Tests for explanation generation."""

    def test_stopped_explanation(self):
        """Stopped event should generate stop explanation."""
        explanations = generate_explanations(
            jitter_ratio=0.5,
            volatility_ratio=0.5,
            is_stop_event=True,
            stop_duration_sec=30,
            busyness_pct=None,
            busyness_delta=None,
            weather_condition=None,
            pet_name="Pepper",
        )
        assert any("stopped" in e.lower() for e in explanations)

    def test_long_stop_includes_duration(self):
        """Long stop should include duration in explanation."""
        explanations = generate_explanations(
            jitter_ratio=0.5,
            volatility_ratio=0.5,
            is_stop_event=True,
            stop_duration_sec=120,
            busyness_pct=None,
            busyness_delta=None,
            weather_condition=None,
            pet_name="Pepper",
        )
        assert any("120 seconds" in e for e in explanations)

    def test_calm_walk_explanation(self):
        """Low jitter should generate calm explanation."""
        explanations = generate_explanations(
            jitter_ratio=JITTER_CALM_THRESHOLD - 0.1,
            volatility_ratio=0.5,
            is_stop_event=False,
            stop_duration_sec=None,
            busyness_pct=None,
            busyness_delta=None,
            weather_condition=None,
            pet_name="Pepper",
        )
        assert any("steadily" in e.lower() for e in explanations)

    def test_busy_area_explanation(self):
        """High busyness should generate busy explanation."""
        explanations = generate_explanations(
            jitter_ratio=0.5,
            volatility_ratio=0.5,
            is_stop_event=False,
            stop_duration_sec=None,
            busyness_pct=BUSYNESS_BUSY_THRESHOLD + 10,
            busyness_delta=None,
            weather_condition=None,
            pet_name="Pepper",
        )
        assert any("busy" in e.lower() for e in explanations)

    def test_busyness_surge_explanation(self):
        """Large positive busyness delta should generate surge explanation."""
        explanations = generate_explanations(
            jitter_ratio=0.5,
            volatility_ratio=0.5,
            is_stop_event=False,
            stop_duration_sec=None,
            busyness_pct=50,
            busyness_delta=25,
            weather_condition=None,
            pet_name="Pepper",
        )
        assert any("crowded" in e.lower() for e in explanations)

    def test_rain_explanation(self):
        """Rain weather should generate rain explanation."""
        explanations = generate_explanations(
            jitter_ratio=0.5,
            volatility_ratio=0.5,
            is_stop_event=False,
            stop_duration_sec=None,
            busyness_pct=None,
            busyness_delta=None,
            weather_condition="Light Rain",
            pet_name="Pepper",
        )
        assert any("raining" in e.lower() for e in explanations)

    def test_custom_pet_name(self):
        """Custom pet name should be used in explanations."""
        explanations = generate_explanations(
            jitter_ratio=JITTER_CALM_THRESHOLD - 0.1,
            volatility_ratio=0.5,
            is_stop_event=False,
            stop_duration_sec=None,
            busyness_pct=None,
            busyness_delta=None,
            weather_condition=None,
            pet_name="Max",
        )
        assert any("Max" in e for e in explanations)

    def test_max_three_explanations(self):
        """Should return at most 3 explanations."""
        explanations = generate_explanations(
            jitter_ratio=JITTER_ACTIVE_THRESHOLD + 1,
            volatility_ratio=VOLATILITY_ERRATIC_THRESHOLD + 1,
            is_stop_event=False,
            stop_duration_sec=None,
            busyness_pct=BUSYNESS_BUSY_THRESHOLD + 10,
            busyness_delta=30,
            weather_condition="Rain",
            pet_name="Pepper",
        )
        assert len(explanations) <= 3

    def test_always_at_least_one_explanation(self):
        """Should always return at least one explanation."""
        explanations = generate_explanations(
            jitter_ratio=None,
            volatility_ratio=None,
            is_stop_event=False,
            stop_duration_sec=None,
            busyness_pct=None,
            busyness_delta=None,
            weather_condition=None,
            pet_name="Pepper",
        )
        assert len(explanations) >= 1
