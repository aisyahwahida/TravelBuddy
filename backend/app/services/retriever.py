import json
from pathlib import Path

from app.data.france_places import FRANCE_PLACES
from app.schemas.travel import Place, TravelIntent
from app.services.reranker import rerank_places
from app.services.semantic_retrieval import semantic_scores

REDDIT_PLACES_PATH = Path(__file__).resolve().parents[1] / "data" / "reddit_places.json"
GOOGLE_PLACES_PATH = Path(__file__).resolve().parents[1] / "data" / "google_places.json"
OSM_PLACES_PATH = Path(__file__).resolve().parents[1] / "data" / "osm_places.json"
OSM_POI_PLACES_PATH = Path(__file__).resolve().parents[1] / "data" / "osm_poi_places.json"
OPEN_DATA_PLACES_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "open_data_places.json"
)
MUST_GO_PLACES_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "france_must_go_places.json"
)


def _google_maps_url(latitude: float, longitude: float, name: str) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={latitude},{longitude}"


def _load_reddit_places() -> list[dict]:
    if not REDDIT_PLACES_PATH.exists():
        return []

    try:
        payload = json.loads(REDDIT_PLACES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    if isinstance(payload, dict):
        return payload.get("places", [])
    if isinstance(payload, list):
        return payload
    return []


def _load_google_places() -> dict[str, dict]:
    if not GOOGLE_PLACES_PATH.exists():
        return {}

    try:
        payload = json.loads(GOOGLE_PLACES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}

    places = payload.get("places", []) if isinstance(payload, dict) else []
    return {
        f"{place.get('name', '').lower()}::{place.get('city', '').lower()}": place
        for place in places
    }


def _load_osm_places() -> dict[str, dict]:
    if not OSM_PLACES_PATH.exists():
        return {}

    try:
        payload = json.loads(OSM_PLACES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}

    places = payload.get("places", []) if isinstance(payload, dict) else []
    return {
        f"{place.get('name', '').lower()}::{place.get('city', '').lower()}": place
        for place in places
    }


def _load_open_data_places() -> list[dict]:
    if not OPEN_DATA_PLACES_PATH.exists():
        return []

    try:
        payload = json.loads(OPEN_DATA_PLACES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    if isinstance(payload, dict):
        return payload.get("places", [])
    if isinstance(payload, list):
        return payload
    return []


def _load_osm_poi_places() -> list[dict]:
    if not OSM_POI_PLACES_PATH.exists():
        return []

    try:
        payload = json.loads(OSM_POI_PLACES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    if isinstance(payload, dict):
        return payload.get("places", [])
    if isinstance(payload, list):
        return payload
    return []


def _load_must_go_places() -> list[dict]:
    if not MUST_GO_PLACES_PATH.exists():
        return []

    try:
        payload = json.loads(MUST_GO_PLACES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    if isinstance(payload, dict):
        return payload.get("places", [])
    if isinstance(payload, list):
        return payload
    return []


def _all_places(include_must_go: bool = False) -> list[dict]:
    google_places = _load_google_places()
    osm_places = _load_osm_places()
    merged: list[dict] = []

    for place in [
        *FRANCE_PLACES,
        *_load_reddit_places(),
        *_load_open_data_places(),
        *_load_osm_poi_places(),
        *(_load_must_go_places() if include_must_go else []),
    ]:
        key = f"{place.get('name', '').lower()}::{place.get('city', '').lower()}"
        osm_match = osm_places.get(key)
        if osm_match:
            place = {
                **place,
                "neighborhood": osm_match.get("neighborhood")
                or place.get("neighborhood", ""),
                "address": osm_match.get("display_name")
                or place.get("address", ""),
                "category": osm_match.get("category") or place.get("category", ""),
                "latitude": osm_match.get("latitude", place.get("latitude")),
                "longitude": osm_match.get("longitude", place.get("longitude")),
                "google_maps_url": osm_match.get("map_url")
                or place.get("google_maps_url", ""),
                "map_source": "OpenStreetMap",
                "map_url": osm_match.get("map_url", ""),
                "price_label": osm_match.get("price_label", ""),
                "business_status": osm_match.get("business_status", ""),
                "opening_hours": osm_match.get("opening_hours", []),
                "open_now": osm_match.get("open_now"),
                "source_type": "openstreetmap",
                "source_title": osm_match.get(
                    "source_title", "OpenStreetMap place details"
                ),
                "source_url": osm_match.get("source_url", ""),
            }
        google_match = google_places.get(key)
        if google_match:
            place = {
                **place,
                "google_maps_url": google_match.get("google_maps_url")
                or place.get("google_maps_url", ""),
                "map_source": "Google Maps",
                "map_url": google_match.get("google_maps_url")
                or place.get("google_maps_url", ""),
                "price_label": google_match.get("price_label", ""),
                "source_type": "google_maps",
                "source_title": google_match.get("source_title", "Google Maps reviews"),
                "source_url": google_match.get("source_url", ""),
                "google_rating": google_match.get("rating"),
                "google_user_rating_count": google_match.get("user_rating_count"),
                "google_price_level": google_match.get("price_level", ""),
                "google_price_label": google_match.get("price_label", ""),
                "business_status": google_match.get("business_status", ""),
                "opening_hours": google_match.get("opening_hours", []),
                "open_now": google_match.get("open_now"),
            }
        merged.append(place)

    return merged


def _has_cafe_intent(intent: TravelIntent) -> bool:
    cafe_terms = {"cafe", "cafes", "coffee", "coffee shops", "espresso"}
    return bool(cafe_terms.intersection({item.lower() for item in intent.interests}))


def _is_cafe_only_intent(intent: TravelIntent) -> bool:
    interests = {item.lower() for item in intent.interests}
    non_cafe_interests = interests - {"cafe", "cafes", "coffee", "coffee shops", "espresso"}
    return _has_cafe_intent(intent) and not non_cafe_interests


def _is_cafe_place(place: dict) -> bool:
    tags = {tag.lower() for tag in place.get("tags", [])}
    haystack = f"{place.get('category', '')} {place.get('name', '')}".lower()
    return bool({"coffee", "espresso"}.intersection(tags)) or any(
        term in haystack for term in ("cafe", "coffee", "espresso")
    )


def _is_market_place(place: dict) -> bool:
    tags = {tag.lower() for tag in place.get("tags", [])}
    haystack = f"{place.get('category', '')} {place.get('name', '')}".lower()
    return bool({"market", "markets", "marketplace"}.intersection(tags)) or any(
        term in haystack for term in ("market", "marketplace", "marche")
    )


def _is_museum_place(place: dict) -> bool:
    tags = {tag.lower() for tag in place.get("tags", [])}
    haystack = f"{place.get('category', '')} {place.get('name', '')}".lower()
    return bool({"museum", "museums", "gallery"}.intersection(tags)) or any(
        term in haystack for term in ("museum", "musee", "gallery")
    )


def _is_park_place(place: dict) -> bool:
    tags = {tag.lower() for tag in place.get("tags", [])}
    category = place.get("category", "").lower()
    return bool({"park", "parks", "garden", "gardens"}.intersection(tags)) or any(
        term in category for term in ("park", "garden")
    )


def _is_book_place(place: dict) -> bool:
    tags = {tag.lower() for tag in place.get("tags", [])}
    haystack = f"{place.get('category', '')} {place.get('name', '')}".lower()
    return bool({"bookstores", "books", "library", "libraries"}.intersection(tags)) or any(
        term in haystack for term in ("book", "library", "librairie")
    )


def _is_shopping_place(place: dict) -> bool:
    tags = {tag.lower() for tag in place.get("tags", [])}
    haystack = f"{place.get('category', '')} {place.get('name', '')}".lower()
    shopping_terms = {
        "shopping",
        "shop",
        "shops",
        "souvenir",
        "souvenirs",
        "gift",
        "gifts",
        "vintage",
        "thrift",
        "friperie",
        "flea market",
        "antiques",
        "luxury",
        "high-end",
        "high end",
        "brand",
        "brands",
        "designer",
        "fashion",
        "department store",
        "mall",
        "boutique",
        "boutiques",
        "skincare",
        "cosmetics",
        "pharmacy",
        "crafts",
        "artisan",
    }
    return bool(shopping_terms.intersection(tags)) or any(
        term in haystack
        for term in (
            "shop",
            "shopping",
            "souvenir",
            "gift",
            "vintage",
            "thrift",
            "friperie",
            "flea",
            "antique",
            "luxury",
            "designer",
            "fashion",
            "department store",
            "mall",
            "boutique",
            "pharmacy",
            "craft",
            "artisan",
        )
    )


def _is_event_place(place: dict) -> bool:
    tags = {tag.lower() for tag in place.get("tags", [])}
    haystack = f"{place.get('category', '')} {place.get('name', '')}".lower()
    return bool({"event", "events", "activity", "activities", "exhibition", "concert"}.intersection(tags)) or any(
        term in haystack for term in ("event", "activity", "exhibition", "concert")
    )


def _requested_place_matchers(intent: TravelIntent) -> list:
    interests = {item.lower() for item in intent.interests}
    matchers = []
    if {"cafe", "cafes", "coffee", "coffee shops"}.intersection(interests):
        matchers.append(_is_cafe_place)
    if {"market", "markets"}.intersection(interests):
        matchers.append(_is_market_place)
    if {"museum", "museums", "art", "exhibition", "exhibitions"}.intersection(interests):
        matchers.append(_is_museum_place)
    if {"park", "parks", "walks", "quiet"}.intersection(interests):
        matchers.append(_is_park_place)
    if {"bookstores", "library", "libraries"}.intersection(interests):
        matchers.append(_is_book_place)
    if {
        "shopping",
        "shop",
        "shops",
        "souvenir",
        "souvenirs",
        "gift",
        "gifts",
        "affordable shopping",
        "vintage",
        "thrift",
        "thrifting",
        "friperie",
        "flea market",
        "antiques",
        "luxury",
        "high-end",
        "high end",
        "brand",
        "brands",
        "designer",
        "fashion",
        "department store",
        "mall",
        "boutique",
        "boutiques",
        "skincare",
        "cosmetics",
        "pharmacy",
    }.intersection(interests):
        matchers.append(_is_shopping_place)
    if {"event", "events", "activity", "activities", "concert", "weekend"}.intersection(interests):
        matchers.append(_is_event_place)
    return matchers


def _matches_any_requested_type(place: dict, matchers: list) -> bool:
    return any(matcher(place) for matcher in matchers)


def _has_restaurant_intent(intent: TravelIntent) -> bool:
    food_terms = {"restaurant", "restaurants", "food", "lunch", "dinner", "eat"}
    return (
        bool(food_terms.intersection({item.lower() for item in intent.interests}))
        or "food_recommendation" in intent.request_intents
        or bool(intent.food_preference)
    )


def _is_food_only_intent(intent: TravelIntent) -> bool:
    interests = {item.lower() for item in intent.interests}
    food_terms = {
        "restaurant",
        "restaurants",
        "food",
        "lunch",
        "dinner",
        "eat",
        "asian",
        "japanese",
        "korean",
        "chinese",
        "thai",
        "vietnamese",
        "ramen",
        "sushi",
        "pho",
        "french",
        "bistro",
        "brasserie",
    }
    activity_intents = {
        "itinerary",
        "budget_plan",
        "romantic_plan",
        "quiet_plan",
        "family_trip",
        "nightlife_plan",
        "museum_plan",
        "walking_route",
        "shopping_plan",
        "must_go_plan",
        "rainy_day_plan",
    }
    return (
        _has_restaurant_intent(intent)
        and not (interests - food_terms)
        and not activity_intents.intersection(set(intent.request_intents))
    )


def _has_mixed_default_intent(intent: TravelIntent) -> bool:
    interests = {item.lower() for item in intent.interests}
    return "mixed" in interests


def _has_must_go_intent(intent: TravelIntent) -> bool:
    interests = {item.lower() for item in intent.interests}
    return bool({"must_go", "first_time", "iconic", "landmarks"}.intersection(interests))


def _is_restaurant_place(place: dict) -> bool:
    tags = {tag.lower() for tag in place.get("tags", [])}
    haystack = f"{place.get('category', '')} {place.get('name', '')}".lower()
    return "restaurant" in tags or "restaurant" in haystack or "bistro" in tags


def _is_indoor_candidate(place: dict) -> bool:
    if _is_market_place(place):
        return False
    return (
        _is_museum_place(place)
        or _is_shopping_place(place)
        or _is_cafe_place(place)
        or _is_restaurant_place(place)
        or _is_book_place(place)
        or _is_event_place(place)
    )


def _is_romantic_candidate(place: dict) -> bool:
    tags = {tag.lower() for tag in place.get("tags", [])}
    text = f"{place.get('category', '')} {place.get('name', '')} {place.get('reason', '')}".lower()
    return (
        _is_restaurant_place(place)
        or _is_cafe_place(place)
        or _is_park_place(place)
        or bool({"wine", "view", "views", "viewpoint", "garden", "romantic"}.intersection(tags))
        or any(term in text for term in ("wine", "view", "sunset", "garden", "romantic"))
    )


def _has_asian_food_intent(intent: TravelIntent) -> bool:
    asian_terms = {
        "asian",
        "japanese",
        "korean",
        "chinese",
        "thai",
        "vietnamese",
        "ramen",
        "sushi",
        "pho",
    }
    return bool(asian_terms.intersection({item.lower() for item in intent.interests}))


def _is_asian_restaurant(place: dict) -> bool:
    tags = {tag.lower() for tag in place.get("tags", [])}
    haystack = f"{place.get('category', '')} {place.get('name', '')}".lower()
    asian_terms = {
        "asian",
        "japanese",
        "korean",
        "chinese",
        "thai",
        "vietnamese",
        "ramen",
        "sushi",
        "pho",
        "noodles",
    }
    return (
        "restaurant" in tags
        and bool(asian_terms.intersection(tags))
    ) or (
        "restaurant" in haystack
        and any(term in haystack for term in asian_terms)
    )


def _specific_cuisine_terms(intent: TravelIntent) -> set[str]:
    specific_terms = {
        "french",
        "bistro",
        "brasserie",
        "japanese",
        "korean",
        "chinese",
        "thai",
        "vietnamese",
        "ramen",
        "sushi",
        "pho",
    }
    return specific_terms.intersection({item.lower() for item in intent.interests})


def _place_bucket(place: dict) -> str:
    if _is_cafe_place(place):
        return "cafe"
    if _is_market_place(place):
        return "market"
    if _is_museum_place(place):
        return "museum"
    if _is_park_place(place):
        return "park"
    if _is_event_place(place):
        return "event"
    if _is_book_place(place):
        return "book"
    if _is_shopping_place(place):
        return "shopping"
    if _is_restaurant_place(place):
        return "restaurant"
    return "local"


def _balanced_mixed_order(places: list[dict]) -> list[dict]:
    bucket_order = [
        "park",
        "cafe",
        "museum",
        "market",
        "event",
        "shopping",
        "restaurant",
        "book",
        "local",
    ]
    buckets: dict[str, list[dict]] = {bucket: [] for bucket in bucket_order}
    for place in places:
        buckets.setdefault(_place_bucket(place), []).append(place)

    balanced: list[dict] = []
    seen: set[tuple[str, str]] = set()
    while len(balanced) < len(places):
        added = False
        for bucket in bucket_order:
            if not buckets.get(bucket):
                continue
            place = buckets[bucket].pop(0)
            key = (place.get("name", ""), place.get("city", ""))
            if key in seen:
                continue
            balanced.append(place)
            seen.add(key)
            added = True
        if not added:
            break
    return balanced


def _rank_meal_candidates(candidates: list[dict]) -> list[dict]:
    scored = []
    asian_terms = {
        "asian",
        "japanese",
        "korean",
        "chinese",
        "thai",
        "vietnamese",
        "ramen",
        "sushi",
        "pho",
    }
    for place in candidates:
        score = 0
        tags = {tag.lower() for tag in place.get("tags", [])}
        haystack = f"{place.get('category', '')} {place.get('name', '')}".lower()
        if _is_restaurant_place(place):
            score += 8
        if _is_market_place(place):
            score += 5
        if {"french", "bistro", "brasserie", "wine", "traditional"}.intersection(tags):
            score += 5
        if any(term in haystack for term in ("french", "bistro", "brasserie", "wine bar")):
            score += 5
        if "local" in tags:
            score += 3
        if asian_terms.intersection(tags) or any(term in haystack for term in asian_terms):
            score -= 3
        if place.get("tourist_trap_risk") == "low":
            score += 3
        if place.get("source_type") in {"reddit", "openstreetmap", "google_maps"}:
            score += 2
        if place.get("source_url"):
            score += 1
        scored.append((score, place))
    return [place for _, place in sorted(scored, key=lambda item: item[0], reverse=True)]


def _rank_requested_regular(candidates: list[dict], intent: TravelIntent) -> list[dict]:
    interests = {interest.lower() for interest in intent.interests}
    scored = []
    for place in candidates:
        score = 0
        if {"shopping", "shop", "shops", "souvenir", "souvenirs", "vintage", "thrift"}.intersection(interests) and _is_shopping_place(place):
            score += 12
        if {"museum", "museums", "art", "exhibition", "exhibitions"}.intersection(interests) and _is_museum_place(place):
            score += 10
        if {"cafe", "cafes", "coffee", "coffee shops"}.intersection(interests) and _is_cafe_place(place):
            score += 8
        if {"park", "parks", "walks", "quiet"}.intersection(interests) and _is_park_place(place):
            score += 8
        if place.get("source_url"):
            score += 1
        scored.append((score, place))
    return [place for _, place in sorted(scored, key=lambda item: item[0], reverse=True)]


def _blend_multiday_with_meals(
    ranked_places: list[dict],
    intent: TravelIntent,
    all_regular_places: list[dict],
) -> list[dict]:
    if _is_cafe_only_intent(intent):
        return ranked_places

    regular_city_matches = [
        place
        for place in all_regular_places
        if intent.destination.lower() == "france"
        or place.get("city", "").lower() == intent.destination.lower()
    ]
    ranked_meals = _rank_meal_candidates(
        [
            place
            for place in regular_city_matches
            if _is_restaurant_place(place) or _is_market_place(place)
        ]
    )
    meal_target = min(len(ranked_meals), max(2, intent.duration_days * 2))
    target_count = min(24, max(8, intent.duration_days * 6))
    blended: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(place: dict | None) -> None:
        if not place:
            return
        key = (place.get("name", "").lower(), place.get("city", "").lower())
        if key in seen:
            return
        blended.append(place)
        seen.add(key)

    meal_index = 0
    for index, place in enumerate(ranked_places):
        if len(blended) >= target_count:
            break
        add(place)
        if (index + 1) % 2 == 0 and meal_index < meal_target:
            add(ranked_meals[meal_index])
            meal_index += 1

    while len(blended) < target_count and meal_index < meal_target:
        add(ranked_meals[meal_index])
        meal_index += 1

    return blended


def _blend_must_go_with_meals(
    ranked_must_go: list[dict],
    intent: TravelIntent,
    all_regular_places: list[dict],
) -> list[dict]:
    regular_city_matches = [
        place
        for place in all_regular_places
        if intent.destination.lower() == "france"
        or place.get("city", "").lower() == intent.destination.lower()
    ]
    meal_candidates = [
        place
        for place in regular_city_matches
        if _is_restaurant_place(place) or _is_market_place(place)
    ]
    ranked_meals = _rank_meal_candidates(meal_candidates)
    requested_matchers = _requested_place_matchers(intent)
    requested_regular = _rank_requested_regular([
        place
        for place in regular_city_matches
        if not (_is_restaurant_place(place) or _is_market_place(place))
        and requested_matchers
        and _matches_any_requested_type(place, requested_matchers)
    ], intent)
    target_count = min(24, max(8, intent.duration_days * 6))
    meal_target = min(len(ranked_meals), max(2, intent.duration_days * 2))

    blended: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(place: dict | None) -> None:
        if not place:
            return
        key = (place.get("name", "").lower(), place.get("city", "").lower())
        if key in seen:
            return
        blended.append(place)
        seen.add(key)

    for place in ranked_must_go[:2]:
        add(place)
    for place in ranked_meals[:1]:
        add(place)
    for place in requested_regular[:2]:
        add(place)
    for place in ranked_must_go[2:5]:
        add(place)
    for place in ranked_meals[1:meal_target]:
        add(place)
    for place in requested_regular[2:]:
        if len(blended) >= target_count:
            break
        add(place)
    for place in ranked_must_go[5:]:
        if len(blended) >= target_count:
            break
        add(place)

    return blended


def _open_status_label(place: dict, visit_day: str) -> str:
    opening_hours = place.get("opening_hours") or []

    if visit_day and opening_hours:
        day_prefix = visit_day.lower()
        for line in opening_hours:
            if line.lower().startswith(day_prefix):
                if "closed" in line.lower():
                    return f"Closed on {visit_day}"
                return f"Open {line}"

    if place.get("open_now") is True:
        return "Open now according to Google Maps"
    if place.get("open_now") is False:
        return "Closed now according to Google Maps"
    if place.get("business_status") == "CLOSED_TEMPORARILY":
        return "Temporarily closed according to Google Maps"
    if place.get("business_status") == "CLOSED_PERMANENTLY":
        return "Permanently closed according to Google Maps"
    if place.get("source_type") == "google_maps":
        return "Google Maps hours available after refresh"
    if place.get("source_type") == "openstreetmap" and opening_hours:
        return f"OpenStreetMap hours: {opening_hours[0]}"
    if place.get("source_type") == "openstreetmap":
        return "Opening hours not mapped in OpenStreetMap"
    if place.get("source_type") == "official_open_data" and opening_hours:
        return f"Official schedule: {opening_hours[0]}"
    if place.get("source_type") == "official_open_data":
        return "Official schedule available on source page"
    return "Opening hours need Google Maps refresh"


def retrieve_places(intent: TravelIntent) -> list[Place]:
    must_go_intent = _has_must_go_intent(intent)
    all_regular_places = _all_places(include_must_go=False)
    all_places = _all_places(include_must_go=must_go_intent)
    if must_go_intent:
        all_places = [
            place
            for place in all_places
            if "must_go" in {tag.lower() for tag in place.get("tags", [])}
        ]

    effective_destination = intent.destination
    if must_go_intent and intent.destination.lower() == "france" and intent.duration_days == 1:
        effective_destination = "Paris"

    city_matches = [
        place
        for place in all_places
        if effective_destination.lower() == "france"
        or place["city"].lower() == effective_destination.lower()
    ]

    if not city_matches:
        city_matches = all_places

    mixed_default = _has_mixed_default_intent(intent)

    if _is_cafe_only_intent(intent):
        cafe_matches = [place for place in city_matches if _is_cafe_place(place)]
        if cafe_matches:
            city_matches = cafe_matches

    if _has_asian_food_intent(intent):
        asian_matches = [place for place in city_matches if _is_asian_restaurant(place)]
        if asian_matches:
            city_matches = asian_matches
            specific_terms = _specific_cuisine_terms(intent)
            specific_matches = [
                place
                for place in city_matches
                if specific_terms.intersection(
                    {tag.lower() for tag in place.get("tags", [])}
                )
            ]
            if specific_matches:
                city_matches = specific_matches
    elif _is_food_only_intent(intent) and not mixed_default:
        restaurant_matches = [place for place in city_matches if _is_restaurant_place(place)]
        if restaurant_matches:
            city_matches = restaurant_matches
            specific_terms = _specific_cuisine_terms(intent)
            if specific_terms:
                cuisine_matches = [
                    place
                    for place in city_matches
                    if specific_terms.intersection(
                        {tag.lower() for tag in place.get("tags", [])}
                    )
                    or any(
                        term in f"{place.get('category', '')} {place.get('name', '')}".lower()
                        for term in specific_terms
                    )
                ]
                if cuisine_matches:
                    city_matches = cuisine_matches
    else:
        requested_matchers = _requested_place_matchers(intent)
        if requested_matchers:
            typed_matches = [
                place
                for place in city_matches
                if _matches_any_requested_type(place, requested_matchers)
            ]
            if len(typed_matches) >= 4:
                city_matches = typed_matches

    if intent.indoor_outdoor == "indoor" or "rainy_day_plan" in intent.request_intents:
        indoor_matches = [place for place in city_matches if _is_indoor_candidate(place)]
        if len(indoor_matches) >= 4:
            city_matches = indoor_matches

    if "romantic_plan" in intent.request_intents or intent.mood == "romantic":
        romantic_matches = [place for place in city_matches if _is_romantic_candidate(place)]
        if len(romantic_matches) >= 3:
            city_matches = romantic_matches

    avoid_terms = {item.lower() for item in intent.avoid}
    requested_matchers = _requested_place_matchers(intent)
    scored = []
    for place in city_matches:
        score = 0
        tags = place["tags"]
        open_status = _open_status_label(place, intent.visit_day).lower()
        for interest in intent.interests:
            if interest.lower() in tags:
                score += 2
                if interest.lower() in _specific_cuisine_terms(intent):
                    score += 4
        if must_go_intent:
            if "must_go" in tags:
                score += 10
            if place.get("source_type") == "curated_must_go":
                score += 8
            if place.get("wikidata_id") or place.get("wikipedia"):
                score += 2
        if "tourist traps" in avoid_terms or "crowds" in avoid_terms:
            if place["tourist_trap_risk"] == "low":
                score += 3
            elif place["tourist_trap_risk"] == "high":
                score -= 3
        if intent.pace == "slow" and "quiet" in tags:
            score += 1
        if _has_cafe_intent(intent):
            if _is_cafe_place(place):
                score += 6
            if place.get("source_type") == "reddit":
                score += 4
            if place.get("source_type") == "google_maps":
                score += 4
            if place.get("source_url"):
                score += 2
        if requested_matchers and _matches_any_requested_type(place, requested_matchers):
            score += 6
            if place.get("source_type") in {
                "openstreetmap",
                "official_open_data",
                "reddit",
                "google_maps",
            }:
                score += 3
            if place.get("source_url"):
                score += 2
            if intent.budget == "budget" and "affordable" in tags:
                score += 4
            if intent.budget == "luxury" and {"luxury", "high-end", "designer"}.intersection(tags):
                score += 4
            if intent.budget == "luxury" and "affordable" in tags:
                score -= 3
        if _has_asian_food_intent(intent):
            if _is_asian_restaurant(place):
                score += 10
            if place.get("source_type") in {"openstreetmap", "reddit", "google_maps"}:
                score += 3
            if place.get("source_url"):
                score += 2
        elif _has_restaurant_intent(intent):
            if _is_restaurant_place(place):
                score += 8
            if place.get("source_type") == "openstreetmap":
                score += 4
            if place.get("source_url"):
                score += 2
        if intent.indoor_outdoor == "indoor" or "rainy_day_plan" in intent.request_intents:
            if _is_indoor_candidate(place):
                score += 7
            if _is_museum_place(place) or _is_event_place(place) or _is_book_place(place):
                score += 4
            if _is_park_place(place) or _is_market_place(place):
                score -= 4
        if "romantic_plan" in intent.request_intents or intent.mood == "romantic":
            if _is_romantic_candidate(place):
                score += 6
        if open_status.startswith("closed") or "permanently closed" in open_status:
            score -= 8
        if "temporarily closed" in open_status:
            score -= 6
        scored.append((score, place))

    ranked = [item for _, item in sorted(scored, key=lambda pair: pair[0], reverse=True)]
    semantic_lookup = semantic_scores(ranked, intent)
    result_limit = min(24, max(8, intent.duration_days * 6))
    ranked = rerank_places(
        ranked,
        intent,
        semantic_lookup,
        limit=max(result_limit * 3, 24),
    )
    if (
        mixed_default
        or len(_requested_place_matchers(intent)) >= 2
        or intent.indoor_outdoor == "indoor"
        or "rainy_day_plan" in intent.request_intents
    ):
        ranked = _balanced_mixed_order(ranked)
    if must_go_intent:
        ranked = _blend_must_go_with_meals(ranked, intent, all_regular_places)
    else:
        ranked = _blend_multiday_with_meals(ranked, intent, all_regular_places)
    return [
        Place(
            name=place["name"],
            city=place["city"],
            neighborhood=place["neighborhood"],
            address=place.get("address", ""),
            category=place["category"],
            reason=place["reason"],
            local_tip=place["local_tip"],
            tourist_trap_risk=place["tourist_trap_risk"],
            best_time=place["best_time"],
            estimated_duration_minutes=place["estimated_duration_minutes"],
            latitude=place["latitude"],
            longitude=place["longitude"],
            map_source=place.get("map_source", ""),
            map_url=place.get("map_url", ""),
            price_label=place.get("price_label", ""),
            google_maps_url=place.get("google_maps_url")
            or _google_maps_url(place["latitude"], place["longitude"], place["name"]),
            google_rating=place.get("google_rating"),
            google_user_rating_count=place.get("google_user_rating_count"),
            google_price_level=place.get("google_price_level", ""),
            google_price_label=place.get("google_price_label", ""),
            business_status=place.get("business_status", ""),
            opening_hours=place.get("opening_hours", []),
            open_now=place.get("open_now"),
            open_status_label=_open_status_label(place, intent.visit_day),
            tags=place["tags"],
            source_type=place.get("source_type", ""),
            source_title=place.get("source_title", ""),
            source_url=place.get("source_url", ""),
            confidence=place.get("confidence", 1.0),
        )
        for place in ranked[:result_limit]
    ]
