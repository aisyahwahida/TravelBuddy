from __future__ import annotations

"""
itinerary_validator.py — Post-planning quality gate.

validate_itinerary()  checks constraint violations across days.
repair_itinerary()    removes the worst offenders and fills gaps from unused candidates.
"""

import logging
import math

from app.schemas.travel import Place, TravelIntent
from app.services.place_identity import place_identity_key

logger = logging.getLogger(__name__)

MIN_STOPS = 4
MAX_STOPS = 7
MAX_FOOD_PER_DAY = 2
MAX_SAME_CATEGORY = 2
LONG_LEG_WARNING_MIN = 40
LONG_LEG_INVALID_MIN = 60
MAX_DAILY_TRAVEL_MIN = 180   # 3 hours of transit in one day is too much
FAR_FROM_CENTER_KM = 4.0    # a stop this far from the day centroid is suspicious


# ─── Type helpers ─────────────────────────────────────────────────────────────

def _tags(place: Place) -> set[str]:
    return {t.lower() for t in place.tags}


def _is_food(place: Place) -> bool:
    tags = _tags(place)
    h = f"{place.category} {place.name}".lower()
    is_cafe = bool({"cafe", "cafes", "coffee", "espresso"}.intersection(tags)) or any(
        t in h for t in ("cafe", "coffee", "espresso")
    )
    is_rest = "restaurant" in tags or "bistro" in tags or "restaurant" in h
    is_market = bool({"market", "markets", "marketplace"}.intersection(tags))
    return is_cafe or is_rest or is_market


def _haversine_km(a: Place, b: Place) -> float:
    r = 6371
    dlat = math.radians(b.latitude - a.latitude)
    dlon = math.radians(b.longitude - a.longitude)
    x = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(a.latitude))
        * math.cos(math.radians(b.latitude))
        * math.sin(dlon / 2) ** 2
    )
    return r * 2 * math.atan2(math.sqrt(x), math.sqrt(1 - x))


def _leg_minutes(a: Place, b: Place) -> int:
    km = _haversine_km(a, b)
    if km <= 1.4:
        return max(4, round((km / 4.8) * 60))
    return max(12, round((km / 18) * 60 + 8))


def _day_centroid(stops: list[Place]) -> tuple[float, float]:
    if not stops:
        return 0.0, 0.0
    return (
        sum(p.latitude for p in stops) / len(stops),
        sum(p.longitude for p in stops) / len(stops),
    )


def _zig_zag_ratio(stops: list[Place]) -> float:
    """
    Ratio of actual route length to greedy nearest-neighbor estimate.
    1.0 = optimal; higher = more backtracking.
    Only meaningful for 3+ stops.
    """
    if len(stops) < 3:
        return 1.0
    actual = sum(_haversine_km(stops[i], stops[i + 1]) for i in range(len(stops) - 1))
    if actual < 0.01:
        return 1.0

    remaining = list(stops)
    current = remaining.pop(0)
    greedy = 0.0
    while remaining:
        nearest = min(remaining, key=lambda p: _haversine_km(current, p))
        greedy += _haversine_km(current, nearest)
        remaining.remove(nearest)
        current = nearest

    return actual / max(greedy, 0.001)


# ─── Validation ───────────────────────────────────────────────────────────────

class DayIssue:
    def __init__(self, day: int, code: str, detail: str = ""):
        self.day = day
        self.code = code
        self.detail = detail

    def __repr__(self) -> str:
        return f"Day {self.day}: [{self.code}] {self.detail}"


def validate_itinerary(
    days: list[list[Place]],
    intent: TravelIntent,
) -> list[DayIssue]:
    issues: list[DayIssue] = []
    all_keys: list[str] = []

    for day_idx, stops in enumerate(days):
        d = day_idx + 1

        # Stop count
        if len(stops) < MIN_STOPS:
            issues.append(DayIssue(d, "too_few_stops", f"{len(stops)} < {MIN_STOPS}"))
        if len(stops) > MAX_STOPS:
            issues.append(DayIssue(d, "too_many_stops", f"{len(stops)} > {MAX_STOPS}"))

        # Duplicate places within the day
        keys = [place_identity_key(p) for p in stops]
        if len(keys) != len(set(keys)):
            issues.append(DayIssue(d, "intra_day_duplicates"))
        all_keys.extend(keys)

        # Food cap
        food_count = sum(1 for p in stops if _is_food(p))
        if food_count > MAX_FOOD_PER_DAY:
            issues.append(DayIssue(d, "too_many_food", f"{food_count} food places"))

        # Category overload
        cat_counts: dict[str, int] = {}
        for p in stops:
            cat = p.category.lower()
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
        for cat, count in cat_counts.items():
            if count > MAX_SAME_CATEGORY:
                issues.append(DayIssue(d, "category_overload", f"'{cat}' × {count}"))

        # Leg analysis: warning at 40 min, invalid at 60 min
        total_travel_min = 0
        for i in range(1, len(stops)):
            mins = _leg_minutes(stops[i - 1], stops[i])
            total_travel_min += mins
            if mins > LONG_LEG_INVALID_MIN:
                issues.append(
                    DayIssue(d, "long_leg",
                             f"{stops[i-1].name} → {stops[i].name}: {mins} min")
                )
            elif mins > LONG_LEG_WARNING_MIN:
                issues.append(
                    DayIssue(d, "long_leg_warning",
                             f"{stops[i-1].name} → {stops[i].name}: {mins} min")
                )

        # Total daily travel time
        if total_travel_min > MAX_DAILY_TRAVEL_MIN:
            issues.append(DayIssue(d, "high_total_travel_time",
                                   f"{total_travel_min} min total transit"))

        # Stops far from the day centroid
        clat, clon = _day_centroid(stops)
        for stop in stops:
            r = 6371
            dlat = math.radians(stop.latitude - clat)
            dlon = math.radians(stop.longitude - clon)
            a_val = (
                math.sin(dlat / 2) ** 2
                + math.cos(math.radians(clat)) * math.cos(math.radians(stop.latitude))
                * math.sin(dlon / 2) ** 2
            )
            dist = r * 2 * math.atan2(math.sqrt(a_val), math.sqrt(1 - a_val))
            if dist > FAR_FROM_CENTER_KM:
                issues.append(DayIssue(d, "far_from_center",
                                       f"{stop.name} is {dist:.1f}km from day centroid"))

        # Zig-zag / backtracking score
        zz = _zig_zag_ratio(stops)
        if zz > 2.0:
            issues.append(DayIssue(d, "zig_zag",
                                   f"route efficiency ratio {zz:.2f} (ideal=1.0)"))

        # City consistency (no mixing cities unless multi-city intent)
        cities = {p.city.lower() for p in stops}
        destination = intent.destination.strip().lower()
        if len(cities) > 1 and destination != "france":
            issues.append(DayIssue(d, "city_mix", f"{cities}"))

    # Cross-day duplicates
    if len(all_keys) != len(set(all_keys)):
        issues.append(DayIssue(0, "cross_day_duplicates"))

    return issues


# ─── Repair ───────────────────────────────────────────────────────────────────

def repair_itinerary(
    days: list[list[Place]],
    all_candidates: list[Place],
    intent: TravelIntent,
) -> list[list[Place]]:
    """
    Light repair pass — fixes the most common validator issues.

    - Too many food places: drops excess food stops (lowest-rated first).
    - Cross-day or intra-day duplicates: removes the duplicate occurrence.
    - Too few stops: backfills from unused non-duplicate candidates.

    Long legs and city-mix are logged but not repaired here (route rebalancing
    is handled by planner.py's existing enforcement passes).
    """
    repaired = [list(day) for day in days]

    # ── 1. Remove cross-day duplicates (keep first occurrence) ───────────────
    seen: set[str] = set()
    for day_idx, stops in enumerate(repaired):
        kept = []
        for place in stops:
            key = place_identity_key(place)
            if key not in seen:
                kept.append(place)
                seen.add(key)
        repaired[day_idx] = kept

    # ── 2. Fix intra-day duplicates ───────────────────────────────────────────
    for day_idx, stops in enumerate(repaired):
        day_keys: set[str] = set()
        kept = []
        for place in stops:
            key = place_identity_key(place)
            if key not in day_keys:
                kept.append(place)
                day_keys.add(key)
        repaired[day_idx] = kept

    # ── 3. Enforce food cap per day ───────────────────────────────────────────
    used_keys = {place_identity_key(p) for day in repaired for p in day}
    for day_idx, stops in enumerate(repaired):
        food_stops = [p for p in stops if _is_food(p)]
        excess = len(food_stops) - MAX_FOOD_PER_DAY
        if excess <= 0:
            continue
        # Sort food by rating descending — keep top 2, drop the rest
        food_stops_sorted = sorted(
            food_stops,
            key=lambda p: float(p.google_rating or 0),
            reverse=True,
        )
        to_drop = {place_identity_key(p) for p in food_stops_sorted[MAX_FOOD_PER_DAY:]}
        repaired[day_idx] = [p for p in stops if place_identity_key(p) not in to_drop]
        used_keys -= to_drop

    # ── 4. Backfill days below minimum stop count ─────────────────────────────
    for day_idx, stops in enumerate(repaired):
        if len(stops) >= MIN_STOPS:
            continue
        gap = MIN_STOPS - len(stops)
        day_city = max(
            {p.city.lower() for p in stops},
            key=lambda c: sum(1 for p in stops if p.city.lower() == c),
            default="",
        )
        # Prefer non-food candidates in the same city not yet used
        candidates_pool = [
            c for c in all_candidates
            if place_identity_key(c) not in used_keys
            and (not day_city or c.city.lower() == day_city)
            and not _is_food(c)
        ]
        for candidate in candidates_pool:
            if gap <= 0:
                break
            key = place_identity_key(candidate)
            repaired[day_idx].append(candidate)
            used_keys.add(key)
            gap -= 1

    # ── 5. Same-slot repair for long legs (>60 min) ───────────────────────────
    # Import here to avoid a circular import at module level.
    from app.services.day_planner import SLOT_SEQUENCE, _matches_slot

    for day_idx, stops in enumerate(repaired):
        if len(stops) < 2:
            continue

        user_type = getattr(intent, "user_type", "general") or "general"
        day_template = SLOT_SEQUENCE.get(user_type, SLOT_SEQUENCE["general"])
        clat, clon = _day_centroid(stops)

        for stop_idx in range(1, len(stops)):
            km = _haversine_km(stops[stop_idx - 1], stops[stop_idx])
            leg_min = round((km / 4.8) * 60) if km <= 1.4 else round((km / 18.0) * 60 + 8)
            if leg_min <= LONG_LEG_INVALID_MIN:
                continue

            problem = stops[stop_idx]
            # Determine what slot type the problem stop is filling
            problem_slot = next(
                (st for st in day_template if _matches_slot(problem, st)), None
            )
            if problem_slot is None:
                continue

            # Find a replacement from unused candidates matching the same slot type
            pool = [
                c for c in all_candidates
                if place_identity_key(c) not in used_keys
                and _matches_slot(c, problem_slot)
            ]
            if not pool:
                continue

            # Prefer candidates closest to the day centroid
            pool.sort(key=lambda c: _haversine_km_coords(c.latitude, c.longitude, clat, clon))

            # Respect food cap
            food_before = sum(1 for p in stops if _is_food(p))
            replacement = None
            for cand in pool:
                food_delta = (1 if _is_food(cand) else 0) - (1 if _is_food(problem) else 0)
                if food_before + food_delta > MAX_FOOD_PER_DAY:
                    continue
                replacement = cand
                break

            if replacement is None:
                continue

            old_key = place_identity_key(problem)
            new_key = place_identity_key(replacement)
            repaired[day_idx] = [
                replacement if place_identity_key(p) == old_key else p
                for p in repaired[day_idx]
            ]
            used_keys.discard(old_key)
            used_keys.add(new_key)
            logger.info(
                "Repair day %d stop %d: '%s' → '%s' (slot=%s, %dmin leg)",
                day_idx + 1, stop_idx, problem.name, replacement.name,
                problem_slot, leg_min,
            )
            break  # one repair per day per pass

    return repaired


def enforce_min_stop_quality(
    days: list[list[Place]],
    all_candidates: list[Place],
    intent: TravelIntent,
) -> list[list[Place]]:
    """
    Final backstop: ensure every day has >= MIN_STOPS stops after repair.

    Backfills from all_candidates using city-awareness and a relaxing filter
    cascade. Days already at or above MIN_STOPS are untouched.
    """
    used_keys: set[str] = {place_identity_key(p) for day in days for p in day}
    result = [list(day) for day in days]

    for day_idx, stops in enumerate(result):
        if len(stops) >= MIN_STOPS:
            continue
        gap = MIN_STOPS - len(stops)

        # Determine the dominant city for this day
        day_city = ""
        if stops:
            city_counts: dict[str, int] = {}
            for p in stops:
                c = p.city.lower()
                city_counts[c] = city_counts.get(c, 0) + 1
            day_city = max(city_counts, key=lambda c: city_counts[c])

        # Relax constraints progressively until the day is filled
        filter_cascade = [
            lambda c, dc=day_city: c.city.lower() == dc and not _is_food(c),
            lambda c, dc=day_city: c.city.lower() == dc,
            lambda c: not _is_food(c),
            lambda c: True,
        ]
        for filter_fn in filter_cascade:
            if gap <= 0:
                break
            pool = [
                c for c in all_candidates
                if place_identity_key(c) not in used_keys and filter_fn(c)
            ]
            for candidate in pool:
                if gap <= 0:
                    break
                key = place_identity_key(candidate)
                result[day_idx].append(candidate)
                used_keys.add(key)
                gap -= 1

        final = len(result[day_idx])
        if final < MIN_STOPS:
            logger.warning(
                "enforce_min_stop_quality: Day %d still has only %d stops "
                "(pool exhausted for city=%r)",
                day_idx + 1, final, day_city,
            )
        else:
            logger.info(
                "enforce_min_stop_quality: Day %d backfilled to %d stops",
                day_idx + 1, final,
            )

    return result


def _haversine_km_coords(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
