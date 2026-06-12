from __future__ import annotations

from app.schemas.travel import AlternativePlace, Itinerary, Place, TravelIntent


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
    days = len(itinerary.days) if itinerary.days else 1
    destination = itinerary.destination or intent.destination or "your destination"
    stop_count = sum(len(d.stops) for d in itinerary.days) if itinerary.days else len(itinerary.stops)
    evidence_count = sum(1 for place in places if place.source_url)

    day_label = "day" if days == 1 else "days"
    intro = f"Here's your {days}-{day_label} plan for {destination} — {stop_count} stops backed by {evidence_count} real sources."

    budget_note = ""
    if intent.budget and intent.budget.lower() in ("low", "budget", "cheap"):
        budget_note = " I've kept it affordable with free sights, markets, and budget-friendly spots."
    elif intent.budget and intent.budget.lower() in ("high", "luxury"):
        budget_note = " I've focused on higher-end experiences to match your budget."

    clarification = (
        f" One thing to check: {intent.clarification_question}"
        if intent.clarification_question
        else ""
    )

    assumption_note = ""
    if intent.assumptions:
        assumption_note = f" I assumed: {intent.assumptions[0].lower()}."

    return (intro + budget_note + assumption_note + clarification).strip()


def build_alternative_options(
    places: list[Place],
    used_names: set[str] | None = None,
) -> list[AlternativePlace]:
    excluded = {name.lower() for name in (used_names or set())}
    candidates = [p for p in places if p.name.lower() not in excluded]
    return [
        AlternativePlace(
            name=place.name,
            category=place.category,
            city=place.city,
            reason=place.reason,
            local_tip=place.local_tip,
            tourist_trap_risk=place.tourist_trap_risk,
            source_url=place.source_url,
            latitude=place.latitude,
            longitude=place.longitude,
        )
        for place in candidates[:6]
    ]
