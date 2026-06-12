from __future__ import annotations

from app.schemas.travel import Itinerary, Place, TravelIntent


def _cost_hint(place: Place) -> str:
    if place.price_label:
        return place.price_label
    tags = {tag.lower() for tag in place.tags}
    if "free" in tags or "park" in tags:
        return "Free or low-cost"
    if any(term in tags for term in ["luxury", "high-end", "designer"]):
        return "Higher-cost"
    if "restaurant" in place.category.lower():
        return "Meal cost varies; check menu"
    return "Check current price"


def build_assistant_message(
    intent: TravelIntent,
    itinerary: Itinerary,
    places: list[Place],
) -> str:
    intent_text = ", ".join(intent.request_intents or ["itinerary"])
    assumption_text = (
        " Assumptions: " + " ".join(intent.assumptions)
        if intent.assumptions
        else ""
    )
    clarification = (
        f" Quick check: {intent.clarification_question}"
        if intent.clarification_question
        else ""
    )
    route_logic = (
        "Route logic: days are grouped by theme and each day keeps lunch/dinner "
        "between activities where food candidates are available."
    )
    evidence_count = sum(1 for place in places if place.source_url)
    cost_examples = "; ".join(
        f"{place.name}: {_cost_hint(place)}" for place in places[:4]
    )
    alternatives = ", ".join(place.name for place in places[4:7])

    return (
        f"{itinerary.summary} Request type detected: {intent_text}. "
        f"{route_logic} Estimated cost guidance: {cost_examples or 'check current prices'}. "
        f"Evidence: {evidence_count} selected stops include community, map, official, or curated source links. "
        f"Alternatives to swap in: {alternatives or 'ask for a different mood, budget, or area'}. "
        f"{assumption_text}{clarification}"
    ).strip()


def build_alternative_options(places: list[Place]) -> list[str]:
    return [
        f"{place.name} ({place.category}, {place.city})"
        for place in places[4:10]
    ]
