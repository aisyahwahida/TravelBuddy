from app.schemas.travel import Itinerary, ItineraryDay, Place, TravelIntent


def _tags(place: Place) -> set[str]:
    return {tag.lower() for tag in place.tags}


def _haystack(place: Place) -> str:
    return f"{place.category} {place.name}".lower()


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
    return bool({"museum", "museums", "gallery", "art"}.intersection(tags)) or any(
        term in _haystack(place) for term in ("museum", "musee", "gallery")
    )


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
        key = (place.name, place.city)
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
        key = (place.name, place.city)
        if key in used:
            continue
        used.add(key)
        remaining.append(place)
    return remaining


DAY_THEMES = [
    {
        "label": "Sightseeing day",
        "summary": "Classic first-time sights with lunch and dinner built in so the route stays realistic.",
        "matcher": _is_must_go,
    },
    {
        "label": "Museum hopping day",
        "summary": "A culture-heavy day with museums or galleries, balanced by meal breaks.",
        "matcher": _is_museum,
    },
    {
        "label": "Shopping day",
        "summary": "A browsing-focused day for boutiques, souvenirs, vintage, or department-store stops.",
        "matcher": _is_shopping,
    },
    {
        "label": "Neighborhood wandering day",
        "summary": "A slower day for parks, viewpoints, markets, and local streets.",
        "matcher": _is_walk_or_park,
    },
]


def _day_theme_for(day_index: int, stops: list[Place]) -> dict:
    available = [theme for theme in DAY_THEMES if any(theme["matcher"](stop) for stop in stops)]
    if available:
        return available[day_index % len(available)]
    return {
        "label": "Local mixed day",
        "summary": "A balanced day with local-feeling stops and meal breaks.",
        "matcher": _is_activity,
    }


def _unique_places(stops: list[Place]) -> list[Place]:
    unique = []
    seen: set[tuple[str, str]] = set()
    for stop in stops:
        key = (stop.name.lower(), stop.city.lower())
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
) -> list[ItineraryDay]:
    day_count = max(1, min(duration_days, 14))
    unique_stops = _unique_places(stops)
    meals = [stop for stop in unique_stops if _is_restaurant(stop) or _is_market(stop)]
    activities = [stop for stop in unique_stops if stop not in meals]
    day_stops: list[list[Place]] = [[] for _ in range(day_count)]

    for index, stop in enumerate(activities):
        day_stops[index % day_count].append(stop)
    for index, meal in enumerate(meals):
        day_stops[index % day_count].append(meal)

    days: list[ItineraryDay] = []
    for index, stops_for_day in enumerate(day_stops):
        if not stops_for_day:
            continue
        theme = _day_theme_for(index, stops_for_day)
        scheduled_stops = _schedule_day_stops(
            stops_for_day,
            force_full_day=force_full_day,
            theme_matcher=theme["matcher"],
        )
        days.append(ItineraryDay(
            day=index + 1,
            title=f"Day {index + 1} - {theme['label']}",
            summary=(
                f"{theme['summary']} Start around 09:00, plan lunch around 12:30, "
                "and finish with dinner around 19:00 when food stops are available."
            ),
            stops=scheduled_stops,
        ))
    return days


def build_itinerary(intent: TravelIntent, places: list[Place]) -> Itinerary:
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
        practical_notes=[
            "This plan assumes you start touring at 09:00.",
            "Lunch is planned around 12:30 and dinner around 19:00 when suitable food stops are available.",
            "Open each stop on the map before leaving so transit choices stay realistic.",
            "Treat market timings as flexible; many local markets are strongest in the morning.",
            *intent.assumptions,
        ],
    )
