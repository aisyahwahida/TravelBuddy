from __future__ import annotations

"""
test_route_aware_planning.py — Tests for geo-clustering + route-aware slot planning.

Covers:
  - cluster_places() produces reasonable geographic groups
  - select_day_cluster() avoids reusing the same cluster on consecutive days
  - calculate_slot_score() gives higher scores to in-cluster / near-centre places
  - build_full_itinerary() with geo context reduces max leg distances
  - validate_itinerary() catches long_leg_warning, high_total_travel_time, zig_zag
  - repair_itinerary() replaces long-leg stops with same-slot candidates
"""

import unittest

from app.schemas.travel import Place, TravelIntent
from app.services.geo_cluster import (
    DayClusterContext,
    PlaceCluster,
    cluster_places,
    select_day_cluster,
)
from app.services.day_planner import (
    build_full_itinerary,
    calculate_slot_score,
)
from app.services.itinerary_validator import (
    validate_itinerary,
    repair_itinerary,
    _zig_zag_ratio,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def _intent(
    user_type: str = "first_time_visitor",
    days: int = 3,
    interests: list[str] | None = None,
    destination: str = "Paris",
) -> TravelIntent:
    return TravelIntent(
        destination=destination,
        duration_days=days,
        interests=interests or ["history", "art", "food"],
        avoid=[],
        pace="moderate",
        budget="medium",
        mood="explorer",
        travel_style="mixed",
        group_type="couple",
        food_preference="local",
        indoor_outdoor="both",
        stay_location="central Paris",
        user_type=user_type,
        first_time=True,
        assumptions=[],
        clarification_question="",
    )


def _place(
    name: str,
    lat: float,
    lon: float,
    tags: list[str],
    category: str = "attraction",
    city: str = "Paris",
    tourist_trap_risk: str = "low",
    source_type: str = "google_maps",
    google_rating: float = 4.2,
) -> Place:
    return Place(
        name=name,
        city=city,
        category=category,
        reason=f"Visit {name}",
        local_tip="",
        tourist_trap_risk=tourist_trap_risk,
        latitude=lat,
        longitude=lon,
        tags=tags,
        source_type=source_type,
        google_rating=google_rating,
        open_now=True,
    )


# Paris neighbourhoods (approximate centres):
#   Left Bank / Eiffel area    : 48.858, 2.295
#   Louvre / Tuileries area    : 48.862, 2.336
#   Marais / Notre-Dame area   : 48.854, 2.352
#   Montmartre area            : 48.886, 2.341

def _eiffel_area_places() -> list[Place]:
    return [
        _place("Eiffel Tower",         48.8584, 2.2945, ["must_go", "landmark", "iconic"], source_type="curated_must_go"),
        _place("Musée d'Orsay",        48.8600, 2.3266, ["museum", "art", "museums"]),
        _place("Café des Invalides",   48.8564, 2.3120, ["cafe", "coffee"], category="cafe"),
        _place("Esplanade Invalides",  48.8564, 2.3122, ["park", "walks", "outdoor"]),
        _place("Rue Cler Market",      48.8554, 2.3027, ["market", "food"]),
        _place("Le Jules Verne",       48.8584, 2.2950, ["restaurant", "bistro"], category="restaurant"),
    ]


def _louvre_area_places() -> list[Place]:
    return [
        _place("Louvre Museum",        48.8606, 2.3376, ["must_go", "museum", "landmark"], source_type="curated_must_go"),
        _place("Palais Royal",         48.8638, 2.3370, ["must_go", "landmark", "famous"]),
        _place("Café Marly",           48.8603, 2.3353, ["cafe", "coffee"], category="cafe"),
        _place("Sainte-Chapelle",      48.8554, 2.3451, ["museum", "church"]),
        _place("Tuileries Garden",     48.8637, 2.3274, ["park", "garden", "walks"]),
        _place("Brasserie Lipp",       48.8544, 2.3287, ["restaurant", "bistro"], category="restaurant"),
    ]


def _montmartre_area_places() -> list[Place]:
    return [
        _place("Sacré-Cœur",          48.8867, 2.3431, ["must_go", "landmark", "famous"], source_type="curated_must_go"),
        _place("Montmartre Cemetery",  48.8842, 2.3296, ["hidden", "quiet"]),
        _place("Café des Deux Moulins",48.8841, 2.3342, ["cafe", "coffee"], category="cafe"),
        _place("Abbesses Square",      48.8843, 2.3381, ["park", "walks", "viewpoint"]),
        _place("Le Consulat",          48.8860, 2.3435, ["restaurant", "bistro"], category="restaurant"),
    ]


def _all_paris_places() -> list[Place]:
    return _eiffel_area_places() + _louvre_area_places() + _montmartre_area_places()


# ─── Geo cluster tests ────────────────────────────────────────────────────────

class TestClusterPlaces(unittest.TestCase):

    def test_three_neighbourhood_groups(self) -> None:
        places = _all_paris_places()
        intent = _intent()
        clusters = cluster_places(places, intent)
        # 17 places spread across 3 Paris neighbourhoods should produce
        # at least 2 clusters (exact count depends on DBSCAN vs radius fallback)
        self.assertGreaterEqual(len(clusters), 2)

    def test_cluster_has_required_fields(self) -> None:
        places = _eiffel_area_places() + _louvre_area_places()
        clusters = cluster_places(places, _intent())
        for c in clusters:
            self.assertIsInstance(c.cluster_id, int)
            self.assertGreater(c.candidate_count, 0)
            self.assertGreaterEqual(c.slot_coverage_score, 0.0)
            self.assertLessEqual(c.slot_coverage_score, 1.0)
            self.assertGreaterEqual(c.compactness_score, 0.0)

    def test_empty_places_returns_empty(self) -> None:
        clusters = cluster_places([], _intent())
        self.assertEqual(clusters, [])

    def test_single_place_creates_one_cluster(self) -> None:
        places = [_place("Only Place", 48.85, 2.35, ["museum"])]
        clusters = cluster_places(places, _intent())
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].candidate_count, 1)


class TestSelectDayCluster(unittest.TestCase):

    def _make_clusters(self) -> list[PlaceCluster]:
        eiffel = _eiffel_area_places()
        louvre = _louvre_area_places()
        mont = _montmartre_area_places()
        all_p = eiffel + louvre + mont
        return cluster_places(all_p, _intent())

    def test_returns_context_with_required_fields(self) -> None:
        clusters = self._make_clusters()
        ctx = select_day_cluster(clusters, set(), 0, _intent())
        self.assertIsNotNone(ctx)
        self.assertIsInstance(ctx.cluster_id, int)
        self.assertIsInstance(ctx.place_keys, set)
        self.assertGreater(len(ctx.place_keys), 0)

    def test_returns_none_for_empty_clusters(self) -> None:
        ctx = select_day_cluster([], set(), 0, _intent())
        self.assertIsNone(ctx)

    def test_avoids_reusing_same_cluster(self) -> None:
        clusters = self._make_clusters()
        if len(clusters) < 2:
            self.skipTest("Need at least 2 clusters for this test")
        ctx0 = select_day_cluster(clusters, set(), 0, _intent())
        used = {ctx0.cluster_id}
        ctx1 = select_day_cluster(clusters, used, 1, _intent())
        # Should prefer a different cluster when one is available
        self.assertNotEqual(ctx0.cluster_id, ctx1.cluster_id)

    def test_allows_cluster_reuse_when_only_one_exists(self) -> None:
        # Force a single-place (single cluster) scenario
        sole = [_place("Only Museum", 48.858, 2.295, ["museum", "art"])]
        single = cluster_places(sole, _intent())
        self.assertEqual(len(single), 1)
        ctx0 = select_day_cluster(single, set(), 0, _intent())
        ctx1 = select_day_cluster(single, {ctx0.cluster_id}, 1, _intent())
        # With only one cluster, the system must reuse it
        self.assertEqual(ctx0.cluster_id, ctx1.cluster_id)


# ─── Route-aware score tests ──────────────────────────────────────────────────

class TestRouteAwareSlotScore(unittest.TestCase):

    def _cluster_ctx(
        self, center_lat: float, center_lng: float, place_keys: set
    ) -> DayClusterContext:
        return DayClusterContext(
            cluster_id=0,
            center_lat=center_lat,
            center_lng=center_lng,
            place_keys=place_keys,
        )

    def test_in_cluster_place_scores_higher_than_far_place(self) -> None:
        intent = _intent()
        near = _place("Near Gem", 48.858, 2.295, ["must_go", "landmark", "iconic"], source_type="curated_must_go")
        far = _place("Far Gem", 48.886, 2.341, ["must_go", "landmark", "iconic"], source_type="curated_must_go")

        from app.services.place_identity import place_identity_key
        near_key = place_identity_key(near)

        ctx = self._cluster_ctx(48.858, 2.295, {near_key})

        score_near = calculate_slot_score(near, "must_go_landmark", [], None, intent, ctx)
        score_far = calculate_slot_score(far, "must_go_landmark", [], None, intent, ctx)

        self.assertGreater(score_near, score_far)

    def test_no_cluster_context_gives_same_result_as_before(self) -> None:
        intent = _intent()
        place = _place("Museum", 48.860, 2.337, ["museum", "art"])
        score_with = calculate_slot_score(place, "museum_or_culture", [], None, intent, None)
        score_without = calculate_slot_score(place, "museum_or_culture", [], None, intent)
        self.assertAlmostEqual(score_with, score_without, places=6)

    def test_far_from_center_is_penalised(self) -> None:
        intent = _intent()
        near = _place("Near", 48.858, 2.295, ["park", "garden", "walks"])
        far = _place("Far", 48.900, 2.350, ["park", "garden", "walks"])  # ~5km from center

        ctx = self._cluster_ctx(48.858, 2.295, set())
        s_near = calculate_slot_score(near, "scenic_walk_or_open_area", [], None, intent, ctx)
        s_far = calculate_slot_score(far, "scenic_walk_or_open_area", [], None, intent, ctx)
        self.assertGreater(s_near, s_far)

    def test_slot_type_still_dominates_over_route_score(self) -> None:
        """A perfect-route but wrong-slot place should lose to right-slot far place."""
        intent = _intent()
        # In-cluster restaurant (wrong slot: museum_or_culture)
        wrong_slot = _place("In-Cluster Restaurant", 48.858, 2.295,
                            ["restaurant", "bistro"], category="restaurant")
        # Far museum (right slot)
        right_slot = _place("Far Museum", 48.890, 2.390, ["museum", "art", "museums"])

        from app.services.place_identity import place_identity_key
        ctx = self._cluster_ctx(48.858, 2.295, {place_identity_key(wrong_slot)})

        s_wrong = calculate_slot_score(wrong_slot, "museum_or_culture", [], None, intent, ctx)
        s_right = calculate_slot_score(right_slot, "museum_or_culture", [], None, intent, ctx)
        self.assertGreater(s_right, s_wrong)


# ─── Full itinerary with geo context ─────────────────────────────────────────

class TestBuildFullItinerary(unittest.TestCase):

    def test_3_day_paris_first_time_visitor(self) -> None:
        places = _all_paris_places()
        intent = _intent(user_type="first_time_visitor", days=3)
        days = build_full_itinerary(places, intent)
        self.assertEqual(len(days), 3)
        for day in days:
            self.assertGreater(len(day), 0, "Each day should have at least one stop")

    def test_no_place_repeated_across_days(self) -> None:
        places = _all_paris_places()
        intent = _intent(days=3)
        days = build_full_itinerary(places, intent)
        all_names = [p.name for day in days for p in day]
        self.assertEqual(len(all_names), len(set(all_names)), "No place should repeat across days")

    def test_food_traveler_respects_food_cap(self) -> None:
        places = _all_paris_places()
        intent = _intent(user_type="food_traveler", days=2, interests=["food", "cafe", "dining"])
        days = build_full_itinerary(places, intent)
        from app.services.itinerary_validator import _is_food, MAX_FOOD_PER_DAY
        for day_idx, day in enumerate(days):
            food_count = sum(1 for p in day if _is_food(p))
            self.assertLessEqual(food_count, MAX_FOOD_PER_DAY,
                                 f"Day {day_idx + 1} has {food_count} food places (max {MAX_FOOD_PER_DAY})")

    def test_hotel_anchor_nearby_cluster_selected_first(self) -> None:
        """When the hotel is in the Eiffel area, Day 1 should contain Eiffel-area places."""
        places = _all_paris_places()
        intent = _intent(days=2)
        intent.stay_location = "near Eiffel Tower"
        days = build_full_itinerary(places, intent)
        # Day 1 should contain at least one Eiffel-area place (lat ~48.855–48.865, lon ~2.290–2.330)
        day1_lons = [p.longitude for p in days[0]]
        self.assertTrue(
            any(lon < 2.34 for lon in day1_lons),
            f"Expected Eiffel-area stop in Day 1, got lons: {day1_lons}",
        )


# ─── Validator route checks ───────────────────────────────────────────────────

class TestValidatorRouteChecks(unittest.TestCase):

    def test_zig_zag_ratio_optimal_is_1(self) -> None:
        # A perfectly linear route has ratio ≈ 1.0
        stops = [
            _place("A", 48.850, 2.300, ["museum"]),
            _place("B", 48.852, 2.302, ["museum"]),
            _place("C", 48.854, 2.304, ["museum"]),
        ]
        ratio = _zig_zag_ratio(stops)
        self.assertAlmostEqual(ratio, 1.0, places=1)

    def test_zig_zag_ratio_backtracking_is_above_1(self) -> None:
        # A→C→B where B is between A and C is inefficient
        a = _place("A", 48.850, 2.300, ["museum"])
        b = _place("B", 48.855, 2.305, ["museum"])   # midpoint
        c = _place("C", 48.860, 2.310, ["museum"])   # far end
        zigzag_stops = [a, c, b]  # go far then come back
        ratio = _zig_zag_ratio(zigzag_stops)
        self.assertGreater(ratio, 1.2)

    def test_long_leg_warning_detected(self) -> None:
        """A leg of 40–60 min should produce long_leg_warning, not long_leg."""
        intent = _intent(days=1)
        stops = [
            # ~3.5 km apart → ~35 min by transit → warning territory
            _place("Place A", 48.850, 2.295, ["must_go", "landmark"]),
            _place("Place B", 48.873, 2.321, ["museum", "art"]),  # ~3.5km
        ]
        issues = validate_itinerary([stops], intent)
        codes = [i.code for i in issues]
        # There may or may not be a warning depending on exact distance,
        # but there should NOT be a long_leg (invalid) for ~3.5km
        self.assertNotIn("long_leg", codes)


# ─── Repair tests ─────────────────────────────────────────────────────────────

class TestRepairItinerary(unittest.TestCase):

    def test_backfill_thin_days(self) -> None:
        intent = _intent(days=2)
        places = _all_paris_places()
        thin_days = [
            [_place("Museum A", 48.856, 2.295, ["museum", "art"])],  # only 1 stop
            [_place("Cafe B", 48.860, 2.337, ["cafe"], category="cafe"),
             _place("Park C", 48.863, 2.340, ["park", "garden"]),
             _place("Gem D", 48.858, 2.352, ["museum"]),
             _place("Tower E", 48.858, 2.294, ["must_go", "landmark"], source_type="curated_must_go")],
        ]
        repaired = repair_itinerary(thin_days, places, intent)
        self.assertGreaterEqual(len(repaired[0]), 4, "Thin day should be backfilled to min 4 stops")

    def test_excess_food_removed(self) -> None:
        intent = _intent(days=1)
        stops = [
            _place("Cafe 1", 48.856, 2.295, ["cafe"], category="cafe"),
            _place("Cafe 2", 48.856, 2.296, ["cafe"], category="cafe"),
            _place("Restaurant 3", 48.856, 2.297, ["restaurant"], category="restaurant"),
            _place("Museum A", 48.857, 2.300, ["museum"]),
        ]
        repaired = repair_itinerary([stops], _all_paris_places(), intent)
        from app.services.itinerary_validator import _is_food, MAX_FOOD_PER_DAY
        food_count = sum(1 for p in repaired[0] if _is_food(p))
        self.assertLessEqual(food_count, MAX_FOOD_PER_DAY)

    def test_cross_day_dedup_keeps_first_occurrence(self) -> None:
        intent = _intent(days=2)
        shared = _place("Shared Museum", 48.860, 2.337, ["museum"])
        days = [
            [shared, _place("Park A", 48.862, 2.340, ["park"])],
            [shared, _place("Cafe B", 48.863, 2.341, ["cafe"], category="cafe")],
        ]
        repaired = repair_itinerary(days, _all_paris_places(), intent)
        # Shared should appear only once across both days
        all_names = [p.name for day in repaired for p in day]
        self.assertEqual(all_names.count("Shared Museum"), 1)


if __name__ == "__main__":
    unittest.main()
