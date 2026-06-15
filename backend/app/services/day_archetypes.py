from __future__ import annotations

"""
day_archetypes.py — Day-level archetypes for 5+ day general itineraries.

Archetypes guide slot EMPHASIS (score boosts) but never replace the
deterministic slot-based planner. They are only active when:
  - trip is 5+ days long
  - user_type is "general" or "general_low_specificity"

Public API:
  get_day_archetype(day_number, duration_days, intent) -> DayArchetype | None
  get_archetype_slot_boost(archetype, slot_type) -> float
  apply_archetype_tag_bias(place, archetype) -> float
"""

from dataclasses import dataclass, field
from app.schemas.travel import TravelIntent


@dataclass
class DayArchetype:
    name: str
    label: str
    # Extra score added to the slot_bonus when place matches this slot type
    slot_boosts: dict[str, float] = field(default_factory=dict)
    # Tags that earn a small tag-bias bonus
    preferred_tags: list[str] = field(default_factory=list)


ARCHETYPES: dict[str, DayArchetype] = {
    "orientation": DayArchetype(
        name="orientation",
        label="Arrival & Orientation Day",
        slot_boosts={
            "must_go_landmark": 0.5,
            "scenic_walk_or_open_area": 0.3,
        },
        preferred_tags=["landmark", "neighborhood", "viewpoint", "park", "iconic"],
    ),
    "sightseeing": DayArchetype(
        name="sightseeing",
        label="Must-See Sightseeing Day",
        slot_boosts={
            "must_go_landmark": 1.0,
            "museum_or_culture": 0.3,
        },
        preferred_tags=["must_go", "iconic", "landmark", "famous", "first_time"],
    ),
    "culture_museum": DayArchetype(
        name="culture_museum",
        label="Culture & Museum Day",
        slot_boosts={
            "museum_or_culture": 1.0,
            "hidden_gem": 0.3,
        },
        preferred_tags=["museum", "gallery", "art", "exhibition", "history", "culture"],
    ),
    "local_neighborhood": DayArchetype(
        name="local_neighborhood",
        label="Local Neighborhood Day",
        slot_boosts={
            "hidden_gem": 0.8,
            "local_experience": 0.5,
            "scenic_walk_or_open_area": 0.2,
        },
        preferred_tags=["neighborhood", "quiet", "local", "hidden", "reddit"],
    ),
    "food_market": DayArchetype(
        name="food_market",
        label="Food & Market Day",
        slot_boosts={
            "cafe_or_local_food": 0.5,
            "hidden_gem": 0.3,
        },
        preferred_tags=["market", "food", "bistro", "cafe", "brasserie", "wine"],
    ),
    "scenic_nature": DayArchetype(
        name="scenic_nature",
        label="Scenic & Nature Day",
        slot_boosts={
            "scenic_walk_or_open_area": 1.0,
            "hidden_gem": 0.3,
        },
        preferred_tags=["park", "garden", "viewpoint", "outdoor", "nature", "walk", "views"],
    ),
    "hidden_gems": DayArchetype(
        name="hidden_gems",
        label="Hidden Gems & Relaxed Exploration",
        slot_boosts={
            "hidden_gem": 1.0,
            "local_experience": 0.5,
        },
        preferred_tags=["hidden", "quiet", "local", "off-the-beaten", "reddit", "gems"],
    ),
    "final_highlights": DayArchetype(
        name="final_highlights",
        label="Final Highlights Day",
        slot_boosts={
            "must_go_landmark": 0.3,
            "hidden_gem": 0.3,
            "scenic_walk_or_open_area": 0.3,
        },
        preferred_tags=["landmark", "viewpoint", "iconic", "favorite"],
    ),
}

# Sequence for 5–8 day trips (indices into the 8-archetype list)
_SEQUENCE_8: list[str] = [
    "orientation",
    "sightseeing",
    "culture_museum",
    "local_neighborhood",
    "food_market",
    "scenic_nature",
    "hidden_gems",
    "final_highlights",
]

# Cycling rotation for the middle of longer trips (day 2 through day N-1)
_MIDDLE_CYCLE: list[str] = [
    "sightseeing",
    "culture_museum",
    "local_neighborhood",
    "food_market",
    "scenic_nature",
    "hidden_gems",
]

_GENERAL_USER_TYPES = {"general", "general_low_specificity"}


def get_day_archetype(
    day_number: int,       # 1-based
    duration_days: int,
    intent: TravelIntent,
) -> DayArchetype | None:
    """
    Return the DayArchetype for this day, or None if archetypes are inactive.

    Archetypes are only used for:
    - trips of 5+ days
    - general / low-specificity user profiles
    """
    if duration_days < 5:
        return None
    user_type = getattr(intent, "user_type", "") or "general"
    if user_type not in _GENERAL_USER_TYPES:
        return None

    if duration_days <= 8:
        # Map day proportionally onto the 8-archetype sequence
        idx = round((day_number - 1) * (len(_SEQUENCE_8) - 1) / max(1, duration_days - 1))
        name = _SEQUENCE_8[min(idx, len(_SEQUENCE_8) - 1)]
    else:
        # Longer trips: orientation → middle cycle → final_highlights
        if day_number == 1:
            name = "orientation"
        elif day_number == duration_days:
            name = "final_highlights"
        else:
            mid_idx = (day_number - 2) % len(_MIDDLE_CYCLE)
            name = _MIDDLE_CYCLE[mid_idx]

    return ARCHETYPES.get(name)


def get_archetype_slot_boost(archetype: DayArchetype | None, slot_type: str) -> float:
    """Return extra score to add when place matches this slot type for the archetype."""
    if archetype is None:
        return 0.0
    return archetype.slot_boosts.get(slot_type, 0.0)


def apply_archetype_tag_bias(place_tags: set[str], source_type: str, archetype: DayArchetype | None) -> float:
    """
    Return a small bonus (max +0.4) when the place matches the archetype's preferred tags.
    Kept below the route_score cap (±1.3) and slot_bonus (±3.0).
    """
    if archetype is None:
        return 0.0
    matches = sum(
        1 for tag in archetype.preferred_tags
        if tag in place_tags or tag == source_type
    )
    return min(0.4, matches * 0.15)
