from __future__ import annotations

"""
intent_specificity.py — Detect low-specificity prompts and apply safe default profiles.

Call order (must be AFTER extract_travel_intent sets user_type):
  calculate_intent_specificity(intent) -> int      0-11 score
  is_low_specificity_intent(intent) -> bool        score <= 1
  apply_default_profile(intent) -> TravelIntent    fills only missing fields
"""

import logging

from app.schemas.travel import TravelIntent

logger = logging.getLogger(__name__)

# Interests the extractor injects when nothing was explicitly stated.
_AUTO_INTERESTS: frozenset[str] = frozenset(
    ["mixed", "walks", "museum", "parks", "cafes", "market", "restaurant"]
)

# Default avoid that is auto-added without explicit user mention.
_AUTO_AVOIDS: frozenset[str] = frozenset(["tourist traps"])

# Balanced interests for low-specificity prompts — mapped to real tags in the dataset.
DEFAULT_BALANCED_INTERESTS: list[str] = [
    "landmarks",
    "walks",
    "museum",
    "cafes",
    "market",
    "parks",
    "restaurant",
]

DEFAULT_BALANCED_AVOIDS: list[str] = [
    "tourist traps",
    "overcrowded restaurants",
]


def calculate_intent_specificity(intent: TravelIntent) -> int:
    """
    Return an 0-11 score representing how much the user told us.
    Higher = more specific preferences.

    Must be called AFTER user_type classification (extractor.extract_travel_intent).
    """
    score = 0

    if intent.duration_days > 1:
        score += 1          # user mentioned an explicit length

    if intent.mood:
        score += 1          # "romantic", "cultural", "foodie" etc.

    if intent.budget:
        score += 1          # "budget", "luxury", "mid-range"

    if intent.travel_style:
        score += 1          # "solo", "couple", "local-first" etc.

    if intent.food_preference:
        score += 1          # "french", "japanese" etc.

    if intent.indoor_outdoor:
        score += 1          # "indoor", "outdoor", "mixed"

    if intent.stay_location:
        score += 1          # user told us their hotel/area

    if intent.group_type:
        score += 1          # "solo", "family", "friends"

    # Strong user-type signals (not the generic "general" fallback)
    if intent.user_type not in {"general", "general_low_specificity", ""}:
        score += 2

    # Avoids beyond the auto-injected "tourist traps"
    explicit_avoids = [a for a in intent.avoid if a.lower() not in _AUTO_AVOIDS]
    if explicit_avoids:
        score += 1

    # Explicit pace ("balanced" is the silent default — slow/fast are explicit)
    if intent.pace in {"slow", "fast"}:
        score += 1

    return score


def is_low_specificity_intent(intent: TravelIntent) -> bool:
    """Return True when the prompt was too general to personalise meaningfully."""
    return calculate_intent_specificity(intent) <= 1


def apply_default_profile(intent: TravelIntent) -> TravelIntent:
    """
    Fill in safe balanced defaults for low-specificity prompts.
    Only touches fields the user did NOT explicitly set.
    Returns a new TravelIntent (no in-place mutation).
    """
    if not is_low_specificity_intent(intent):
        return intent

    updates: dict = {}
    assumptions: list[str] = list(intent.assumptions)

    # user_type → general_low_specificity
    if intent.user_type in {"general", ""}:
        updates["user_type"] = "general_low_specificity"

    # first_time → True (safe default when we know nothing about the traveller)
    if not intent.first_time:
        updates["first_time"] = True

    # budget → mid-range
    if not intent.budget:
        updates["budget"] = "mid-range"
        assumptions.append("Assumed mid-range budget.")

    # interests → replace auto-generated default with a balanced set
    current_set = frozenset(i.lower() for i in intent.interests)
    if not (current_set - _AUTO_INTERESTS):
        updates["interests"] = DEFAULT_BALANCED_INTERESTS
        assumptions.append(
            "Applied a balanced default mix (landmarks, culture, food, scenic walks)."
        )

    # avoid → use balanced defaults when user gave no specific avoidances
    explicit_avoids = [a for a in intent.avoid if a.lower() not in _AUTO_AVOIDS]
    if not explicit_avoids:
        updates["avoid"] = DEFAULT_BALANCED_AVOIDS

    updates["assumptions"] = assumptions

    result = intent.model_copy(update=updates)
    logger.info(
        "Low-specificity prompt (score=%d) → default balanced profile applied: "
        "user_type=%s, budget=%s, interests=%s",
        calculate_intent_specificity(intent),
        result.user_type,
        result.budget,
        result.interests,
    )
    return result
