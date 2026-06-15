from __future__ import annotations

from app.schemas.travel import TravelIntent
from app.services.semantic_retrieval import semantic_key


def _tags(place: dict) -> set[str]:
    return {tag.lower() for tag in place.get("tags", [])}


def _text(place: dict) -> str:
    return f"{place.get('name', '')} {place.get('category', '')} {place.get('reason', '')}".lower()


def _has_real_photo(place: dict) -> bool:
    return bool(str(place.get("photo_name", "")).strip() or str(place.get("wiki_thumb_url", "")).strip())


def _general_quality_score(place: dict) -> float:
    """
    Balanced quality score for low-specificity prompts where the semantic query
    is too vague to be a reliable signal.

    Weights:
      0.25 must-go / iconic places
      0.25 hidden-gem / non-touristy places
      0.20 source confidence (reddit, curated, google)
      0.15 rating quality (above 3 stars)
      0.10 has photo + map_url bonus
      -0.20 tourist-trap penalty
    """
    tags = _tags(place)
    is_landmark = bool({"must_go", "landmark", "iconic", "famous"}.intersection(tags))
    is_curated = place.get("source_type") == "curated_must_go"
    must_go_s = min(1.0, (1.0 if is_landmark else 0.0) + (0.5 if is_curated else 0.0))

    is_gem = place.get("tourist_trap_risk") == "low" and not is_landmark
    reddit_b = 0.3 if place.get("source_type") == "reddit" else 0.0
    gem_s = min(1.0, (1.0 if is_gem else 0.0) + reddit_b)

    source_s = (
        1.0 if place.get("source_type") in {"reddit", "curated_must_go", "google_maps"}
        else 0.5
    )
    if place.get("source_url"):
        source_s = min(1.0, source_s + 0.2)

    rating = float(place.get("google_rating") or 0)
    rating_s = min(1.0, max(0.0, (rating - 3.0) / 2.0)) if rating >= 3.0 else 0.0

    photo_b = 0.5 if _has_real_photo(place) else 0.0
    map_b = 0.5 if place.get("google_maps_url") else 0.0
    media_s = (photo_b + map_b)  # 0–1

    trap_s = 1.0 if place.get("tourist_trap_risk") == "high" else 0.0

    return (
        0.25 * must_go_s
        + 0.25 * gem_s
        + 0.20 * source_s
        + 0.15 * rating_s
        + 0.10 * media_s
        - 0.20 * trap_s
    )


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

    if place.get("source_type") in {"reddit", "google_maps", "official_open_data", "curated_must_go"}:
        score += 1.0
    if place.get("source_url"):
        score += 0.8
    if _has_real_photo(place):
        score += 1.0
    else:
        score -= 0.5
    if place.get("google_maps_url"):
        score += 0.5
    else:
        score -= 0.5
    if place.get("google_rating"):
        score += min(float(place.get("google_rating", 0)) / 5, 1.0)
    score += float(place.get("confidence", 0.7))

    # Profile-specific adjustments
    user_type = getattr(intent, "user_type", "") or "general"
    is_landmark = bool({"must_go", "landmark", "iconic", "famous"}.intersection(tags))
    is_curated_must_go = place.get("source_type") == "curated_must_go"
    must_go_score = (3.0 if is_landmark else 0.0) + (2.0 if is_curated_must_go else 0.0)
    is_gem = place.get("tourist_trap_risk") == "low" and not is_landmark
    hidden_gem_score = (3.0 if is_gem else 0.0) + (1.0 if place.get("source_type") == "reddit" else 0.0)
    tourist_trap_score = 2.0 if place.get("tourist_trap_risk") == "high" else 0.0

    if user_type == "first_time_visitor":
        score += 0.20 * must_go_score
    elif user_type == "returning_visitor":
        score += 0.15 * hidden_gem_score
        score -= 0.10 * tourist_trap_score
    elif user_type == "local_resident":
        score += 0.25 * hidden_gem_score
        score -= 0.20 * tourist_trap_score
    elif user_type == "family_trip":
        score += 0.10 * must_go_score
        if any(t in tags for t in ["family", "kids", "family-friendly", "park", "outdoor", "garden"]):
            score += 2.0
    elif user_type == "food_traveler":
        if any(t in tags for t in ["restaurant", "bistro", "cafe", "coffee", "market", "food", "wine"]):
            score += 2.5
    elif user_type == "general_low_specificity":
        # Balanced: reward both landmarks and hidden gems, penalise tourist traps
        score += 0.20 * must_go_score
        score += 0.15 * hidden_gem_score
        score -= 0.10 * tourist_trap_score

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
        key = semantic_key(place)
        if key in seen:
            continue
        category = place.get("category", "unknown")
        city = place.get("city", "unknown")
        # Light penalty at retrieval stage — keeps variety in the candidate list
        # without over-penalising categories the user loves (e.g. museums × 3 for a
        # museum lover). Heavy diversity enforcement happens inside the day planner.
        penalty = category_counts.get(category, 0) * 0.3 + city_counts.get(city, 0) * 0.10
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
    user_type = getattr(intent, "user_type", "") or "general"
    is_low_spec = user_type == "general_low_specificity"

    ranked = []
    for place in places:
        semantic = semantic_score_lookup.get(semantic_key(place), 0.0)

        if is_low_spec:
            # Low-specificity: reduce semantic weight (vague query = noisy signal)
            # and add general quality score to ensure balanced, well-rounded candidates.
            # semantic * 1 ≈ 5% vs the normal 5× ≈ 20% contribution.
            gen_score = _general_quality_score(place)
            score = semantic * 1.0 + metadata_score(place, intent) + gen_score * 5.0
        else:
            # Specific prompts: keep existing blend (semantic 5× + metadata)
            score = semantic * 5 + metadata_score(place, intent)

        ranked.append((score, place))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return diversity_rerank(ranked, limit)
