from __future__ import annotations

from app.schemas.travel import TravelIntent


def _tags(place: dict) -> set[str]:
    return {tag.lower() for tag in place.get("tags", [])}


def _text(place: dict) -> str:
    return f"{place.get('name', '')} {place.get('category', '')} {place.get('reason', '')}".lower()


def metadata_score(place: dict, intent: TravelIntent) -> float:
    tags = _tags(place)
    text = _text(place)
    score = 0.0

    for interest in intent.interests:
        normalized = interest.lower()
        if normalized in tags or normalized in text:
            score += 2.0

    if intent.mood and (intent.mood.lower() in tags or intent.mood.lower() in text):
        score += 2.0
    if intent.food_preference and (
        intent.food_preference.lower() in tags or intent.food_preference.lower() in text
    ):
        score += 3.0
    if intent.indoor_outdoor == "indoor" and any(
        term in tags for term in ["museum", "gallery", "indoor", "shopping"]
    ):
        score += 2.0
    if intent.indoor_outdoor == "outdoor" and any(
        term in tags for term in ["park", "garden", "walks", "viewpoint", "outdoor"]
    ):
        score += 2.0
    if intent.budget == "budget" and any(
        term in tags for term in ["free", "budget", "affordable", "market"]
    ):
        score += 2.5
    if intent.budget == "luxury" and any(
        term in tags for term in ["luxury", "high-end", "designer"]
    ):
        score += 2.5

    if place.get("tourist_trap_risk") == "low":
        score += 2.0
    elif place.get("tourist_trap_risk") == "high" and "must_go" not in tags:
        score -= 2.5

    if place.get("source_type") in {"reddit", "google_maps", "openstreetmap", "official_open_data", "curated_must_go"}:
        score += 1.0
    if place.get("source_url"):
        score += 0.8
    if place.get("google_rating"):
        score += min(float(place.get("google_rating", 0)) / 5, 1.0)
    score += float(place.get("confidence", 0.7))

    return score


def diversity_rerank(
    ranked: list[tuple[float, dict]],
    limit: int,
) -> list[dict]:
    selected: list[dict] = []
    category_counts: dict[str, int] = {}
    city_counts: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()

    for base_score, place in ranked:
        key = (place.get("name", "").lower(), place.get("city", "").lower())
        if key in seen:
            continue
        category = place.get("category", "unknown")
        city = place.get("city", "unknown")
        penalty = category_counts.get(category, 0) * 0.9 + city_counts.get(city, 0) * 0.15
        place["_rerank_score"] = round(base_score - penalty, 4)
        selected.append(place)
        seen.add(key)
        category_counts[category] = category_counts.get(category, 0) + 1
        city_counts[city] = city_counts.get(city, 0) + 1
        selected.sort(key=lambda item: item.get("_rerank_score", 0), reverse=True)
        selected = selected[:limit]

    return selected


def rerank_places(
    places: list[dict],
    intent: TravelIntent,
    semantic_score_lookup: dict[tuple[str, str], float],
    limit: int,
) -> list[dict]:
    ranked = []
    for place in places:
        key = (place.get("name", "").lower(), place.get("city", "").lower())
        semantic = semantic_score_lookup.get(key, 0.0)
        score = semantic * 10 + metadata_score(place, intent)
        ranked.append((score, place))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return diversity_rerank(ranked, limit)
