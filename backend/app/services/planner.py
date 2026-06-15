from __future__ import annotations
import math
from app.schemas.travel import Itinerary, ItineraryDay, LocationAnchor, Place, TravelIntent
from app.services.place_identity import place_identity_key
from app.services.day_planner import build_full_itinerary as _slot_build_days

MAX_DAY_LEG_MINUTES = 60
MIN_STOPS_PER_DAY = 4
MAX_STOPS_PER_DAY = 6


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return approximate distance in km between two lat/lon points."""
    r = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _route_distance(stops: list[Place]) -> float:
    return sum(
        _haversine(stops[i].latitude, stops[i].longitude, stops[i + 1].latitude, stops[i + 1].longitude)
        for i in range(len(stops) - 1)
    )


def _estimated_leg_minutes(from_stop: Place, to_stop: Place) -> int:
    distance_km = _haversine(
        from_stop.latitude,
        from_stop.longitude,
        to_stop.latitude,
        to_stop.longitude,
    )
    if distance_km <= 1.4:
        return max(4, round((distance_km / 4.8) * 60))
    return max(12, round((distance_km / 18) * 60 + 8))


def _estimated_anchor_leg_minutes(anchor: LocationAnchor, to_stop: Place) -> int:
    distance_km = _haversine(
        anchor.latitude,
        anchor.longitude,
        to_stop.latitude,
        to_stop.longitude,
    )
    if distance_km <= 1.4:
        return max(4, round((distance_km / 4.8) * 60))
    return max(12, round((distance_km / 18) * 60 + 8))


def _two_opt(stops: list[Place]) -> list[Place]:
    """Repeatedly reverse sub-segments that reduce total route distance."""
    best = list(stops)
    best_dist = _route_distance(best)
    improved = True
    while improved:
        improved = False
        for i in range(1, len(best) - 1):
            for j in range(i + 1, len(best)):
                candidate = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                d = _route_distance(candidate)
                if d < best_dist - 1e-9:
                    best, best_dist, improved = candidate, d, True
    return best


def _nearest_neighbor_sort(stops: list[Place]) -> list[Place]:
    """Best nearest-neighbor from every start point, then 2-opt improved."""
    if len(stops) <= 2:
        return stops
    best_route: list[Place] = []
    best_dist = float("inf")
    for start in range(len(stops)):
        remaining = list(stops)
        ordered = [remaining.pop(start)]
        while remaining:
            last = ordered[-1]
            nearest = min(remaining, key=lambda s: _haversine(last.latitude, last.longitude, s.latitude, s.longitude))
            ordered.append(nearest)
            remaining.remove(nearest)
        d = _route_distance(ordered)
        if d < best_dist:
            best_dist, best_route = d, ordered
    return _two_opt(best_route)


def _sort_from_anchor(stops: list[Place], anchor: LocationAnchor | None) -> list[Place]:
    if not anchor or len(stops) <= 1:
        return _nearest_neighbor_sort(stops)
    remaining = list(stops)
    ordered: list[Place] = []
    current_lat = anchor.latitude
    current_lon = anchor.longitude
    while remaining:
        next_stop = min(
            remaining,
            key=lambda s: _haversine(current_lat, current_lon, s.latitude, s.longitude),
        )
        ordered.append(next_stop)
        remaining.remove(next_stop)
        current_lat, current_lon = next_stop.latitude, next_stop.longitude
    return _two_opt(ordered) if len(ordered) > 2 else ordered


def _tags(place: Place) -> set[str]:
    return {tag.lower() for tag in place.tags}


def _haystack(place: Place) -> str:
    return f"{place.category} {place.name}".lower()


def _place_key(place: Place) -> tuple[str, str]:
    return (place_identity_key(place), place.city.lower())


def _has_display_photo(place: Place) -> bool:
    return bool(place.photo_name.strip() or (place.wiki_thumb_url or "").strip())


def _is_cafe(place: Place) -> bool:
    return bool({"cafe", "cafes", "coffee", "espresso"}.intersection(_tags(place))) or any(
        term in _haystack(place) for term in ("cafe", "coffee", "espresso")
    )


def _is_restaurant(place: Place) -> bool:
    return "restaurant" in _tags(place) or "restaurant" in _haystack(place)


def _is_market(place: Place) -> bool:
    return bool({"market", "markets", "marketplace"}.intersection(_tags(place))) or any(
        term in _haystack(place) for term in ("market", "marketplace", "marche")
    )


def _is_museum(place: Place) -> bool:
    tags = _tags(place)
    category = place.category.lower()
    if bool({"museum", "museums", "gallery", "art"}.intersection(tags)):
        return True
    if any(term in category for term in ("museum", "musee", "gallery")):
        return True
    if _is_cafe(place) or _is_restaurant(place):
        return False
    return any(term in place.name.lower() for term in ("museum", "musee", "gallery"))


def _is_shopping(place: Place) -> bool:
    tags = _tags(place)
    return bool(
        {
            "shopping",
            "shop",
            "shops",
            "souvenirs",
            "vintage",
            "thrift",
            "fashion",
            "boutique",
            "mall",
            "department store",
        }.intersection(tags)
    ) or any(
        term in _haystack(place)
        for term in ("shop", "shopping", "souvenir", "vintage", "boutique", "mall")
    )


def _is_must_go(place: Place) -> bool:
    tags = _tags(place)
    return bool({"must_go", "first_time", "iconic", "landmark", "landmarks"}.intersection(tags)) or "must-go" in _haystack(place)


def _is_walk_or_park(place: Place) -> bool:
    tags = _tags(place)
    return bool({"walks", "park", "parks", "garden", "gardens", "quiet"}.intersection(tags)) or any(
        term in _haystack(place) for term in ("walk", "park", "garden", "viewpoint")
    )


def _is_activity(place: Place) -> bool:
    activity_terms = {
        "museum",
        "museums",
        "gallery",
        "park",
        "parks",
        "garden",
        "gardens",
        "walks",
        "event",
        "events",
        "activity",
        "activities",
        "bookstores",
        "library",
        "libraries",
        "shopping",
        "must_go",
        "first_time",
        "iconic",
        "landmark",
        "landmarks",
        "heritage",
        "castle",
        "palace",
        "cathedral",
        "religious",
        "shop",
        "shops",
        "souvenirs",
        "vintage",
        "thrift",
        "flea market",
        "luxury",
        "high end",
        "fashion",
        "brand",
        "brands",
        "department store",
        "mall",
        "boutique",
        "skincare",
        "pharmacy",
    }
    return bool(activity_terms.intersection(_tags(place))) or any(
        term in _haystack(place)
        for term in (
            "museum",
            "musee",
            "gallery",
            "park",
            "garden",
            "walk",
            "event",
            "activity",
            "book",
            "library",
            "shop",
            "must-go",
            "landmark",
            "heritage",
            "castle",
            "palace",
            "cathedral",
            "religious",
            "shopping",
            "souvenir",
            "vintage",
            "thrift",
            "flea",
            "department store",
            "mall",
            "boutique",
            "pharmacy",
        )
    )


def _with_time(place: Place, time_label: str) -> Place:
    original_time = place.best_time.strip()
    best_time = (
        f"{time_label} ({original_time})"
        if original_time and not original_time[:2].isdigit()
        else time_label
    )
    return place.model_copy(update={"best_time": best_time})


def _adjust_filler_time_label(time_label: str, place: Place) -> str:
    if _is_cafe(place) and "cafe" not in time_label:
        return time_label.replace("culture or wander", "cafe / local pause").replace(
            "stroll", "cafe / local pause"
        )
    if (_is_restaurant(place) or _is_market(place)) and not any(
        meal in time_label for meal in ("lunch", "dinner")
    ):
        return time_label.replace("culture or wander", "meal stop").replace(
            "stroll", "meal stop"
        )
    return time_label


def _take_first(
    candidates: list[Place],
    used: set[tuple[str, str]],
    matcher,
) -> Place | None:
    for place in candidates:
        key = _place_key(place)
        if key not in used and matcher(place):
            used.add(key)
            return place
    return None


def _fill_remaining(
    candidates: list[Place],
    used: set[tuple[str, str]],
    limit: int,
) -> list[Place]:
    remaining = []
    for place in candidates:
        if len(remaining) >= limit:
            break
        key = _place_key(place)
        if key in used:
            continue
        used.add(key)
        remaining.append(place)
    return remaining


def _day_centroid(stops: list[Place]) -> tuple[float, float]:
    if not stops:
        return (48.8566, 2.3522)
    return (
        sum(stop.latitude for stop in stops) / len(stops),
        sum(stop.longitude for stop in stops) / len(stops),
    )


def _closest_leg_minutes(stop: Place, day_stops: list[Place]) -> int:
    if not day_stops:
        return 0
    return min(_estimated_leg_minutes(stop, existing) for existing in day_stops)


def _cluster_days_by_location(stops: list[Place], day_count: int) -> list[list[Place]]:
    if day_count <= 1 or len(stops) <= 1:
        return [list(stops)] if stops else [[]]

    city_counts: dict[str, int] = {}
    for stop in stops:
        city_key = stop.city.lower()
        city_counts[city_key] = city_counts.get(city_key, 0) + 1

    sorted_stops = sorted(
        stops,
        key=lambda place: (
            place.city.lower(),
            place.latitude,
            place.longitude,
            place.name.lower(),
        ),
    )
    days: list[list[Place]] = [[] for _ in range(day_count)]

    city_groups: dict[str, list[Place]] = {}
    for stop in sorted_stops:
        city_groups.setdefault(stop.city.lower(), []).append(stop)

    city_slots: dict[str, int] = {}
    viable_cities = sorted(
        city_groups,
        key=lambda city: (-len(city_groups[city]), city),
    )
    for city in viable_cities:
        if len(city_slots) >= day_count:
            break
        if len(city_groups[city]) >= MIN_STOPS_PER_DAY:
            city_slots[city] = 1

    while sum(city_slots.values()) < day_count and city_slots:
        city = max(
            city_slots,
            key=lambda key: (
                len(city_groups[key]) / (city_slots[key] + 1),
                len(city_groups[key]),
                key,
            ),
        )
        city_slots[city] += 1

    seed_stops: list[Place] = []
    for city, slot_count in sorted(city_slots.items(), key=lambda item: (-len(city_groups[item[0]]), item[0])):
        group = city_groups[city]
        for slot_index in range(slot_count):
            seed_index = min(len(group) - 1, round((slot_index / max(1, slot_count)) * len(group)))
            seed_stops.append(group[seed_index])
            if len(seed_stops) >= day_count:
                break
        if len(seed_stops) >= day_count:
            break

    if len(seed_stops) < day_count:
        seeded_keys = {_place_key(stop) for stop in seed_stops}
        for stop in sorted_stops:
            if _place_key(stop) in seeded_keys:
                continue
            seed_stops.append(stop)
            if len(seed_stops) >= day_count:
                break

    seeded_keys = {_place_key(stop) for stop in seed_stops[:day_count]}
    for index, stop in enumerate(seed_stops[:day_count]):
        days[index].append(stop)

    for stop in sorted_stops:
        if _place_key(stop) in seeded_keys:
            continue
        scored: list[tuple[int, int, float, int, int]] = []
        for index, day_stops in enumerate(days):
            centroid_lat, centroid_lon = _day_centroid(day_stops)
            centroid_distance = _haversine(
                stop.latitude, stop.longitude, centroid_lat, centroid_lon
            )
            closest_leg = _closest_leg_minutes(stop, day_stops)
            leg_penalty = 0 if closest_leg <= MAX_DAY_LEG_MINUTES else 1
            city_penalty = (
                0
                if not day_stops
                or any(existing.city.lower() == stop.city.lower() for existing in day_stops)
                else 1
            )
            scored.append(
                (leg_penalty, city_penalty, centroid_distance, len(day_stops), index)
            )
        _, _, _, _, best_index = min(scored)
        days[best_index].append(stop)

    return days


def _rebalance_activities(day_stops: list[list[Place]]) -> list[list[Place]]:
    """Move activities from over-full days to under-filled ones to even out stop counts."""
    MIN_ACTIVITIES = 2
    rebalanced = [list(stops) for stops in day_stops]
    changed = True
    guard = 0
    while changed and guard < 20:
        changed = False
        guard += 1
        activity_counts = [
            sum(1 for s in day if not _is_restaurant(s) and not _is_market(s))
            for day in rebalanced
        ]
        thin_days = [i for i, c in enumerate(activity_counts) if c < MIN_ACTIVITIES]
        if not thin_days:
            break
        target_index = thin_days[0]
        donor_index = max(
            range(len(rebalanced)),
            key=lambda i: activity_counts[i],
        )
        if donor_index == target_index or activity_counts[donor_index] <= MIN_ACTIVITIES:
            break
        donor_activities = [
            s for s in rebalanced[donor_index]
            if not _is_restaurant(s) and not _is_market(s)
        ]
        # Pick the donor activity closest to the thin day's centroid
        centroid_lat, centroid_lon = _day_centroid(rebalanced[target_index])
        best = min(
            donor_activities,
            key=lambda s: _haversine(s.latitude, s.longitude, centroid_lat, centroid_lon),
        )
        closest_leg = _closest_leg_minutes(best, rebalanced[target_index])
        if closest_leg > MAX_DAY_LEG_MINUTES and rebalanced[target_index]:
            break
        rebalanced[donor_index] = [s for s in rebalanced[donor_index] if _place_key(s) != _place_key(best)]
        rebalanced[target_index].append(best)
        changed = True
    return rebalanced


def _enforce_max_leg_minutes(day_stops: list[list[Place]]) -> list[list[Place]]:
    rebalanced = [list(stops) for stops in day_stops]
    changed = True
    guard = 0
    while changed and guard < 24:
        changed = False
        guard += 1
        for day_index, stops in enumerate(rebalanced):
            if len(stops) < 2:
                continue
            ordered = _nearest_neighbor_sort(stops)
            for stop_index in range(1, len(ordered)):
                if _estimated_leg_minutes(ordered[stop_index - 1], ordered[stop_index]) <= MAX_DAY_LEG_MINUTES:
                    continue
                moved = ordered[stop_index]
                destination_scores: list[tuple[int, int, int]] = []
                for candidate_index, candidate_day in enumerate(rebalanced):
                    if candidate_index == day_index:
                        continue
                    candidate_leg = _closest_leg_minutes(moved, candidate_day)
                    destination_scores.append(
                        (
                            0 if candidate_leg <= MAX_DAY_LEG_MINUTES else 1,
                            candidate_leg,
                            candidate_index,
                        )
                    )
                if not destination_scores:
                    continue
                _, _, best_index = min(destination_scores)
                rebalanced[day_index] = [
                    stop for stop in rebalanced[day_index] if _place_key(stop) != _place_key(moved)
                ]
                rebalanced[best_index].append(moved)
                changed = True
                break
            if changed:
                break
    return rebalanced


def _anchor_minutes(anchor: LocationAnchor | None, stop: Place) -> int:
    if not anchor:
        return 0
    return _estimated_anchor_leg_minutes(anchor, stop)


def _has_long_route_leg(stops: list[Place]) -> bool:
    return any(
        _estimated_leg_minutes(stops[index - 1], stops[index]) > MAX_DAY_LEG_MINUTES
        for index in range(1, len(stops))
    )


def _best_leg_limited_route(stops: list[Place], anchor: LocationAnchor | None) -> list[Place]:
    """Choose the longest readable route whose displayed legs stay under the limit."""
    candidates = _unique_places(stops)
    if len(candidates) <= 1:
        return candidates

    max_route_size = min(MAX_STOPS_PER_DAY, len(candidates))
    starts = sorted(
        candidates,
        key=lambda stop: (
            _anchor_minutes(anchor, stop),
            stop.city.lower(),
            stop.name.lower(),
        ),
    )
    best_route: list[Place] = []
    best_score: tuple[int, float, int] | None = None

    for start in starts:
        route = [start]
        remaining = [stop for stop in candidates if _place_key(stop) != _place_key(start)]
        while remaining and len(route) < max_route_size:
            reachable = [
                stop
                for stop in remaining
                if _estimated_leg_minutes(route[-1], stop) <= MAX_DAY_LEG_MINUTES
            ]
            if not reachable:
                break
            next_stop = min(
                reachable,
                key=lambda stop: (
                    _estimated_leg_minutes(route[-1], stop),
                    _haversine(route[-1].latitude, route[-1].longitude, stop.latitude, stop.longitude),
                    stop.name.lower(),
                ),
            )
            route.append(next_stop)
            remaining = [stop for stop in remaining if _place_key(stop) != _place_key(next_stop)]

        score = (len(route), -_route_distance(route), -_anchor_minutes(anchor, route[0]))
        if best_score is None or score > best_score:
            best_score = score
            best_route = route

    if best_route:
        return best_route

    ordered = _sort_from_anchor(candidates, anchor)[:max_route_size]
    if _has_long_route_leg(ordered):
        return ordered[:1]
    return ordered


def _rebalance_output_days(days: list[ItineraryDay], anchor: LocationAnchor | None) -> list[ItineraryDay]:
    changed = True
    guard = 0
    while changed and guard < 40:
        changed = False
        guard += 1
        thin_indexes = [
            index for index, day in enumerate(days) if len(day.stops) < MIN_STOPS_PER_DAY
        ]
        if not thin_indexes:
            break
        for thin_index in thin_indexes:
            thin_day = days[thin_index]
            donor_indexes = [
                index
                for index, day in enumerate(days)
                if index != thin_index and len(day.stops) > MIN_STOPS_PER_DAY
            ]
            best_move: tuple[int, int, int, Place, list[Place]] | None = None
            for donor_index in donor_indexes:
                donor_day = days[donor_index]
                for candidate in donor_day.stops:
                    repaired = _best_leg_limited_route(thin_day.stops + [candidate], anchor)
                    if len(repaired) <= len(thin_day.stops):
                        continue
                    closest_leg = _closest_leg_minutes(candidate, thin_day.stops)
                    move_score = (closest_leg, len(donor_day.stops))
                    if best_move is None or move_score < (best_move[0], best_move[1]):
                        best_move = (closest_leg, len(donor_day.stops), donor_index, candidate, repaired)
            if best_move is None:
                movable: list[Place] = []
                donor_for_key: dict[tuple[str, str], int] = {}
                donor_quota: dict[int, int] = {}
                city_spares: dict[str, list[Place]] = {}
                for donor_index in donor_indexes:
                    quota = len(days[donor_index].stops) - MIN_STOPS_PER_DAY
                    donor_quota[donor_index] = quota
                    if quota <= 0:
                        continue
                    city_used_from_donor: dict[str, int] = {}
                    for stop in days[donor_index].stops:
                        movable.append(stop)
                        donor_for_key[_place_key(stop)] = donor_index
                        city_key = stop.city.lower()
                        if city_used_from_donor.get(city_key, 0) < quota:
                            city_spares.setdefault(city_key, []).append(stop)
                            city_used_from_donor[city_key] = city_used_from_donor.get(city_key, 0) + 1
                city_replacements = sorted(
                    (
                        _best_leg_limited_route(candidates, anchor)
                        for candidates in city_spares.values()
                        if len(candidates) >= MIN_STOPS_PER_DAY
                    ),
                    key=lambda route: (len(route), -_route_distance(route)),
                    reverse=True,
                )
                if city_replacements and len(city_replacements[0]) >= MIN_STOPS_PER_DAY:
                    selected = city_replacements[0][:MAX_STOPS_PER_DAY]
                    selected_keys = {_place_key(stop) for stop in selected}
                    for donor_index in donor_indexes:
                        days[donor_index].stops = [
                            stop for stop in days[donor_index].stops if _place_key(stop) not in selected_keys
                        ]
                        days[donor_index].stops = _best_leg_limited_route(days[donor_index].stops, anchor)
                    thin_day.stops = selected
                    changed = True
                    break
                replacement = _best_leg_limited_route(movable, anchor)
                selected: list[Place] = []
                used_quota: dict[int, int] = {}
                for stop in replacement:
                    donor_index = donor_for_key.get(_place_key(stop))
                    if donor_index is None:
                        continue
                    if used_quota.get(donor_index, 0) >= donor_quota.get(donor_index, 0):
                        continue
                    selected.append(stop)
                    used_quota[donor_index] = used_quota.get(donor_index, 0) + 1
                    if len(selected) >= MIN_STOPS_PER_DAY:
                        break
                if len(selected) < MIN_STOPS_PER_DAY:
                    continue
                selected_keys = {_place_key(stop) for stop in selected}
                for donor_index in donor_indexes:
                    days[donor_index].stops = [
                        stop for stop in days[donor_index].stops if _place_key(stop) not in selected_keys
                    ]
                    days[donor_index].stops = _best_leg_limited_route(days[donor_index].stops, anchor)
                thin_day.stops = selected
                changed = True
                break
            _, _, donor_index, moved, repaired_thin = best_move
            donor_day = days[donor_index]
            donor_day.stops = [
                stop for stop in donor_day.stops if _place_key(stop) != _place_key(moved)
            ]
            donor_day.stops = _best_leg_limited_route(donor_day.stops, anchor)
            thin_day.stops = repaired_thin
            changed = True
            if len(thin_day.stops) >= MIN_STOPS_PER_DAY:
                break
    return days


def _replace_underfilled_days_from_unused(
    days: list[ItineraryDay],
    all_candidates: list[Place],
    anchor: LocationAnchor | None,
) -> list[ItineraryDay]:
    used_keys = {
        _place_key(stop)
        for day in days
        for stop in day.stops
    }
    for day in days:
        if len(day.stops) >= MIN_STOPS_PER_DAY:
            continue
        current_keys = {_place_key(stop) for stop in day.stops}
        unused = [
            stop
            for stop in all_candidates
            if _place_key(stop) not in used_keys or _place_key(stop) in current_keys
        ]
        replacement = _best_leg_limited_route(unused, anchor)
        if len(replacement) < MIN_STOPS_PER_DAY:
            continue
        used_keys.difference_update(current_keys)
        day.stops = replacement[:MAX_STOPS_PER_DAY]
        used_keys.update(_place_key(stop) for stop in day.stops)
    return days


def _ensure_day_count(days: list[ItineraryDay], day_count: int) -> list[ItineraryDay]:
    """Keep the exact requested trip length — trim excess days, pad if short."""
    # Trim: strip any extra days the planner may have emitted
    if len(days) > day_count:
        return [
            day.model_copy(update={"day": index + 1})
            for index, day in enumerate(days[:day_count])
        ]

    if len(days) == day_count:
        return days

    # Pad: add placeholder days when the candidate pool is too small
    balanced = list(days)
    while len(balanced) < day_count:
        donor = max(balanced, key=lambda day: len(day.stops), default=None)
        moved_stop = donor.stops.pop() if donor and len(donor.stops) > 1 else None
        balanced.append(ItineraryDay(
            day=len(balanced) + 1,
            title=f"Day {len(balanced) + 1} - Local mixed day",
            summary="A lighter day because the available candidate pool is limited.",
            stops=[moved_stop] if moved_stop else [],
        ))

    return [
        day.model_copy(update={"day": index + 1})
        for index, day in enumerate(balanced[:day_count])
    ]


def _rebalance_day_stop_counts(day_stops: list[list[Place]]) -> list[list[Place]]:
    """Keep day sizes readable: 4-6 stops when the candidate pool is large enough."""
    rebalanced = [list(stops) for stops in day_stops]
    if not rebalanced:
        return rebalanced

    total_stops = sum(len(day) for day in rebalanced)
    if total_stops < len(rebalanced) * MIN_STOPS_PER_DAY:
        return rebalanced

    changed = True
    guard = 0
    while changed and guard < 80:
        changed = False
        guard += 1
        thin_indexes = [
            index for index, day in enumerate(rebalanced) if len(day) < MIN_STOPS_PER_DAY
        ]
        if not thin_indexes:
            break

        target_index = min(thin_indexes, key=lambda index: len(rebalanced[index]))
        donor_indexes = [
            index
            for index, day in enumerate(rebalanced)
            if index != target_index and len(day) > MIN_STOPS_PER_DAY
        ]
        if not donor_indexes:
            break

        donor_index = max(donor_indexes, key=lambda index: len(rebalanced[index]))
        centroid_lat, centroid_lon = _day_centroid(rebalanced[target_index])
        donor_candidates = sorted(
            rebalanced[donor_index],
            key=lambda stop: _haversine(stop.latitude, stop.longitude, centroid_lat, centroid_lon),
        )
        moved = next(
            (
                stop
                for stop in donor_candidates
                if not rebalanced[target_index]
                or _closest_leg_minutes(stop, rebalanced[target_index]) <= MAX_DAY_LEG_MINUTES
            ),
            None,
        )
        if moved is None:
            break
        rebalanced[donor_index] = [
            stop for stop in rebalanced[donor_index] if _place_key(stop) != _place_key(moved)
        ]
        rebalanced[target_index].append(moved)
        changed = True

    # If a day is still oversized, move its least disruptive extras to smaller days.
    changed = True
    guard = 0
    while changed and guard < 80:
        changed = False
        guard += 1
        oversized = [
            index for index, day in enumerate(rebalanced) if len(day) > MAX_STOPS_PER_DAY
        ]
        receivers = [
            index for index, day in enumerate(rebalanced) if len(day) < MAX_STOPS_PER_DAY
        ]
        if not oversized or not receivers:
            break

        donor_index = max(oversized, key=lambda index: len(rebalanced[index]))
        receiver_index = min(receivers, key=lambda index: len(rebalanced[index]))
        centroid_lat, centroid_lon = _day_centroid(rebalanced[receiver_index])
        donor_candidates = sorted(
            rebalanced[donor_index],
            key=lambda stop: _haversine(stop.latitude, stop.longitude, centroid_lat, centroid_lon),
        )
        moved = next(
            (
                stop
                for stop in donor_candidates
                if not rebalanced[receiver_index]
                or _closest_leg_minutes(stop, rebalanced[receiver_index]) <= MAX_DAY_LEG_MINUTES
            ),
            None,
        )
        if moved is None:
            break
        rebalanced[donor_index] = [
            stop for stop in rebalanced[donor_index] if _place_key(stop) != _place_key(moved)
        ]
        rebalanced[receiver_index].append(moved)
        changed = True

    return rebalanced


# Time labels for each slot position when the slot-based planner chose the stops.
# Index matches the slot sequence in day_planner.SLOT_SEQUENCE.
_SLOT_TIME_LABELS = [
    "09:00 morning landmark",
    "10:30 cafe / local pause",
    "12:30 lunch",
    "14:30 afternoon culture or wander",
    "17:00 early evening stroll",
    "19:00 dinner",
]

# Which slot types are "food" for the purpose of time-label assignment
_FOOD_SLOT_TYPES = {"cafe_or_local_food"}


def _assign_time_labels_in_order(stops: list[Place]) -> list[Place]:
    """
    Assign time labels purely by position, preserving the slot-planner's chosen order.
    No re-sorting for distance — that is handled by the slot planner's distance term.
    """
    result = []
    for i, place in enumerate(stops):
        label = _SLOT_TIME_LABELS[i] if i < len(_SLOT_TIME_LABELS) else "19:30 extra stop"
        result.append(_with_time(place, label))
    return result


DAY_THEMES = [
    {
        "label": "Sightseeing day",
        "summary": "Classic first-time sights with lunch and dinner built in so the route stays realistic.",
        "matcher": _is_must_go,
        "min_matches": 2,
    },
    {
        "label": "Museum hopping day",
        "summary": "A culture-heavy day with museums or galleries, balanced by meal breaks.",
        "matcher": _is_museum,
        "min_matches": 2,
    },
    {
        "label": "Shopping day",
        "summary": "A browsing-focused day for boutiques, souvenirs, vintage, or department-store stops.",
        "matcher": _is_shopping,
        "min_matches": 2,
    },
    {
        "label": "Neighborhood wandering day",
        "summary": "A slower day for parks, viewpoints, markets, and local streets.",
        "matcher": _is_walk_or_park,
        "min_matches": 2,
    },
]


def _day_theme_for(day_index: int, stops: list[Place]) -> dict:
    scored_themes: list[tuple[int, int, dict]] = []
    for priority, theme in enumerate(DAY_THEMES):
        score = sum(1 for stop in stops if theme["matcher"](stop))
        if score >= theme.get("min_matches", 1):
            scored_themes.append((score, -priority, theme))
    if scored_themes:
        scored_themes.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return scored_themes[0][2]
    return {
        "label": "Local mixed day",
        "summary": "A balanced day with local-feeling stops and meal breaks.",
        "matcher": _is_activity,
    }


def _unique_places(stops: list[Place]) -> list[Place]:
    unique = []
    seen: set[tuple[str, str]] = set()
    for stop in stops:
        key = _place_key(stop)
        if key in seen:
            continue
        seen.add(key)
        unique.append(stop)
    return unique


def _schedule_day_stops(
    stops: list[Place],
    force_full_day: bool = False,
    theme_matcher=None,
) -> list[Place]:
    used: set[tuple[str, str]] = set()
    meal_matcher = lambda place: _is_restaurant(place) or _is_market(place)
    activity_matcher = theme_matcher or _is_activity
    fallback_activity = lambda place: activity_matcher(place) or _is_activity(place)

    planned_slots: list[tuple[str, Place | None]] = [
        ("09:00 morning neighborhood start", _take_first(stops, used, fallback_activity)),
        ("10:30 cafe / local pause", _take_first(stops, used, _is_cafe)),
        ("12:30 lunch", _take_first(stops, used, meal_matcher)),
        ("14:30 afternoon culture or wander", _take_first(stops, used, fallback_activity)),
        ("17:00 early evening stroll", _take_first(stops, used, _is_activity)),
        ("19:00 dinner", _take_first(stops, used, meal_matcher)),
    ]

    if force_full_day:
        filled_slots = list(planned_slots)
        empty_indexes = [
            index for index, (_, place) in enumerate(filled_slots) if place is None
        ]
        remaining_places = _fill_remaining(
            stops,
            used,
            min(len(stops), 4) - sum(1 for _, place in filled_slots if place is not None),
        )
        for index, place in zip(empty_indexes, remaining_places):
            time_label, _ = filled_slots[index]
            filled_slots[index] = (_adjust_filler_time_label(time_label, place), place)
        planned_slots = filled_slots

    scheduled = [
        _with_time(place, time_label)
        for time_label, place in planned_slots
        if place is not None
    ]

    return scheduled


def split_stops_by_day(
    stops: list[Place],
    duration_days: int,
    force_full_day: bool = False,
    stay_anchor: LocationAnchor | None = None,
    intent: TravelIntent | None = None,
) -> list[ItineraryDay]:
    day_count = max(1, min(duration_days, 14))
    unique_stops = _unique_places(stops)
    city_counts: dict[str, int] = {}
    for stop in unique_stops:
        city_counts[stop.city.lower()] = city_counts.get(stop.city.lower(), 0) + 1
    clustered_stops = [
        stop
        for stop in unique_stops
        if city_counts.get(stop.city.lower(), 0) >= MIN_STOPS_PER_DAY
    ]
    if len(clustered_stops) >= day_count * MIN_STOPS_PER_DAY:
        unique_stops = clustered_stops
    photo_backed_stops = [stop for stop in unique_stops if _has_display_photo(stop)]
    if len(photo_backed_stops) >= day_count * MIN_STOPS_PER_DAY:
        unique_stops = photo_backed_stops
    # ── Slot-based day composition ──────────────────────────────────────────
    # Build each day using typed slots (must_go_landmark / cafe_or_local_food /
    # hidden_gem / museum_or_culture / scenic_walk_or_open_area / dinner).
    # Meals are included naturally via cafe_or_local_food slots — no separate
    # meal-distribution pass is needed.
    is_slot_based = intent is not None
    if is_slot_based:
        slot_intent = intent.model_copy(update={"duration_days": day_count})
        day_stops = _slot_build_days(unique_stops, slot_intent)
    else:
        # Fallback: classic geographic clustering when no intent is available
        meals = [s for s in unique_stops if _is_restaurant(s) or _is_market(s)]
        activities = [s for s in unique_stops if s not in meals] or unique_stops
        day_stops = _cluster_days_by_location(activities, day_count)
        MAX_MEALS_PER_DAY = 2
        for meal in meals:
            scored: list[tuple[int, int, int, float, int, int]] = []
            for index, current_day in enumerate(day_stops):
                centroid_lat, centroid_lon = _day_centroid(current_day)
                closest_leg = _closest_leg_minutes(meal, current_day)
                centroid_distance = _haversine(
                    meal.latitude, meal.longitude, centroid_lat, centroid_lon
                )
                meals_in_day = sum(1 for s in current_day if _is_restaurant(s) or _is_market(s))
                meal_cap_penalty = 1 if meals_in_day >= MAX_MEALS_PER_DAY else 0
                scored.append(
                    (meal_cap_penalty, 0 if closest_leg <= MAX_DAY_LEG_MINUTES else 1,
                     closest_leg, centroid_distance, len(current_day), index)
                )
            _, _, _, _, _, best_index = min(scored)
            day_stops[best_index].append(meal)
    while len(day_stops) < day_count:
        day_stops.append([])

    day_stops = _enforce_max_leg_minutes(day_stops)
    day_stops = _rebalance_activities(day_stops)
    day_stops = _enforce_max_leg_minutes(day_stops)

    days: list[ItineraryDay] = []
    day_stops = _rebalance_day_stop_counts(day_stops)
    day_stops = _enforce_max_leg_minutes(day_stops)
    for index, stops_for_day in enumerate(day_stops):
        if not stops_for_day:
            continue

        if is_slot_based:
            # Slot-based path: the planner already chose stops in time order
            # (landmark → cafe → gem → museum → walk → dinner).
            # Assign time labels by position — do NOT reorder for distance, which
            # would destroy the semantic time structure (e.g., dinner at 09:00).
            scheduled_stops = _assign_time_labels_in_order(
                stops_for_day[:MAX_STOPS_PER_DAY]
            )
        else:
            # Classic path: schedule by type matchers, then route-optimise.
            scheduled_stops = _schedule_day_stops(
                stops_for_day,
                force_full_day=True,
                theme_matcher=_day_theme_for(index, stops_for_day)["matcher"],
            )
            if len(scheduled_stops) < MIN_STOPS_PER_DAY:
                used_keys = {_place_key(stop) for stop in scheduled_stops}
                extras = [
                    stop for stop in stops_for_day if _place_key(stop) not in used_keys
                ]
                for extra in extras:
                    if len(scheduled_stops) >= MIN_STOPS_PER_DAY:
                        break
                    scheduled_stops.append(extra)
            route_candidates = scheduled_stops + [
                stop
                for stop in stops_for_day
                if _place_key(stop) not in {_place_key(e) for e in scheduled_stops}
            ]
            scheduled_stops = _best_leg_limited_route(route_candidates, stay_anchor)

        theme = _day_theme_for(index, scheduled_stops)
        days.append(ItineraryDay(
            day=index + 1,
            title=f"Day {index + 1} - {theme['label']}",
            summary=(
                f"{theme['summary']} Start around 09:00, plan lunch around 12:30, "
                "and finish with dinner around 19:00 when food stops are available."
            ),
            stops=scheduled_stops,
        ))
    days = _rebalance_output_days(days, stay_anchor)
    days = _replace_underfilled_days_from_unused(days, unique_stops, stay_anchor)
    return _ensure_day_count(days, day_count)


def build_itinerary(
    intent: TravelIntent,
    places: list[Place],
    stay_anchor: LocationAnchor | None = None,
) -> Itinerary:
    if not places:
        raise ValueError("No candidate places were found for this request.")

    themes = list(dict.fromkeys(intent.interests))[:4]
    day_label = "1-day" if intent.duration_days == 1 else f"{intent.duration_days}-day"
    summary = (
        f"A {day_label} {intent.pace} itinerary in {intent.destination} "
        f"matching {', '.join(intent.request_intents or ['travel planning'])} with "
        "route logic, meal breaks, and evidence-backed stops."
    )
    avoidance_notes = [
        "Prioritized places with lower tourist-trap risk.",
        "Recommended morning or neighborhood-first visits where helpful.",
    ]
    force_full_day = "mixed" in {interest.lower() for interest in intent.interests}
    scheduled_days = split_stops_by_day(
        places,
        intent.duration_days,
        force_full_day=force_full_day,
        stay_anchor=stay_anchor,
        intent=intent,
    )
    scheduled_stops = [
        stop for day in scheduled_days for stop in day.stops
    ] or places

    return Itinerary(
        title=f"{intent.destination} Local Explorer Plan",
        summary=summary,
        destination=intent.destination,
        themes=themes,
        stops=scheduled_stops,
        days=scheduled_days,
        avoidance_notes=avoidance_notes,
        start_location=stay_anchor,
        practical_notes=[
            "This plan assumes you start touring at 09:00.",
            "Lunch is planned around 12:30 and dinner around 19:00 when suitable food stops are available.",
            "Open each stop on the map before leaving so transit choices stay realistic.",
            "Treat market timings as flexible; many local markets are strongest in the morning.",
            *intent.assumptions,
        ],
    )
