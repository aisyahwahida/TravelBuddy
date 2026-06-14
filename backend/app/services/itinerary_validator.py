from __future__ import annotations

"""
itinerary_validator.py — Post-planning quality gate.

validate_itinerary()  checks constraint violations across days.
repair_itinerary()    removes the worst offenders and fills gaps from unused candidates.
"""

from app.schemas.travel import Place, TravelIntent
from app.services.place_identity import place_identity_key

MIN_STOPS = 4
MAX_STOPS = 7
MAX_FOOD_PER_DAY = 2
MAX_SAME_CATEGORY = 2


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
    import math
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

        # Long legs (> 60 min)
        for i in range(1, len(stops)):
            mins = _leg_minutes(stops[i - 1], stops[i])
            if mins > 60:
                issues.append(
                    DayIssue(d, "long_leg",
                             f"{stops[i-1].name} → {stops[i].name}: {mins} min")
                )

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

    return repaired
