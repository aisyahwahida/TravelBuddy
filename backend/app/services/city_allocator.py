from __future__ import annotations

"""
city_allocator.py — City-block allocation for France-wide general itineraries.

Prevents random city zig-zagging by assigning days to city blocks BEFORE the
slot-level day planner runs. Only activates when destination == "france" and
the prompt is general / low-specificity.

Public API:
  is_france_country_trip(intent) -> bool
  allocate_cities_for_country_trip(intent, places, duration_days) -> list[str]
  build_city_day_blocks(places) -> dict[str, list[Place]]
"""

import logging

from app.schemas.travel import Place, TravelIntent

logger = logging.getLogger(__name__)

# Minimum candidates a city must have to receive day assignments.
MIN_PLACES_FOR_CITY = 4

# Priority order for France road trips (most data-rich cities first).
_FRANCE_CITY_PRIORITY: list[str] = [
    "paris",
    "lyon",
    "nice",
    "marseille",
    "bordeaux",
    "strasbourg",
    "lille",
    "nantes",
    "cannes",
    "antibes",
]

# Geographic travel groups — cities that naturally sit near each other.
# Used to order blocks so nearby cities are adjacent in the schedule.
_GEO_GROUPS: list[list[str]] = [
    ["paris"],
    ["strasbourg", "colmar"],
    ["lyon"],
    ["marseille", "nice", "cannes", "antibes", "villefranche-sur-mer", "menton"],
    ["bordeaux", "biarritz"],
    ["lille"],
    ["nantes"],
]


def _geo_order(city: str) -> int:
    """Group index for geographic adjacency ordering."""
    city_l = city.lower()
    for i, group in enumerate(_GEO_GROUPS):
        if city_l in group:
            return i
    return len(_GEO_GROUPS)


def _priority(city: str) -> int:
    """Lower number = higher priority."""
    try:
        return _FRANCE_CITY_PRIORITY.index(city.lower())
    except ValueError:
        return len(_FRANCE_CITY_PRIORITY)


def is_france_country_trip(intent: TravelIntent) -> bool:
    """Return True when the intent covers all of France (not a single city)."""
    return intent.destination.strip().lower() == "france"


def allocate_cities_for_country_trip(
    intent: TravelIntent,
    places: list[Place],
    duration_days: int,
) -> list[str]:
    """
    Return an ordered list (length == duration_days) of city names for each day.
    Cities are grouped geographically to eliminate zig-zagging.
    Returns an empty list when the trip is not a France-wide general trip.
    """
    # Count candidates per city
    city_counts: dict[str, int] = {}
    for p in places:
        city = p.city.lower()
        city_counts[city] = city_counts.get(city, 0) + 1

    viable = {c: n for c, n in city_counts.items() if n >= MIN_PLACES_FOR_CITY}
    if not viable:
        logger.warning("city_allocator: no viable cities found (need >= %d places each)", MIN_PLACES_FOR_CITY)
        return []

    # Order cities: by geo-group first, then by priority, then by place count
    ordered_cities = sorted(
        viable.keys(),
        key=lambda c: (_geo_order(c), _priority(c), -viable[c]),
    )

    # Allocate days proportionally to place count
    total = sum(viable.values())
    city_days: dict[str, int] = {}
    for city in ordered_cities:
        share = viable[city] / total
        city_days[city] = max(1, round(share * duration_days))

    # Adjust total to exact duration_days
    while sum(city_days.values()) > duration_days:
        # Remove a day from the lowest-priority city that has > 1 day
        for city in reversed(ordered_cities):
            if city_days.get(city, 0) > 1:
                city_days[city] -= 1
                break
        else:
            break

    while sum(city_days.values()) < duration_days:
        # Add a day to the highest-priority city
        city_days[ordered_cities[0]] = city_days.get(ordered_cities[0], 0) + 1

    # Build schedule: consecutive blocks per city, in geo order
    schedule: list[str] = []
    for city in ordered_cities:
        schedule.extend([city] * city_days.get(city, 0))

    logger.info(
        "City allocation for %d-day France trip: %s",
        duration_days,
        {c: city_days[c] for c in ordered_cities if city_days.get(c, 0) > 0},
    )
    return schedule[:duration_days]


def build_city_day_blocks(places: list[Place]) -> dict[str, list[Place]]:
    """Group places by lowercase city name."""
    blocks: dict[str, list[Place]] = {}
    for p in places:
        city = p.city.lower()
        blocks.setdefault(city, []).append(p)
    return blocks
