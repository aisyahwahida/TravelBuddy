from __future__ import annotations

import re

from app.schemas.travel import ChatResponse, Itinerary, ItineraryDay, Place
from app.services.closed_places import is_permanently_closed_place


def is_closed_place(place: Place) -> bool:
    return (
        place.business_status == "CLOSED_PERMANENTLY"
        or "permanently closed" in place.open_status_label.lower()
        or is_permanently_closed_place(place.name, place.city)
    )


def filter_closed_places(places: list[Place]) -> list[Place]:
    return [place for place in places if not is_closed_place(place)]


def sanitize_itinerary(itinerary: Itinerary) -> Itinerary:
    safe_stops = filter_closed_places(itinerary.stops)
    safe_days: list[ItineraryDay] = []
    for day in itinerary.days:
        day_stops = filter_closed_places(day.stops)
        if day_stops:
            safe_days.append(day.model_copy(update={"stops": day_stops}))
    return itinerary.model_copy(update={"stops": safe_stops, "days": safe_days})


def _remove_closed_names_from_text(text: str, removed_names: set[str]) -> str:
    cleaned = text
    for name in removed_names:
        cleaned = re.sub(rf"\b{re.escape(name)}\b[:,]?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def sanitize_response(response: ChatResponse) -> ChatResponse:
    original_stops = [
        *response.itinerary.stops,
        *[stop for day in response.itinerary.days for stop in day.stops],
    ]
    safe_itinerary = sanitize_itinerary(response.itinerary)
    removed_names = {
        stop.name for stop in original_stops if is_closed_place(stop)
    }
    safe_evidence = [
        item for item in response.evidence if item.place_name not in removed_names
    ]
    safe_alternatives = [
        item for item in response.alternative_options
        if not is_permanently_closed_place(item.name, item.city)
    ]
    assistant_message = _remove_closed_names_from_text(
        response.assistant_message,
        removed_names,
    )
    return response.model_copy(
        update={
            "assistant_message": assistant_message,
            "itinerary": safe_itinerary,
            "evidence": safe_evidence,
            "alternative_options": safe_alternatives,
        }
    )
