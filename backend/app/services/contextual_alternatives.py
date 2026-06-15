from __future__ import annotations

"""
contextual_alternatives.py — Slot-aware, route-aware alternative place generation.

Each returned AlternativePlace carries a `recommended_for` list that specifies
which (day_index, stop_index) swaps it is appropriate for, together with a
`replacement_score` and `route_delta_minutes` for each position.

The frontend uses these to:
  - Sort alternative cards by relevance to the currently selected stop.
  - Prevent invalid drops (wrong slot type, food cap, route too long).
  - Show a compatibility score badge on each card.
"""

import logging
import math
from app.schemas.travel import AlternativePlace, Itinerary, Place, RecommendedForItem, TravelIntent
from app.services.closed_places import is_permanently_closed_place
from app.services.day_planner import (
    MAX_FOOD_PER_DAY,
    NON_FOOD_SLOTS,
    _haversine,
    _is_food_place,
    _matches_slot,
    get_day_template,
)

logger = logging.getLogger(__name__)

# Reject a candidate replacement if it adds more than this many minutes to the day route.
MAX_ROUTE_DELTA_MINUTES = 40.0


# ─── Geometry helpers ─────────────────────────────────────────────────────────

def _leg_minutes(km: float) -> float:
    """Estimate travel time in minutes for a single leg (mirrors frontend logic)."""
    if km <= 1.4:
        return max(4.0, (km / 4.8) * 60.0)
    return max(12.0, (km / 18.0) * 60.0 + 8.0)


def _day_centroid(stops: list[Place]) -> tuple[float, float]:
    if not stops:
        return 0.0, 0.0
    return (
        sum(s.latitude for s in stops) / len(stops),
        sum(s.longitude for s in stops) / len(stops),
    )


# ─── Slot helpers ─────────────────────────────────────────────────────────────

def get_candidate_slot_types(place: Place) -> list[str]:
    """Return every slot type this place can fill."""
    all_slots = [
        "must_go_landmark",
        "cafe_or_local_food",
        "hidden_gem",
        "museum_or_culture",
        "scenic_walk_or_open_area",
        "local_experience",
        "family_friendly",
    ]
    return [st for st in all_slots if _matches_slot(place, st)]


def is_slot_compatible(place: Place, slot_type: str) -> bool:
    return _matches_slot(place, slot_type)


# ─── Constraint checkers ──────────────────────────────────────────────────────

def would_violate_food_cap(
    candidate: Place,
    day_stops: list[Place],
    replacing_stop: Place,
) -> bool:
    if not _is_food_place(candidate):
        return False
    current_food = sum(1 for s in day_stops if _is_food_place(s))
    replacing_food = 1 if _is_food_place(replacing_stop) else 0
    new_food_count = current_food - replacing_food + 1
    return new_food_count > MAX_FOOD_PER_DAY


def would_violate_category_diversity(
    candidate: Place,
    day_stops: list[Place],
    replacing_stop: Place,
) -> bool:
    cat = candidate.category.lower()
    count = sum(1 for s in day_stops if s.category.lower() == cat)
    replacing_same = 1 if replacing_stop.category.lower() == cat else 0
    new_count = count - replacing_same + 1
    return new_count > 2


# ─── Route scoring ────────────────────────────────────────────────────────────

def calculate_replacement_route_delta(
    candidate: Place,
    target_stop: Place,
    day_stops: list[Place],
) -> float:
    """
    Return the estimated change in travel time (minutes) when replacing
    target_stop with candidate.  Negative means candidate is closer to its
    neighbours.
    """
    idx = next((i for i, s in enumerate(day_stops) if s.name == target_stop.name), None)
    if idx is None:
        return 0.0

    prev_stop = day_stops[idx - 1] if idx > 0 else None
    next_stop = day_stops[idx + 1] if idx < len(day_stops) - 1 else None

    old_cost = 0.0
    new_cost = 0.0

    if prev_stop:
        old_km = _haversine(
            prev_stop.latitude, prev_stop.longitude,
            target_stop.latitude, target_stop.longitude,
        )
        new_km = _haversine(
            prev_stop.latitude, prev_stop.longitude,
            candidate.latitude, candidate.longitude,
        )
        old_cost += _leg_minutes(old_km)
        new_cost += _leg_minutes(new_km)

    if next_stop:
        old_km = _haversine(
            target_stop.latitude, target_stop.longitude,
            next_stop.latitude, next_stop.longitude,
        )
        new_km = _haversine(
            candidate.latitude, candidate.longitude,
            next_stop.latitude, next_stop.longitude,
        )
        old_cost += _leg_minutes(old_km)
        new_cost += _leg_minutes(new_km)

    return new_cost - old_cost


def calculate_distance_to_day_center(candidate: Place, day_stops: list[Place]) -> float:
    clat, clng = _day_centroid(day_stops)
    if clat == 0.0 and clng == 0.0:
        return 0.0
    return _haversine(candidate.latitude, candidate.longitude, clat, clng)


# ─── Replacement scoring ──────────────────────────────────────────────────────

def _score_replacement(
    candidate: Place,
    target_stop: Place,
    day_stops: list[Place],
    intent: TravelIntent,
    original_score: float,
    slot_type: str,
) -> tuple[float, float]:
    """
    Return (replacement_score, route_delta_minutes).

    replacement_score formula:
      0.30 * original_rerank_score  (position in reranked pool)
      0.25 * slot_compatibility     (1.0 if matches slot, 0.0 otherwise)
      0.20 * day_cluster_fit        (proxy: 1 − dist_to_centroid / 5km)
      0.15 * route_delta_score      (1 − delta_minutes / MAX_ROUTE_DELTA)
      0.05 * user_preference_match  (fraction of user interests covered)
      0.05 * source_confidence      (curated > reddit > google > other)
      − tourist_trap_penalty        (0.20 for high-risk places)
      − diversity_penalty           (0.15–0.30 for over-represented categories)
    """
    slot_compat = 1.0 if _matches_slot(candidate, slot_type) else 0.0

    dist_to_center = calculate_distance_to_day_center(candidate, day_stops)
    day_cluster_fit = max(0.0, 1.0 - dist_to_center / 5.0)

    route_delta_minutes = calculate_replacement_route_delta(candidate, target_stop, day_stops)
    route_delta_score = max(0.0, 1.0 - max(0.0, route_delta_minutes) / MAX_ROUTE_DELTA_MINUTES)

    tags = {t.lower() for t in candidate.tags}
    interests = {i.lower() for i in intent.interests}
    matched = sum(1 for i in interests if i in tags)
    pref_score = min(1.0, matched / max(1, len(interests)))

    src_confidence = {
        "curated_must_go": 1.0,
        "official_open_data": 0.9,
        "reddit": 0.8,
        "google_maps": 0.75,
    }.get(candidate.source_type, 0.6)

    trap_penalty = 0.20 if candidate.tourist_trap_risk == "high" else 0.0

    cat = candidate.category.lower()
    existing_same_cat = sum(
        1 for s in day_stops
        if s.category.lower() == cat and s.name != target_stop.name
    )
    diversity_penalty = 0.30 if existing_same_cat >= 2 else (0.15 if existing_same_cat == 1 else 0.0)

    score = (
        0.30 * original_score
        + 0.25 * slot_compat
        + 0.20 * day_cluster_fit
        + 0.15 * route_delta_score
        + 0.05 * pref_score
        + 0.05 * src_confidence
        - trap_penalty
        - diversity_penalty
    )

    return max(0.0, round(score, 4)), route_delta_minutes


# ─── Main entry point ─────────────────────────────────────────────────────────

def build_contextual_alternative_options(
    places: list[Place],
    itinerary: Itinerary,
    intent: TravelIntent,
    max_alts: int = 12,
) -> list[AlternativePlace]:
    """
    Build context-aware alternatives from the final reranked candidate pool.

    For each unused candidate, we evaluate it against every (day, stop) position
    in the itinerary.  A position is eligible when:
      - The candidate is in the same city as the day.
      - The candidate matches the template slot type for that position.
      - The swap does not violate the food cap or category diversity rule.
      - The route delta does not exceed MAX_ROUTE_DELTA_MINUTES.

    Each returned AlternativePlace has a `recommended_for` list with one entry
    per eligible (day, stop) position, allowing the frontend to sort and validate
    drops without re-contacting the backend.
    """
    days = itinerary.days
    if not days:
        return []

    used_names: set[str] = {stop.name.lower() for day in days for stop in day.stops}
    n = max(len(places), 1)

    # Pre-compute template slot types for each day so we don't repeat this per candidate
    slot_types_by_day: list[list[str]] = []
    for day_idx, day in enumerate(days):
        user_type = intent.user_type or "general"
        template = get_day_template(user_type, day_idx)
        day_slots: list[str] = []
        for stop_idx, stop in enumerate(day.stops):
            if stop_idx < len(template):
                day_slots.append(template[stop_idx])
            else:
                # Infer slot from stop properties for any overflow positions
                inferred = next(
                    (
                        st for st in [
                            "must_go_landmark", "cafe_or_local_food", "museum_or_culture",
                            "hidden_gem", "scenic_walk_or_open_area",
                        ]
                        if _matches_slot(stop, st)
                    ),
                    "general",
                )
                day_slots.append(inferred)
        slot_types_by_day.append(day_slots)

    # Track log stats
    stats = {
        "total_unused": 0,
        "rejected_city": 0,
        "rejected_slot": 0,
        "rejected_food_cap": 0,
        "rejected_diversity": 0,
        "rejected_route": 0,
        "eligible": 0,
    }

    result_entries: list[dict] = []

    for rank, place in enumerate(places):
        if place.name.lower() in used_names:
            continue
        if is_permanently_closed_place(place.name, place.city):
            continue
        if place.business_status in {"CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY"}:
            continue
        if "permanently closed" in place.open_status_label.lower():
            continue

        stats["total_unused"] += 1

        # Normalized score from reranker position (0.0 = last, 1.0 = first)
        original_score = 1.0 - (rank / n)
        candidate_slot_types = get_candidate_slot_types(place)

        recommended_for: list[RecommendedForItem] = []
        city_rejected = 0

        for day_idx, day in enumerate(days):
            # City consistency: candidate must match the dominant city of the day
            day_cities = {s.city.lower() for s in day.stops}
            if day_cities and place.city.lower() not in day_cities:
                city_rejected += 1
                continue

            day_stop_list = list(day.stops)

            for stop_idx, target_stop in enumerate(day.stops):
                slot_type = slot_types_by_day[day_idx][stop_idx]

                if not _matches_slot(place, slot_type):
                    stats["rejected_slot"] += 1
                    continue

                if would_violate_food_cap(place, day_stop_list, target_stop):
                    stats["rejected_food_cap"] += 1
                    continue

                if would_violate_category_diversity(place, day_stop_list, target_stop):
                    stats["rejected_diversity"] += 1
                    continue

                rep_score, route_delta = _score_replacement(
                    place, target_stop, day_stop_list, intent, original_score, slot_type
                )

                if route_delta > MAX_ROUTE_DELTA_MINUTES:
                    stats["rejected_route"] += 1
                    continue

                recommended_for.append(
                    RecommendedForItem(
                        day_index=day_idx,
                        stop_index=stop_idx,
                        replacement_score=rep_score,
                        route_delta_minutes=round(route_delta, 1),
                    )
                )

        if city_rejected > 0:
            stats["rejected_city"] += city_rejected

        if not recommended_for:
            continue

        stats["eligible"] += 1
        best_score = max(r.replacement_score for r in recommended_for)
        best_delta = min(r.route_delta_minutes for r in recommended_for)
        dist_to_center = calculate_distance_to_day_center(
            place, [s for day in days for s in day.stops]
        )

        result_entries.append({
            "place": place,
            "recommended_for": recommended_for,
            "best_score": best_score,
            "best_delta": best_delta,
            "candidate_slot_types": candidate_slot_types,
            "dist_to_center": dist_to_center,
        })

    # Sort by best replacement score descending
    result_entries.sort(key=lambda a: a["best_score"], reverse=True)
    result_entries = result_entries[:max_alts]

    logger.info(
        "contextual_alternatives: unused=%d city_reject=%d slot_reject=%d "
        "food_reject=%d div_reject=%d route_reject=%d eligible=%d returning=%d",
        stats["total_unused"],
        stats["rejected_city"],
        stats["rejected_slot"],
        stats["rejected_food_cap"],
        stats["rejected_diversity"],
        stats["rejected_route"],
        stats["eligible"],
        len(result_entries),
    )

    if logger.isEnabledFor(logging.DEBUG):
        for entry in result_entries[:5]:
            p = entry["place"]
            logger.debug(
                "  alt=%r score=%.3f delta=%.1f slots=%s recommended_positions=%s",
                p.name,
                entry["best_score"],
                entry["best_delta"],
                entry["candidate_slot_types"],
                [(r.day_index, r.stop_index) for r in entry["recommended_for"]],
            )

    return [
        AlternativePlace(
            name=e["place"].name,
            category=e["place"].category,
            city=e["place"].city,
            reason=e["place"].reason,
            local_tip=e["place"].local_tip,
            tourist_trap_risk=e["place"].tourist_trap_risk,
            source_url=e["place"].source_url,
            latitude=e["place"].latitude,
            longitude=e["place"].longitude,
            photo_name=e["place"].photo_name,
            compatible_slot_types=e["candidate_slot_types"],
            recommended_for=e["recommended_for"],
            replacement_score=round(e["best_score"], 3),
            route_delta_minutes=round(e["best_delta"], 1),
            distance_from_day_center_km=round(e["dist_to_center"], 2),
        )
        for e in result_entries
    ]
