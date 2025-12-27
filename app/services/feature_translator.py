"""
Feature Translation Service for Family Dashboard.

Translates technical behavioral metrics into human-readable descriptions
that are understandable by non-technical family members.
"""

from dataclasses import dataclass
from typing import Literal, Optional

from app.db.models import EnrichedPing, RawPing


@dataclass
class TranslatedFeatures:
    """Human-readable feature translations."""

    # Activity
    activity_label: str
    movement_type: Literal["steady", "active", "playing", "erratic", "frozen"]
    is_stopped: bool
    stop_duration: Optional[int]

    # Environment
    crowding_level: Literal["quiet", "moderate", "busy"]
    weather_description: Optional[str]
    busyness_pct: Optional[float]

    # Explanations
    explanations: list[str]


# Thresholds for feature classification
JITTER_CALM_THRESHOLD = 0.8
JITTER_ACTIVE_THRESHOLD = 1.5
VOLATILITY_ERRATIC_THRESHOLD = 2.0
BUSYNESS_QUIET_THRESHOLD = 30
BUSYNESS_BUSY_THRESHOLD = 60
STOP_LONG_DURATION_SEC = 60


def translate_activity(
    jitter_ratio: Optional[float],
    volatility_ratio: Optional[float],
    is_stop_event: bool,
    stop_duration_sec: Optional[int],
) -> tuple[str, Literal["steady", "active", "playing", "erratic", "frozen"]]:
    """
    Translate movement metrics to human-readable activity label.

    Returns:
        Tuple of (label, movement_type)
    """
    # Stop events take priority
    if is_stop_event:
        if stop_duration_sec and stop_duration_sec > STOP_LONG_DURATION_SEC:
            return "Resting", "frozen"
        return "Paused", "frozen"

    # Check for erratic movement (high direction changes)
    if volatility_ratio and volatility_ratio > VOLATILITY_ERRATIC_THRESHOLD:
        return "Exploring actively", "erratic"

    # Classify by jitter ratio
    if jitter_ratio is None:
        return "Walking", "steady"

    if jitter_ratio < JITTER_CALM_THRESHOLD:
        return "Calm walk", "steady"
    elif jitter_ratio < JITTER_ACTIVE_THRESHOLD:
        return "Active", "active"
    else:
        return "Playing", "playing"


def translate_crowding(busyness_pct: Optional[float]) -> Literal["quiet", "moderate", "busy"]:
    """Translate busyness percentage to crowding level."""
    if busyness_pct is None:
        return "moderate"  # Default assumption

    if busyness_pct < BUSYNESS_QUIET_THRESHOLD:
        return "quiet"
    elif busyness_pct < BUSYNESS_BUSY_THRESHOLD:
        return "moderate"
    else:
        return "busy"


def generate_explanations(
    jitter_ratio: Optional[float],
    volatility_ratio: Optional[float],
    is_stop_event: bool,
    stop_duration_sec: Optional[int],
    busyness_pct: Optional[float],
    busyness_delta: Optional[float],
    weather_condition: Optional[str],
    pet_name: str = "Pepper",
) -> list[str]:
    """
    Generate human-readable explanations for the current status.

    Returns list of 1-3 explanation sentences.
    """
    explanations = []

    # Movement explanation
    if is_stop_event:
        if stop_duration_sec and stop_duration_sec > STOP_LONG_DURATION_SEC:
            explanations.append(
                f"{pet_name} has been still for {stop_duration_sec} seconds."
            )
        else:
            explanations.append(f"{pet_name} has stopped moving.")
    elif jitter_ratio is not None:
        if jitter_ratio < JITTER_CALM_THRESHOLD:
            explanations.append(
                f"{pet_name} is walking steadily with low movement variation."
            )
        elif jitter_ratio < JITTER_ACTIVE_THRESHOLD:
            explanations.append(f"{pet_name} is moving around normally.")
        else:
            explanations.append(f"{pet_name} is very active right now.")

    # Direction changes explanation
    if volatility_ratio and volatility_ratio > VOLATILITY_ERRATIC_THRESHOLD:
        explanations.append(f"{pet_name} is changing direction frequently.")

    # Environment explanation
    if busyness_pct is not None:
        if busyness_pct < BUSYNESS_QUIET_THRESHOLD:
            explanations.append("Few people or dogs nearby.")
        elif busyness_pct > BUSYNESS_BUSY_THRESHOLD:
            explanations.append("Busy area - many people nearby.")
        else:
            explanations.append("Moderate foot traffic in the area.")

    # Busyness trend
    if busyness_delta is not None and abs(busyness_delta) > 20:
        if busyness_delta > 0:
            explanations.append("The area is getting more crowded.")
        else:
            explanations.append("The area is quieting down.")

    # Weather context (only if notable)
    if weather_condition:
        condition_lower = weather_condition.lower()
        if "rain" in condition_lower:
            explanations.append("It's raining in the area.")
        elif "snow" in condition_lower:
            explanations.append("There's snow in the area.")
        elif "storm" in condition_lower or "thunder" in condition_lower:
            explanations.append("Stormy conditions detected.")

    # Ensure at least one explanation
    if not explanations:
        explanations.append(f"{pet_name} is on a walk.")

    return explanations[:3]  # Limit to 3 explanations


def translate_features(
    enriched: EnrichedPing,
    pet_name: str = "Pepper",
) -> TranslatedFeatures:
    """
    Translate all enriched ping features to human-readable format.

    Args:
        enriched: EnrichedPing with all behavioral and environmental data
        pet_name: Name of the pet for personalized messages

    Returns:
        TranslatedFeatures with all human-readable translations
    """
    # Translate activity
    activity_label, movement_type = translate_activity(
        jitter_ratio=enriched.jitter_ratio,
        volatility_ratio=enriched.volatility_ratio,
        is_stop_event=enriched.is_stop_event,
        stop_duration_sec=enriched.stop_duration_sec,
    )

    # Translate crowding
    crowding_level = translate_crowding(enriched.busyness_pct)

    # Generate explanations
    explanations = generate_explanations(
        jitter_ratio=enriched.jitter_ratio,
        volatility_ratio=enriched.volatility_ratio,
        is_stop_event=enriched.is_stop_event,
        stop_duration_sec=enriched.stop_duration_sec,
        busyness_pct=enriched.busyness_pct,
        busyness_delta=enriched.busyness_delta,
        weather_condition=enriched.weather_condition,
        pet_name=pet_name,
    )

    return TranslatedFeatures(
        activity_label=activity_label,
        movement_type=movement_type,
        is_stopped=enriched.is_stop_event,
        stop_duration=enriched.stop_duration_sec,
        crowding_level=crowding_level,
        weather_description=enriched.weather_condition,
        busyness_pct=enriched.busyness_pct,
        explanations=explanations,
    )
