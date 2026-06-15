from __future__ import annotations

"""
day_planner.py — Slot-based itinerary composition.

Each day is built by filling typed slots (must_go_landmark, cafe_or_local_food,
hidden_gem, museum_or_culture, scenic_walk_or_open_area) rather than picking the
globally highest-ranked places.  This guarantees every day is balanced and no day
becomes "only cafes" or "only museums".

Public API used by planner.py:
  build_full_itinerary(places, intent) -> list[list[Place]]
  validate_itinerary_balance(days)     -> dict
"""

import logging
import math
from app.schemas.travel import Place, TravelIntent
from app.services.place_identity import place_identity_key

logger = logging.getLogger(__name__)

# Imported lazily inside _route_aware_score / build_full_itinerary to avoid
# a startup-time circular import (geo_cluster → place_identity, not day_planner).
# The constant is mirrored here so the import only happens once per call.
_FAR_FROM_CENTER_KM = 3.0   # mirrors geo_cluster.FAR_FROM_CENTER_KM


# ─── Day templates ────────────────────────────────────────────────────────────
# Six slots per day map to time labels 09:00 / 10:30 / 12:30 / 14:30 / 17:00 / 19:00.
# The template changes based on user profile so first-timers get more landmarks,
# locals get more hidden gems, food travellers get more meal slots, etc.

SLOT_SEQUENCE: dict[str, list[str]] = {
    "general": [
        "must_go_landmark",       # 09:00 – start with something iconic
        "cafe_or_local_food",     # 10:30 – morning coffee / brunch
        "hidden_gem",             # 12:30 – local discovery at lunch pace
        "museum_or_culture",      # 14:30 – afternoon culture
        "scenic_walk_or_open_area",  # 17:00 – wind down with a stroll
        "cafe_or_local_food",     # 19:00 – dinner
    ],
    # general_low_specificity: same balanced template as general but
    # archetype boosts and profile ratios steer emphasis per day.
    "general_low_specificity": [
        "must_go_landmark",
        "cafe_or_local_food",
        "hidden_gem",
        "museum_or_culture",
        "scenic_walk_or_open_area",
        "cafe_or_local_food",
    ],
    "first_time_visitor": [
        "must_go_landmark",
        "cafe_or_local_food",
        "must_go_landmark",       # second landmark for bucket-list trips
        "museum_or_culture",
        "hidden_gem",
        "cafe_or_local_food",
    ],
    "returning_visitor": [
        "hidden_gem",
        "cafe_or_local_food",
        "hidden_gem",             # skip the tourist circuit
        "local_experience",
        "scenic_walk_or_open_area",
        "cafe_or_local_food",
    ],
    "local_resident": [
        "hidden_gem",
        "cafe_or_local_food",
        "local_experience",
        "hidden_gem",
        "scenic_walk_or_open_area",
        "cafe_or_local_food",
    ],
    "family_trip": [
        "must_go_landmark",
        "cafe_or_local_food",
        "family_friendly",
        "scenic_walk_or_open_area",
        "museum_or_culture",
        "cafe_or_local_food",
    ],
    "food_traveler": [
        "cafe_or_local_food",     # lead with food
        "hidden_gem",
        "cafe_or_local_food",
        "local_experience",
        "scenic_walk_or_open_area",
        "cafe_or_local_food",     # dinner slot
    ],
}

# Category diversity penalties — applied when the same category already appears in the day.
# 0 occurrences → 0.00  |  1 occurrence → 0.40  |  2+ occurrences → 0.80
CATEGORY_PENALTIES: dict[int, float] = {0: 0.0, 1: 0.40, 2: 0.80}

# Max food places (restaurant / cafe / market) allowed per day.
# Two cafe_or_local_food slots are intentional; anything beyond is overflow.
MAX_FOOD_PER_DAY = 2

# Slot types that must never be filled with food places, even as fallback.
NON_FOOD_SLOTS = {
    "must_go_landmark",
    "hidden_gem",
    "museum_or_culture",
    "scenic_walk_or_open_area",
    "local_experience",
    "family_friendly",
}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Approximate km distance between two lat/lon points."""
    r = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _tags(place: Place) -> set[str]:
    return {tag.lower() for tag in place.tags}


def _haystack(place: Place) -> str:
    return f"{place.category} {place.name}".lower()


def _is_food_place(place: Place) -> bool:
    """True when the place is primarily a restaurant, cafe, or market."""
    tags = _tags(place)
    haystack = _haystack(place)
    is_cafe = bool({"cafe", "cafes", "coffee", "espresso"}.intersection(tags)) or any(
        t in haystack for t in ("cafe", "coffee", "espresso")
    )
    is_restaurant = "restaurant" in tags or "bistro" in tags or "restaurant" in haystack
    is_market = bool({"market", "markets", "marketplace"}.intersection(tags)) or any(
        t in haystack for t in ("market", "marketplace")
    )
    return is_cafe or is_restaurant or is_market


# ─── Slot matchers ────────────────────────────────────────────────────────────

def _matches_slot(place: Place, slot_type: str) -> bool:
    """Return True when the place is a natural fit for the given slot type."""
    tags = _tags(place)
    haystack = _haystack(place)

    if slot_type == "must_go_landmark":
        return bool(
            {"must_go", "landmark", "iconic", "famous", "first_time", "landmarks"}.intersection(tags)
            or place.source_type == "curated_must_go"
        )

    if slot_type == "cafe_or_local_food":
        is_cafe = bool({"cafe", "cafes", "coffee", "espresso"}.intersection(tags)) or any(
            t in haystack for t in ("cafe", "coffee", "espresso")
        )
        is_restaurant = "restaurant" in tags or "restaurant" in haystack or "bistro" in tags
        is_market = bool({"market", "markets", "marketplace"}.intersection(tags)) or any(
            t in haystack for t in ("market", "marketplace", "marche")
        )
        return is_cafe or is_restaurant or is_market

    if slot_type == "hidden_gem":
        is_landmark = bool({"must_go", "landmark", "iconic", "famous"}.intersection(tags))
        is_food = "restaurant" in tags or bool({"cafe", "cafes", "coffee"}.intersection(tags)) or "market" in tags
        # Food hidden gems (local bakery, family bistro, covered passage) are valid
        # when the user has food interests — excluded only from non-food users.
        return place.tourist_trap_risk == "low" and not is_landmark and not is_food

    if slot_type == "museum_or_culture":
        is_museum = bool(
            {"museum", "museums", "gallery", "art", "exhibition", "exhibitions"}.intersection(tags)
        ) or any(t in haystack for t in ("museum", "musee", "gallery"))
        is_event = bool(
            {"event", "events", "concert", "theatre", "library", "libraries",
             "bookstore", "bookstores"}.intersection(tags)
        )
        return is_museum or is_event

    if slot_type == "scenic_walk_or_open_area":
        return bool(
            {"park", "parks", "garden", "gardens", "walks", "walk", "quiet",
             "viewpoint", "views", "outdoor"}.intersection(tags)
        ) or any(t in haystack for t in ("park", "garden", "walk", "viewpoint", "promenade"))

    if slot_type == "local_experience":
        is_landmark = bool({"must_go", "landmark", "iconic", "famous"}.intersection(tags))
        return place.source_type in {"reddit", "google_maps"} and not is_landmark

    if slot_type == "family_friendly":
        return bool(
            {"family", "kids", "family-friendly", "children", "park", "garden",
             "outdoor", "zoo", "aquarium"}.intersection(tags)
        )

    return False


# ─── Public scoring functions ─────────────────────────────────────────────────

def get_day_template(user_type: str, day_index: int = 0) -> list[str]:
    """
    Return the ordered slot sequence for a given user profile.
    day_index is reserved for future per-day template variation.
    """
    return list(SLOT_SEQUENCE.get(user_type, SLOT_SEQUENCE["general"]))


def calculate_category_diversity_penalty(place: Place, day_so_far: list[Place]) -> float:
    """
    Penalise placing the same category repeatedly in one day.
      0 occurrences → 0.00 (no penalty)
      1 occurrence  → 0.25 (slight penalty)
      2+ occurrences → 0.60 (heavy penalty)
    """
    category = place.category.lower()
    count = sum(1 for p in day_so_far if p.category.lower() == category)
    return CATEGORY_PENALTIES.get(min(count, 2), 0.60)


def calculate_distance_score(place: Place, prev_place: Place | None) -> float:
    """
    Proximity score 0–1.  Closer is better.
      0 km  → 1.0   |   5 km → 0.5   |   10 km+ → 0.0
    Returns 0.8 as a neutral default when there is no previous stop yet.
    """
    if prev_place is None:
        return 0.8
    dist_km = _haversine(
        prev_place.latitude, prev_place.longitude,
        place.latitude, place.longitude,
    )
    return max(0.0, 1.0 - dist_km / 10.0)


def calculate_base_place_score(place: Place, intent: TravelIntent) -> float:
    """
    Multi-factor score that is independent of slot position or day context.

    Component weights (distance 15% and diversity 5% are added in calculate_slot_score):
      25% preference match   — how many of the user's interests the place covers
      20% hidden gem score   — low tourist-trap-risk & reddit-sourced places
      15% must-go score      — landmark / curated must-go places
      10% opening hours      — open_now bonus or closed penalty
      10% rating quality     — Google rating scaled to 0–1 above 3.0 stars
    """
    tags = _tags(place)
    interests = {i.lower() for i in intent.interests}

    # Preference match (0–1)
    matched = sum(1 for i in interests if i in tags)
    pref_match = min(1.0, matched / max(1, len(interests)))

    # Hidden gem score (0–1)
    is_landmark = bool({"must_go", "landmark", "iconic", "famous"}.intersection(tags))
    is_gem = place.tourist_trap_risk == "low" and not is_landmark
    reddit_boost = 0.3 if place.source_type == "reddit" and not is_landmark else 0.0
    hidden_gem = min(1.0, (1.0 if is_gem else 0.0) + reddit_boost)

    # Must-go score (0–1)
    must_go = 1.0 if is_landmark else (0.5 if place.source_type == "curated_must_go" else 0.0)

    # Opening hours score (−0.5 to 1.0)
    if place.open_now is True:
        hours = 1.0
    elif place.open_now is False:
        hours = -0.5
    elif place.opening_hours:
        hours = 0.5
    else:
        hours = 0.0

    # Rating quality (0–1, only above 3 stars counts)
    rating = float(place.google_rating or 0.0)
    rating_q = min(1.0, max(0.0, (rating - 3.0) / 2.0)) if rating >= 3.0 else 0.0

    # Mild penalty for missing photo/map — enough to prefer richer entries but not
    # so heavy that a real hidden gem without a photo loses to a mainstream place.
    has_photo = bool(place.photo_name or place.wiki_thumb_url)
    has_gmap = bool(place.google_maps_url)
    photo_penalty = 0.0 if has_photo else -0.3
    gmap_penalty = 0.0 if has_gmap else -0.2

    return (
        0.25 * pref_match
        + 0.20 * hidden_gem
        + 0.15 * must_go
        + 0.10 * hours
        + 0.10 * rating_q
        + photo_penalty
        + gmap_penalty
    )


def _route_aware_score(
    place: Place,
    prev_place: Place | None,
    day_cluster: DayClusterContext | None,
) -> float:
    """
    Additive route-efficiency bonus/penalty (max ~+1.3, min ~-1.4).
    Never large enough to override the slot_bonus (±3.0/2.0).

    Components
    ----------
    +0.6  in-cluster bonus: place belongs to the day's geographic cluster
    +0.4  center proximity: sliding bonus from 0 km to FAR_FROM_CENTER_KM
    +0.3  prev-stop proximity: closer previous stop = easier travel
    -0.5× far-from-center penalty: per km beyond FAR_FROM_CENTER_KM
    -0.04× long-leg penalty: per minute beyond 40 min
    """
    if day_cluster is None:
        return 0.0

    score = 0.0

    # In-cluster bonus
    key = place_identity_key(place)
    if key in day_cluster.place_keys:
        score += 0.6

    # Distance to day centre
    dist_to_center = _haversine(
        place.latitude, place.longitude,
        day_cluster.center_lat, day_cluster.center_lng,
    )
    if dist_to_center <= _FAR_FROM_CENTER_KM:
        score += 0.4 * (1.0 - dist_to_center / _FAR_FROM_CENTER_KM)
    else:
        score -= 0.5 * (dist_to_center - _FAR_FROM_CENTER_KM)

    # Proximity to previous stop + long-leg penalty
    if prev_place is not None:
        dist_km = _haversine(
            prev_place.latitude, prev_place.longitude,
            place.latitude, place.longitude,
        )
        # Proximity bonus: 0–0.3 over 0–3 km
        score += max(0.0, 0.3 * (1.0 - dist_km / 3.0))

        # Leg time estimate
        if dist_km <= 1.4:
            leg_min = max(4, round((dist_km / 4.8) * 60))
        else:
            leg_min = max(12, round((dist_km / 18.0) * 60 + 8))

        if leg_min > 40:
            score -= 0.04 * (leg_min - 40)  # -0.04/min above 40 min

    return score


def calculate_slot_score(
    place: Place,
    slot_type: str,
    day_so_far: list[Place],
    prev_place: Place | None,
    intent: TravelIntent,
    day_cluster: DayClusterContext | None = None,
) -> float:
    """
    Final slot score combining all factors.

    Full formula:
      score = calculate_base_place_score(...)
            + 0.15 * distance_efficiency
            + 0.30 * (1 − category_diversity_penalty)
            + city_consistency_bonus          (0.20 if same city as day majority)
            + route_aware_score               (±1.3 max, geo-cluster bonus/penalty)
            + slot_relevance                  (+3.0 if matches slot, −2.0 if not)
            − consecutive_type_penalty        (−0.40 if same slot type as previous stop)

    The slot_relevance term is the key differentiator: it ensures that the
    best candidate for a "hidden_gem" slot is not a landmark even if the landmark
    has a higher base score.
    """
    base = calculate_base_place_score(place, intent)

    # Distance efficiency (0–1, weighted 15%)
    dist_score = calculate_distance_score(place, prev_place)

    # Category diversity penalty → convert to diversity score (0–1, weighted 30%)
    cat_penalty = calculate_category_diversity_penalty(place, day_so_far)
    diversity = 1.0 - cat_penalty

    # City consistency: prefer the city that already dominates the day.
    # Only apply once at least 2 stops are chosen.
    city_bonus = 0.0
    if len(day_so_far) >= 2:
        city_counts: dict[str, int] = {}
        for p in day_so_far:
            city_counts[p.city.lower()] = city_counts.get(p.city.lower(), 0) + 1
        dominant = max(city_counts, key=lambda c: city_counts[c])
        dominant_share = city_counts[dominant] / len(day_so_far)
        if place.city.lower() == dominant and dominant_share > 0.5:
            city_bonus = 0.2

    # Route-aware bonus/penalty (geo-cluster context)
    route_score = _route_aware_score(place, prev_place, day_cluster)

    weighted = base + 0.15 * dist_score + 0.30 * diversity + city_bonus + route_score

    # Slot relevance: large bonus for matching the slot, penalty for not matching
    slot_bonus = 3.0 if _matches_slot(place, slot_type) else -2.0

    # Consecutive same-type penalty
    consec_penalty = 0.0
    if day_so_far and slot_type not in {"cafe_or_local_food"}:
        prev = day_so_far[-1]
        if _matches_slot(prev, slot_type) and _matches_slot(place, slot_type):
            consec_penalty = 0.4

    return weighted + slot_bonus - consec_penalty


# ─── Candidate selection ──────────────────────────────────────────────────────

def get_slot_candidates(
    all_candidates: list[Place],
    slot_type: str,
    used_keys: set[str],
    day_so_far: list[Place],
    prev_place: Place | None,
    intent: TravelIntent,
    food_count: int = 0,
    day_cluster: "DayClusterContext | None" = None,
    archetype: "object | None" = None,
    trip_category_counts: "dict[str, int] | None" = None,
) -> list[Place]:
    """
    Return all unused candidates ranked by slot score (highest first).
    Food places are excluded from non-food slots, and once the daily food cap
    is reached they are excluded from every slot.

    Optional params:
      archetype           — DayArchetype for archetype-level slot boosts (5+ day general trips)
      trip_category_counts — category counts across all days so far (trip-level diversity)
    """
    from app.services.day_archetypes import get_archetype_slot_boost, apply_archetype_tag_bias

    available = [p for p in all_candidates if place_identity_key(p) not in used_keys]

    # Enforce hard food exclusion, with one exception:
    # hidden_gem slot allows food when the user has food interests (local bakery,
    # family bistro, covered market passage are legitimate hidden gems).
    food_interests = {"food", "restaurant", "restaurants", "bistro", "cafe", "cafes",
                      "coffee", "market", "markets", "dining", "eat", "lunch", "dinner"}
    user_has_food_interest = bool(food_interests.intersection(
        {i.lower() for i in intent.interests}
    ))
    allow_food_for_this_slot = (
        slot_type == "hidden_gem" and user_has_food_interest and food_count < MAX_FOOD_PER_DAY
    )

    food_cap_hit = food_count >= MAX_FOOD_PER_DAY
    if (slot_type in NON_FOOD_SLOTS and not allow_food_for_this_slot) or food_cap_hit:
        non_food = [p for p in available if not _is_food_place(p)]
        if non_food:
            available = non_food
        elif slot_type in NON_FOOD_SLOTS:
            available = available  # last resort: keep all to avoid empty slot

    # Archetype slot boost — extra bonus for slots that match this day's theme
    archetype_slot_boost = get_archetype_slot_boost(archetype, slot_type)

    scored: list[tuple[float, Place]] = []
    for p in available:
        base = calculate_slot_score(p, slot_type, day_so_far, prev_place, intent, day_cluster)

        # Archetype tag bias (max +0.4): prefer places that fit the day's theme
        tag_bias = apply_archetype_tag_bias(
            {t.lower() for t in p.tags},
            p.source_type,
            archetype,
        )
        # Archetype slot boost (up to +1.0): slot-type match earns extra when day has a theme
        slot_theme_bonus = archetype_slot_boost if _matches_slot(p, slot_type) else 0.0

        # Trip-level category repetition penalty: discourage over-used categories
        trip_cat_penalty = 0.0
        if trip_category_counts:
            cat = p.category.lower()
            count = trip_category_counts.get(cat, 0)
            user_wants = bool(
                {i.lower() for i in intent.interests}.intersection({cat, cat.rstrip("s")})
            )
            if count >= 5 and not user_wants:
                trip_cat_penalty = 0.6
            elif count >= 3 and not user_wants:
                trip_cat_penalty = 0.3

        scored.append((base + tag_bias + slot_theme_bonus - trip_cat_penalty, p))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored]


# ─── Day builder ─────────────────────────────────────────────────────────────

def build_balanced_day(
    candidates: list[Place],
    day_index: int,
    intent: TravelIntent,
    used_keys: set[str],
    day_cluster: "DayClusterContext | None" = None,
    archetype: "object | None" = None,
    trip_category_counts: "dict[str, int] | None" = None,
) -> list[Place]:
    """
    Fill one day by iterating through its slot sequence and picking the best
    available candidate for each slot.

    Strategy per slot:
      1. Rank all unused candidates by calculate_slot_score() (includes route bonus).
      2. Apply archetype boosts and trip-level category penalties (optional).
      3. Pick the top slot-matching place; fall back to best-in-pool.
      4. Mark the chosen place as used so it cannot appear on another day.
    """
    user_type = getattr(intent, "user_type", "") or "general"
    slots = get_day_template(user_type, day_index)

    day_so_far: list[Place] = []
    prev_place: Place | None = None
    food_count = 0

    for slot_type in slots:
        ranked = get_slot_candidates(
            candidates, slot_type, used_keys, day_so_far, prev_place, intent,
            food_count=food_count,
            day_cluster=day_cluster,
            archetype=archetype,
            trip_category_counts=trip_category_counts,
        )
        if not ranked:
            break

        # Prefer a place that actually matches this slot; fall back to best in pool.
        chosen = next((p for p in ranked if _matches_slot(p, slot_type)), ranked[0])

        key = place_identity_key(chosen)
        used_keys.add(key)
        day_so_far.append(chosen)
        prev_place = chosen
        if _is_food_place(chosen):
            food_count += 1

    return day_so_far


# ─── Full itinerary builder ───────────────────────────────────────────────────

def _day_route_stats(stops: list[Place]) -> tuple[float, int]:
    """Return (total_km, max_leg_minutes) for a single day's stops."""
    total_km = 0.0
    max_min = 0
    for i in range(1, len(stops)):
        km = _haversine(
            stops[i - 1].latitude, stops[i - 1].longitude,
            stops[i].latitude, stops[i].longitude,
        )
        total_km += km
        if km <= 1.4:
            leg_min = max(4, round((km / 4.8) * 60))
        else:
            leg_min = max(12, round((km / 18.0) * 60 + 8))
        max_min = max(max_min, leg_min)
    return total_km, max_min


def build_full_itinerary(
    places: list[Place],
    intent: TravelIntent,
) -> list[list[Place]]:
    """
    Build a balanced day-by-day itinerary using slot-based selection.

    Pipeline:
      1. For France-wide general trips: pre-assign cities to days (city allocator).
      2. Geo-cluster within the assigned city (or globally for city-specific trips).
      3. For 5+ day general trips: assign a day archetype that biases slot selection.
      4. Fill each day's 6 slots; track trip-level category counts to prevent repetition.
    """
    from app.services.geo_cluster import cluster_places, select_day_cluster
    from app.services.day_archetypes import get_day_archetype
    from app.services.city_allocator import (
        is_france_country_trip,
        allocate_cities_for_country_trip,
        build_city_day_blocks,
    )

    duration = intent.duration_days

    # ── City allocation for France-wide general trips ─────────────────────────
    city_schedule: list[str] = []
    city_blocks: dict[str, list[Place]] = {}
    city_cluster_cache: dict[str, list] = {}

    if is_france_country_trip(intent):
        city_schedule = allocate_cities_for_country_trip(intent, places, duration)
        if city_schedule:
            city_blocks = build_city_day_blocks(places)
            logger.info(
                "build_full_itinerary: France city schedule → %s",
                city_schedule,
            )

    # ── Global clusters (used for single-city trips or France fallback) ───────
    global_clusters = cluster_places(places, intent)
    used_cluster_ids: set[int] = set()
    used_keys: set[str] = set()
    days: list[list[Place]] = []
    trip_category_counts: dict[str, int] = {}

    for day_index in range(duration):
        day_number = day_index + 1

        # Resolve candidate pool (city-filtered or global)
        if city_schedule and day_index < len(city_schedule):
            assigned_city = city_schedule[day_index]
            city_candidates = city_blocks.get(assigned_city, places)

            # Per-city clusters (cache to avoid recomputing)
            if assigned_city not in city_cluster_cache:
                city_cluster_cache[assigned_city] = cluster_places(city_candidates, intent)
            city_used_ids = used_cluster_ids   # share the set; per-city clusters have unique ids
            day_cluster = select_day_cluster(
                city_cluster_cache[assigned_city], city_used_ids, day_index, intent
            )
            day_candidates = city_candidates
        else:
            day_cluster = select_day_cluster(global_clusters, used_cluster_ids, day_index, intent)
            day_candidates = places

        if day_cluster is not None:
            used_cluster_ids.add(day_cluster.cluster_id)

        # Day archetype (5+ day general trips only)
        archetype = get_day_archetype(day_number, duration, intent)

        day_stops = build_balanced_day(
            day_candidates,
            day_index,
            intent,
            used_keys,
            day_cluster,
            archetype=archetype,
            trip_category_counts=trip_category_counts,
        )
        days.append(day_stops)

        # Update trip-level category counts
        for stop in day_stops:
            cat = stop.category.lower()
            trip_category_counts[cat] = trip_category_counts.get(cat, 0) + 1

        if logger.isEnabledFor(logging.DEBUG) and day_stops:
            total_km, max_leg = _day_route_stats(day_stops)
            categories = [s.category for s in day_stops]
            logger.debug(
                "Day %d: %d stops | cluster=%s | archetype=%s | route_km=%.1f | "
                "max_leg=%dmin | categories=%s",
                day_number, len(day_stops),
                day_cluster.cluster_id if day_cluster else "none",
                archetype.name if archetype else "none",
                total_km, max_leg, categories,
            )

    logger.info(
        "build_full_itinerary: %d days | stops/day=%s | trip_categories=%s",
        len(days),
        [len(d) for d in days],
        dict(sorted(trip_category_counts.items(), key=lambda x: -x[1])[:5]),
    )
    return days


# ─── Balance validation ───────────────────────────────────────────────────────

def validate_itinerary_balance(days: list[list[Place]]) -> dict:
    """
    Inspect each day for category overloading.
    Returns a structured report useful for debugging and testing.
    """
    day_reports = []
    for day_index, stops in enumerate(days):
        category_counts: dict[str, int] = {}
        inferred_slots: list[str] = []
        for stop in stops:
            cat = stop.category.lower()
            category_counts[cat] = category_counts.get(cat, 0) + 1
            if _matches_slot(stop, "must_go_landmark"):
                inferred_slots.append("must_go_landmark")
            elif _matches_slot(stop, "cafe_or_local_food"):
                inferred_slots.append("cafe_or_local_food")
            elif _matches_slot(stop, "hidden_gem"):
                inferred_slots.append("hidden_gem")
            elif _matches_slot(stop, "museum_or_culture"):
                inferred_slots.append("museum_or_culture")
            elif _matches_slot(stop, "scenic_walk_or_open_area"):
                inferred_slots.append("scenic_walk_or_open_area")
            else:
                inferred_slots.append("general")

        issues = [
            f"'{cat}' appears {count}x (recommended max: 2)"
            for cat, count in category_counts.items()
            if count >= 3
        ]
        day_reports.append({
            "day": day_index + 1,
            "stop_count": len(stops),
            "inferred_slots": inferred_slots,
            "category_counts": category_counts,
            "issues": issues,
        })

    return {
        "balanced": all(not d["issues"] for d in day_reports),
        "total_stops": sum(d["stop_count"] for d in day_reports),
        "days": day_reports,
    }
