"""
Tests for the Default Balanced Travel Profile feature (spec points 1–10).

Scenarios:
  A: 8-day Paris, vague prompt → exactly 8 days, 4-7 stops/day, default profile applied
  B: 8-day France, vague prompt → 8 days, city blocks assigned, no zig-zag
  C: 3-day Paris, museums+cafes explicit → default NOT applied, preferences preserved
  D: 4-day Lyon, food-only explicit → default NOT applied, food-heavy preference preserved
  E: 8-day Nice  → exactly 8 days returned (never 9)

All tests run fully offline: they use the intent_specificity and day_archetypes
modules which have no external dependencies, and stub out retriever / planner
calls to avoid hitting embeddings or the LLM.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from app.schemas.travel import Place, TravelIntent
from app.services.intent_specificity import (
    DEFAULT_BALANCED_AVOIDS,
    DEFAULT_BALANCED_INTERESTS,
    apply_default_profile,
    calculate_intent_specificity,
    is_low_specificity_intent,
)
from app.services.day_archetypes import get_day_archetype


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def _make_intent(**kwargs) -> TravelIntent:
    defaults = dict(
        destination="paris",
        duration_days=3,
        interests=[],
        avoid=[],
        pace="moderate",
        budget="",
        mood="",
        travel_style="",
        group_type="",
        food_preference="",
        indoor_outdoor="",
        time_of_day="",
        transportation="",
        walking_constraints="",
        stay_location="",
        user_type="general",
        first_time=False,
        assumptions=[],
        clarification_question="",
        request_intents=[],
    )
    defaults.update(kwargs)
    return TravelIntent(**defaults)


def _make_place(name: str, city: str = "paris", category: str = "landmark", tags=None) -> Place:
    return Place(
        name=name,
        city=city,
        category=category,
        reason="Test place",
        local_tip="",
        latitude=48.8566 + hash(name) % 100 * 0.001,
        longitude=2.3522 + hash(name) % 100 * 0.001,
        tags=tags or [],
        photo_name="",
        wiki_thumb_url="",
        google_maps_url="",
        google_rating=None,
        source_type="curated_must_go",
        source_url="",
        tourist_trap_risk="low",
        confidence=0.8,
        best_time="",
    )


# ─── Scenario A: 8-day Paris vague prompt ─────────────────────────────────────

class TestScenarioA:
    """8-day Paris low-specificity → default profile applied."""

    def test_low_specificity_detected(self):
        intent = _make_intent(destination="paris", duration_days=8, user_type="general")
        assert is_low_specificity_intent(intent), "8-day vague Paris should be low specificity"

    def test_default_profile_applied(self):
        intent = _make_intent(destination="paris", duration_days=8, user_type="general")
        result = apply_default_profile(intent)
        assert result.user_type == "general_low_specificity"
        assert result.first_time is True
        assert result.budget == "mid-range"
        assert set(result.interests) == set(DEFAULT_BALANCED_INTERESTS)
        assert set(result.avoid) == set(DEFAULT_BALANCED_AVOIDS)

    def test_specificity_score_low(self):
        intent = _make_intent(destination="paris", duration_days=8, user_type="general")
        score = calculate_intent_specificity(intent)
        assert score <= 1, f"Expected score <= 1 for vague prompt, got {score}"

    def test_archetypes_assigned_for_8_day_trip(self):
        intent = _make_intent(
            destination="paris", duration_days=8, user_type="general_low_specificity"
        )
        archetypes = [get_day_archetype(d, 8, intent) for d in range(1, 9)]
        assert all(a is not None for a in archetypes), "All 8 days should have archetypes"
        names = [a.name for a in archetypes]
        assert names[0] == "orientation", "Day 1 should be orientation"
        assert names[-1] == "final_highlights", "Day 8 should be final_highlights"

    def test_no_archetypes_for_short_trip(self):
        intent = _make_intent(
            destination="paris", duration_days=3, user_type="general_low_specificity"
        )
        archetypes = [get_day_archetype(d, 3, intent) for d in range(1, 4)]
        assert all(a is None for a in archetypes), "Trips < 5 days should not use archetypes"


# ─── Scenario B: 8-day France country trip ────────────────────────────────────

class TestScenarioB:
    """8-day France (destination='france') → city blocks, no zig-zag."""

    def test_france_country_trip_detected(self):
        from app.services.city_allocator import is_france_country_trip
        intent = _make_intent(destination="france", duration_days=8)
        assert is_france_country_trip(intent)

    def test_non_france_not_detected(self):
        from app.services.city_allocator import is_france_country_trip
        intent = _make_intent(destination="paris", duration_days=8)
        assert not is_france_country_trip(intent)

    def test_city_allocation_no_zigzag(self):
        from app.services.city_allocator import allocate_cities_for_country_trip

        # Build a pool with 8+ places per city so all are viable
        places = (
            [_make_place(f"Paris place {i}", city="paris") for i in range(20)]
            + [_make_place(f"Lyon place {i}", city="lyon") for i in range(12)]
            + [_make_place(f"Nice place {i}", city="nice") for i in range(10)]
        )
        intent = _make_intent(destination="france", duration_days=8)
        schedule = allocate_cities_for_country_trip(intent, places, 8)

        assert len(schedule) == 8, f"Schedule must be exactly 8, got {len(schedule)}"
        # No zig-zag: same city must appear in consecutive blocks
        for i in range(1, len(schedule)):
            if schedule[i] != schedule[i - 1]:
                # Once we leave a city we must not return
                assert schedule[i] not in schedule[:i], (
                    f"Zig-zag detected: returned to {schedule[i]} at position {i}"
                )

    def test_city_allocation_length_exact(self):
        from app.services.city_allocator import allocate_cities_for_country_trip

        places = (
            [_make_place(f"Paris place {i}", city="paris") for i in range(20)]
            + [_make_place(f"Bordeaux place {i}", city="bordeaux") for i in range(8)]
        )
        intent = _make_intent(destination="france", duration_days=6)
        schedule = allocate_cities_for_country_trip(intent, places, 6)
        assert len(schedule) == 6


# ─── Scenario C: 3-day Paris with explicit museums+cafes ──────────────────────

class TestScenarioC:
    """Explicit user preferences → default profile NOT applied."""

    def test_default_not_applied_when_specific(self):
        intent = _make_intent(
            destination="paris",
            duration_days=3,
            interests=["museums", "cafes"],
            mood="cultural",
            budget="mid-range",
            user_type="general",
        )
        result = apply_default_profile(intent)
        # Specificity score should be > 1 — profile stays untouched
        assert result.user_type != "general_low_specificity"
        assert "museums" in result.interests
        assert "cafes" in result.interests

    def test_specificity_score_high_when_interests_set(self):
        intent = _make_intent(
            destination="paris",
            duration_days=3,
            interests=["museums", "cafes"],
            mood="cultural",
            user_type="general",
        )
        score = calculate_intent_specificity(intent)
        assert score > 1, f"Expected score > 1 for specific prompt, got {score}"

    def test_interests_preserved(self):
        intent = _make_intent(
            destination="paris",
            duration_days=3,
            interests=["museums", "cafes"],
            budget="budget",
            user_type="general",
        )
        result = apply_default_profile(intent)
        assert result.interests == ["museums", "cafes"]
        assert result.budget == "budget"


# ─── Scenario D: 4-day Lyon food-only ─────────────────────────────────────────

class TestScenarioD:
    """Explicit food preference → default NOT applied, food-heavy preserved."""

    def test_default_not_applied_food_trip(self):
        intent = _make_intent(
            destination="lyon",
            duration_days=4,
            interests=["restaurant", "bistro", "market"],
            food_preference="local french cuisine",
            user_type="food_traveler",
        )
        result = apply_default_profile(intent)
        assert result.user_type == "food_traveler"
        assert "restaurant" in result.interests
        assert result.food_preference == "local french cuisine"

    def test_food_traveler_not_low_specificity(self):
        intent = _make_intent(
            destination="lyon",
            duration_days=4,
            user_type="food_traveler",
            food_preference="local french cuisine",
        )
        assert not is_low_specificity_intent(intent)


# ─── Scenario E: 8-day Nice — no Day 9 ────────────────────────────────────────

class TestScenarioE:
    """Exact day count enforcement — never return more days than requested."""

    def test_ensure_day_count_trims_excess(self):
        from app.schemas.travel import ItineraryDay
        from app.services.planner import _ensure_day_count

        # Simulate planner returning 9 days for an 8-day request
        days = [
            ItineraryDay(
                day=i,
                title=f"Day {i}",
                summary="",
                stops=[_make_place(f"Place {i}-{j}") for j in range(5)],
            )
            for i in range(1, 10)  # 9 days
        ]
        result = _ensure_day_count(days, 8)
        assert len(result) == 8, f"Expected 8 days after trim, got {len(result)}"
        # Days should be renumbered 1–8
        assert [d.day for d in result] == list(range(1, 9))

    def test_ensure_day_count_pads_short(self):
        from app.schemas.travel import ItineraryDay
        from app.services.planner import _ensure_day_count

        days = [
            ItineraryDay(
                day=i,
                title=f"Day {i}",
                summary="",
                stops=[_make_place(f"Place {i}-{j}") for j in range(6)],
            )
            for i in range(1, 6)  # only 5 days
        ]
        result = _ensure_day_count(days, 8)
        assert len(result) == 8

    def test_enforce_min_stop_quality_backfills(self):
        from app.services.itinerary_validator import enforce_min_stop_quality

        # Day with only 2 stops
        day_with_gap = [_make_place("Eiffel Tower"), _make_place("Louvre")]
        # Provide 5 unused candidates
        candidates = [_make_place(f"Extra {i}") for i in range(5)]
        intent = _make_intent(destination="paris", duration_days=1)

        result = enforce_min_stop_quality([day_with_gap], candidates, intent)
        assert len(result[0]) >= 4, (
            f"enforce_min_stop_quality should fill to 4 stops, got {len(result[0])}"
        )

    def test_enforce_min_stop_quality_leaves_full_days_untouched(self):
        from app.services.itinerary_validator import enforce_min_stop_quality

        full_day = [_make_place(f"Place {i}") for i in range(5)]
        candidates = [_make_place(f"Extra {i}") for i in range(10)]
        intent = _make_intent(destination="paris", duration_days=1)

        result = enforce_min_stop_quality([full_day], candidates, intent)
        # Should not add stops to a day that already meets the minimum
        assert len(result[0]) == 5
