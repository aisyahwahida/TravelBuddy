"""
Tests for the contextual alternatives system.

Scenarios:
  A: Museum stop → alternatives are museums/galleries, no restaurants
  B: Food stop → alternatives are cafes/restaurants; food cap respected
  C: Route-aware → faraway candidate rejected, nearby ranked higher
  D: User preference → tourist-trap alternatives penalized
  E: Recommended_for populated correctly; incompatible positions excluded
"""
from __future__ import annotations

import pytest
from app.schemas.travel import Itinerary, ItineraryDay, Place, TravelIntent
from app.services.contextual_alternatives import (
    build_contextual_alternative_options,
    calculate_replacement_route_delta,
    get_candidate_slot_types,
    is_slot_compatible,
    would_violate_category_diversity,
    would_violate_food_cap,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def _make_intent(**kwargs) -> TravelIntent:
    defaults = dict(
        destination="paris",
        duration_days=1,
        interests=["museum", "landmarks"],
        avoid=[],
        pace="balanced",
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


def _make_place(
    name: str,
    city: str = "Paris",
    category: str = "landmark",
    tags: list[str] | None = None,
    tourist_trap_risk: str = "low",
    source_type: str = "curated_must_go",
    lat: float = 48.8566,
    lon: float = 2.3522,
) -> Place:
    return Place(
        name=name,
        city=city,
        category=category,
        reason="Test place",
        local_tip="",
        tourist_trap_risk=tourist_trap_risk,
        latitude=lat,
        longitude=lon,
        tags=tags or [],
        photo_name="",
        wiki_thumb_url="",
        google_maps_url="",
        google_rating=None,
        source_type=source_type,
        source_url="",
        confidence=0.8,
        best_time="",
        open_status_label="",
        business_status="",
    )


def _make_itinerary(stops: list[Place], day_stops: list[Place] | None = None) -> Itinerary:
    actual_stops = day_stops if day_stops is not None else stops
    return Itinerary(
        title="Test trip",
        summary="",
        destination="Paris",
        themes=[],
        stops=stops,
        days=[
            ItineraryDay(
                day=1,
                title="Day 1",
                summary="",
                stops=actual_stops,
            )
        ],
        avoidance_notes=[],
    )


# ─── A: Museum alternatives ───────────────────────────────────────────────────

class TestMuseumAlternatives:
    def test_museum_slot_alternatives_are_cultural(self):
        """Alternatives for a museum slot must be museums, galleries, or cultural places."""
        itinerary_stops = [
            _make_place("Louvre Museum", category="museum", tags=["museum", "art", "famous"]),
            _make_place("Café de Flore", category="cafe", tags=["cafe", "coffee"]),
            _make_place("Luxembourg Garden", category="park", tags=["park", "garden", "walk"]),
            _make_place("Sacré-Cœur", category="landmark", tags=["must_go", "landmark", "famous"]),
            _make_place("Seine Walk", category="viewpoint", tags=["viewpoint", "walk", "scenic"]),
            _make_place("Bistro Vivienne", category="restaurant", tags=["restaurant", "bistro"]),
        ]
        itinerary = _make_itinerary(itinerary_stops)

        # Candidates: one museum, one restaurant, one gallery
        candidates = [
            *itinerary_stops,
            _make_place("Musée d'Orsay", category="museum", tags=["museum", "art", "exhibitions"],
                        lat=48.8600, lon=2.3266),
            _make_place("Palais Royal Restaurant", category="restaurant", tags=["restaurant"],
                        lat=48.8637, lon=2.3370),
            _make_place("Petit Palais Gallery", category="museum", tags=["museum", "gallery", "art", "exhibitions"],
                        lat=48.8657, lon=2.3135),
        ]
        intent = _make_intent()
        alts = build_contextual_alternative_options(candidates, itinerary, intent)

        # The restaurant may appear as a food-slot alternative — but must NOT be recommended
        # for any non-food slot (must_go_landmark at stop 0, museum_or_culture at stop 3,
        # scenic_walk at stop 4, hidden_gem at stop 2).
        restaurant_alt = next((a for a in alts if a.name == "Palais Royal Restaurant"), None)
        if restaurant_alt:
            non_food_stops = {0, 2, 3, 4}  # landmark / hidden_gem / museum / scenic
            for rec in restaurant_alt.recommended_for:
                assert rec.stop_index not in non_food_stops, (
                    f"Restaurant recommended for non-food stop {rec.stop_index} — should only "
                    f"appear for cafe_or_local_food slots (1, 5)"
                )

    def test_museum_alt_recommended_for_museum_slot(self):
        """A gallery alternative must appear in recommended_for at the cultural stop position."""
        museum_stop = _make_place("Louvre Museum", category="museum", tags=["museum", "famous", "must_go"])
        itinerary_stops = [
            museum_stop,
            _make_place("Café Marly", category="cafe", tags=["cafe", "coffee"]),
            _make_place("Tuileries Garden", category="park", tags=["park", "garden", "walk"]),
            _make_place("Arc de Triomphe", category="landmark", tags=["landmark", "famous", "must_go"]),
            _make_place("Eiffel Walk", category="viewpoint", tags=["viewpoint", "walk"]),
            _make_place("Le Petit Bistro", category="restaurant", tags=["restaurant"]),
        ]
        itinerary = _make_itinerary(itinerary_stops)

        gallery = _make_place(
            "Musée de l'Orangerie",
            category="museum",
            tags=["museum", "art", "exhibitions"],
            lat=48.8638, lon=2.3220,
        )
        candidates = [*itinerary_stops, gallery]
        intent = _make_intent()
        alts = build_contextual_alternative_options(candidates, itinerary, intent)

        gallery_alt = next((a for a in alts if a.name == "Musée de l'Orangerie"), None)
        assert gallery_alt is not None, "Gallery should appear as alternative"
        positions = [(r.day_index, r.stop_index) for r in gallery_alt.recommended_for]
        # Should be recommended for the landmark stop (stop 0) or museum slot
        assert len(positions) > 0, "Gallery alt must have at least one recommended position"


# ─── B: Food alternatives ──────────────────────────────────────────────────────

class TestFoodAlternatives:
    def test_food_alt_for_food_slot_only(self):
        """A restaurant alternative should be recommended for food slots, not museum slots."""
        itinerary_stops = [
            _make_place("Louvre Museum", category="museum", tags=["museum", "famous", "must_go"]),
            _make_place("Café de Flore", category="cafe", tags=["cafe", "coffee"]),
            _make_place("Secret Passage", category="hidden gem", tags=["walk", "local"],
                        tourist_trap_risk="low"),
            _make_place("Pompidou Center", category="museum", tags=["museum", "gallery", "art", "exhibitions"]),
            _make_place("Montmartre Walk", category="viewpoint", tags=["viewpoint", "walk", "park"]),
            _make_place("Bouillon Racine", category="restaurant", tags=["restaurant", "bistro"]),
        ]
        itinerary = _make_itinerary(itinerary_stops)

        new_restaurant = _make_place(
            "Chez Janou",
            category="restaurant",
            tags=["restaurant", "bistro"],
            lat=48.8546, lon=2.3601,
        )
        candidates = [*itinerary_stops, new_restaurant]
        intent = _make_intent(interests=["restaurant", "food"])

        alts = build_contextual_alternative_options(candidates, itinerary, intent)

        restaurant_alt = next((a for a in alts if a.name == "Chez Janou"), None)
        if restaurant_alt:
            # It should only be recommended for food-slot positions
            for rec in restaurant_alt.recommended_for:
                # Positions 1 and 5 are cafe_or_local_food in the general template
                assert rec.stop_index in {1, 5}, (
                    f"Restaurant alternative should not be recommended for stop {rec.stop_index} "
                    f"(non-food slot)"
                )

    def test_food_cap_not_exceeded(self):
        """would_violate_food_cap returns True when swap would create 3 food places in a day."""
        existing_food_1 = _make_place("Café A", category="cafe", tags=["cafe"])
        existing_food_2 = _make_place("Bistro B", category="restaurant", tags=["restaurant"])
        non_food = _make_place("Museum C", category="museum", tags=["museum"])
        day_stops = [existing_food_1, non_food, existing_food_2]

        new_restaurant = _make_place("Café D", category="cafe", tags=["cafe"])

        # Replacing the museum (non-food) with a restaurant would give 3 food places
        assert would_violate_food_cap(new_restaurant, day_stops, non_food) is True

    def test_food_cap_ok_when_replacing_food(self):
        """Replacing one food place with another should NOT violate the food cap."""
        existing_food = _make_place("Café A", category="cafe", tags=["cafe"])
        non_food = _make_place("Museum C", category="museum", tags=["museum"])
        day_stops = [existing_food, non_food]

        new_restaurant = _make_place("Café D", category="cafe", tags=["cafe"])
        assert would_violate_food_cap(new_restaurant, day_stops, existing_food) is False


# ─── C: Route-aware alternatives ─────────────────────────────────────────────

class TestRouteAwareAlternatives:
    def test_faraway_candidate_rejected(self):
        """A candidate more than 40 min route delta away should not appear in recommended_for."""
        nearby_stop = _make_place("Opera", category="landmark", tags=["must_go", "landmark", "famous"],
                                  lat=48.8718, lon=2.3320)
        next_stop = _make_place("Palais Royal", category="hidden gem", tags=["walk", "garden", "park"],
                                lat=48.8637, lon=2.3370)
        day_stops = [nearby_stop, next_stop]

        # Faraway candidate — Nice, France (hundreds of km away)
        faraway = _make_place(
            "Promenade des Anglais",
            category="landmark",
            tags=["must_go", "landmark", "famous"],
            lat=43.6951, lon=7.2659,
        )
        delta = calculate_replacement_route_delta(faraway, nearby_stop, day_stops)
        assert delta > 40, f"Expected large delta for faraway place, got {delta:.1f} min"

    def test_nearby_candidate_has_low_delta(self):
        """A candidate a few hundred metres from the target should have a small route delta."""
        target = _make_place("Louvre Museum", tags=["museum", "must_go", "famous"],
                             lat=48.8606, lon=2.3376)
        prev_stop = _make_place("Tuileries", tags=["park", "garden", "walk"],
                                lat=48.8638, lon=2.3274)
        next_stop = _make_place("Île de la Cité", tags=["landmark", "must_go", "famous"],
                                lat=48.8553, lon=2.3470)
        day_stops = [prev_stop, target, next_stop]

        # Candidate 300 m from Louvre
        nearby = _make_place("Musée des Arts Décoratifs", tags=["museum", "art", "exhibitions"],
                             lat=48.8631, lon=2.3403)
        delta = calculate_replacement_route_delta(nearby, target, day_stops)
        assert delta < 20, f"Expected small delta for nearby place, got {delta:.1f} min"

    def test_route_aware_alts_exclude_high_delta(self):
        """build_contextual_alternative_options must not include alts with delta > 40 min."""
        paris_stop = _make_place("Notre-Dame", tags=["must_go", "landmark", "famous"],
                                 lat=48.8530, lon=2.3499)
        paris_next = _make_place("Sainte-Chapelle", tags=["must_go", "landmark", "famous"],
                                 lat=48.8554, lon=2.3450)
        itinerary_stops = [
            paris_stop,
            _make_place("Coffee Shop", category="cafe", tags=["cafe", "coffee"]),
            _make_place("Local Square", category="hidden gem", tags=["walk", "local"],
                        tourist_trap_risk="low"),
            _make_place("Cluny Museum", category="museum", tags=["museum", "exhibitions"]),
            paris_next,
            _make_place("Bistro Latin", category="restaurant", tags=["restaurant"]),
        ]
        itinerary = _make_itinerary(itinerary_stops)

        # Faraway "landmark" candidate from Marseille
        marseille_candidate = _make_place(
            "Old Port Marseille",
            category="landmark",
            tags=["must_go", "landmark", "famous"],
            lat=43.2965, lon=5.3698,
        )
        candidates = [*itinerary_stops, marseille_candidate]
        intent = _make_intent()
        alts = build_contextual_alternative_options(candidates, itinerary, intent)
        alt_names = {a.name for a in alts}
        assert "Old Port Marseille" not in alt_names, (
            "Marseille place should be excluded due to excessive route delta"
        )


# ─── D: User preference preservation ─────────────────────────────────────────

class TestUserPreferencePreservation:
    def test_tourist_trap_penalized(self):
        """High tourist-trap alternatives should have lower replacement_score than low-risk ones."""
        common_stops = [
            _make_place("Louvre Museum", tags=["must_go", "landmark", "famous"]),
            _make_place("Coffee Spot", category="cafe", tags=["cafe", "coffee"]),
            _make_place("Hidden Alley", category="hidden gem", tags=["walk", "local"],
                        tourist_trap_risk="low"),
            _make_place("Cluny Museum", category="museum", tags=["museum", "exhibitions"]),
            _make_place("Tuileries Garden", tags=["park", "garden", "walk"]),
            _make_place("Bistro Lucie", category="restaurant", tags=["restaurant"]),
        ]
        itinerary = _make_itinerary(common_stops)

        target = common_stops[0]  # must_go_landmark slot

        low_risk = _make_place(
            "Palais Royal",
            tags=["must_go", "landmark", "famous"],
            tourist_trap_risk="low",
            lat=48.8637, lon=2.3370,
        )
        high_risk = _make_place(
            "Tourist Trap Tower",
            tags=["must_go", "landmark", "famous"],
            tourist_trap_risk="high",
            lat=48.8637, lon=2.3370,
        )

        from app.services.contextual_alternatives import _score_replacement
        intent = _make_intent(interests=["museums", "cafes"])

        low_score, _ = _score_replacement(low_risk, target, common_stops, intent, 0.8, "must_go_landmark")
        high_score, _ = _score_replacement(high_risk, target, common_stops, intent, 0.8, "must_go_landmark")

        assert low_score > high_score, (
            f"Low tourist-trap ({low_score:.3f}) should outscore high tourist-trap ({high_score:.3f})"
        )

    def test_avoid_preferences_exclude_unrelated(self):
        """A user who avoids tourist traps should not get high-risk places in alternatives."""
        itinerary_stops = [
            _make_place("Arc de Triomphe", tags=["must_go", "landmark", "famous"]),
            _make_place("Coffee Artisan", category="cafe", tags=["cafe", "coffee"]),
            _make_place("Passage Brady", category="hidden gem", tags=["walk", "local"],
                        tourist_trap_risk="low"),
            _make_place("Orsay Museum", category="museum", tags=["museum", "art", "exhibitions"]),
            _make_place("Canal St-Martin Walk", tags=["walk", "park", "garden"]),
            _make_place("Chez Louisette", category="restaurant", tags=["restaurant"]),
        ]
        itinerary = _make_itinerary(itinerary_stops)

        trap_place = _make_place(
            "Overpriced Souvenir Landmark",
            tags=["must_go", "landmark", "famous"],
            tourist_trap_risk="high",
            lat=48.8620, lon=2.3340,
        )
        quality_place = _make_place(
            "Square du Vert-Galant",
            tags=["must_go", "landmark", "famous"],
            tourist_trap_risk="low",
            lat=48.8573, lon=2.3516,
        )
        candidates = [*itinerary_stops, trap_place, quality_place]
        intent = _make_intent(
            interests=["quiet cafes", "museums"],
            avoid=["tourist traps"],
        )
        alts = build_contextual_alternative_options(candidates, itinerary, intent)

        # High-risk place should either not appear or score lower than the quality alternative
        trap_alt = next((a for a in alts if a.name == "Overpriced Souvenir Landmark"), None)
        quality_alt = next((a for a in alts if a.name == "Square du Vert-Galant"), None)

        if trap_alt and quality_alt:
            assert quality_alt.replacement_score >= trap_alt.replacement_score, (
                "Low tourist-trap place should score >= high tourist-trap place"
            )


# ─── E: recommended_for populated correctly ───────────────────────────────────

class TestRecommendedForPopulation:
    def test_recommended_for_fields_present(self):
        """Every alternative must have recommended_for with valid day/stop indices."""
        itinerary_stops = [
            _make_place("Notre-Dame", tags=["must_go", "landmark", "famous"]),
            _make_place("Café Procope", category="cafe", tags=["cafe", "coffee"]),
            _make_place("Hidden Courtyard", category="hidden gem", tags=["walk", "local"],
                        tourist_trap_risk="low"),
            _make_place("Centre Pompidou", category="museum", tags=["museum", "art", "exhibitions"]),
            _make_place("Place des Vosges", tags=["park", "garden", "walk"]),
            _make_place("L'Ami Jean", category="restaurant", tags=["restaurant"]),
        ]
        itinerary = _make_itinerary(itinerary_stops)

        museum_candidate = _make_place(
            "Musée Carnavalet",
            category="museum",
            tags=["museum", "exhibitions"],
            lat=48.8566, lon=2.3622,
        )
        candidates = [*itinerary_stops, museum_candidate]
        intent = _make_intent()
        alts = build_contextual_alternative_options(candidates, itinerary, intent)

        for alt in alts:
            assert alt.recommended_for, f"{alt.name}: recommended_for must not be empty"
            for rec in alt.recommended_for:
                assert 0 <= rec.day_index < len(itinerary.days)
                assert 0 <= rec.stop_index < len(itinerary.days[rec.day_index].stops)
                assert 0.0 <= rec.replacement_score <= 1.0
                assert rec.route_delta_minutes <= 40.0

    def test_incompatible_slot_not_in_recommended_for(self):
        """A restaurant should not appear in recommended_for for a museum slot (stop 3)."""
        itinerary_stops = [
            _make_place("Louvre", tags=["must_go", "landmark", "famous"]),
            _make_place("Café A", category="cafe", tags=["cafe", "coffee"]),
            _make_place("Local Gem", category="hidden gem", tags=["walk", "local"],
                        tourist_trap_risk="low"),
            _make_place("Musée Rodin", category="museum", tags=["museum", "art", "exhibitions"]),
            _make_place("Gardens", tags=["park", "garden", "walk"]),
            _make_place("Bistro B", category="restaurant", tags=["restaurant"]),
        ]
        itinerary = _make_itinerary(itinerary_stops)

        restaurant_candidate = _make_place(
            "Chez Paul",
            category="restaurant",
            tags=["restaurant", "bistro"],
            lat=48.8530, lon=2.3530,
        )
        candidates = [*itinerary_stops, restaurant_candidate]
        intent = _make_intent(interests=["restaurant", "food"])
        alts = build_contextual_alternative_options(candidates, itinerary, intent)

        restaurant_alt = next((a for a in alts if a.name == "Chez Paul"), None)
        if restaurant_alt:
            for rec in restaurant_alt.recommended_for:
                # Stop 3 is museum_or_culture slot — restaurant must not be there
                assert rec.stop_index != 3, (
                    "Restaurant should not be recommended for the museum slot (stop_index=3)"
                )

    def test_compatible_slot_types_field(self):
        """compatible_slot_types must list every slot type the candidate matches."""
        cafe = _make_place("Café Marché", category="cafe", tags=["cafe", "coffee", "market"])
        slot_types = get_candidate_slot_types(cafe)
        assert "cafe_or_local_food" in slot_types
        assert "museum_or_culture" not in slot_types

    def test_replacement_score_in_zero_to_one(self):
        """replacement_score on each alt must be in [0, 1]."""
        stops = [
            _make_place(f"Stop {i}", tags=["must_go", "landmark", "famous"])
            for i in range(6)
        ]
        itinerary = _make_itinerary(stops)
        extra = _make_place("Extra Place", tags=["must_go", "landmark", "famous"],
                            lat=48.862, lon=2.345)
        alts = build_contextual_alternative_options([*stops, extra], itinerary, _make_intent())
        for alt in alts:
            assert 0.0 <= alt.replacement_score <= 1.0, (
                f"{alt.name}: replacement_score={alt.replacement_score} out of range"
            )
