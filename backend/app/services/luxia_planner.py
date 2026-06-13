import json
import os

from app.schemas.travel import ChatRequest, ChatResponse, Itinerary, Place, TravelIntent
from app.services.closed_places import scrub_permanently_closed_names
from app.services.luxia_client import LuxiaClient, extract_json_object
from app.services.prompt_templates import template_guidance

# Fields the LLM actually needs to make planning decisions.
# Everything else (ratings, hours, map URLs, google data) gets merged back
# after the response — no point paying LLM tokens to copy-paste them.
_PLANNING_FIELDS = {
    "name", "city", "neighborhood", "category", "reason", "local_tip",
    "tourist_trap_risk", "best_time", "estimated_duration_minutes",
    "latitude", "longitude", "tags", "source_type", "source_url",
    "source_title", "price_label",
}


def _slim(place: Place) -> dict:
    return {k: v for k, v in place.model_dump().items() if k in _PLANNING_FIELDS}


def _merge_metadata(response: ChatResponse, candidates: list[Place]) -> ChatResponse:
    """Restore metadata fields stripped before sending to LLM."""
    lookup: dict[tuple[str, str], Place] = {
        (p.name.lower(), p.city.lower()): p for p in candidates
    }

    _META = {
        "map_source", "map_url", "google_maps_url", "google_rating",
        "google_user_rating_count", "google_price_level", "google_price_label",
        "business_status", "opening_hours", "open_now", "open_status_label",
        "address", "confidence",
    }

    def merge(stop: Place) -> Place:
        original = lookup.get((stop.name.lower(), stop.city.lower()))
        if original is None:
            return stop
        updates = {f: getattr(original, f) for f in _META}
        if not stop.price_label and original.price_label:
            updates["price_label"] = original.price_label
        return stop.model_copy(update=updates)

    merged_stops = [merge(s) for s in response.itinerary.stops]
    merged_days = [
        day.model_copy(update={"stops": [merge(s) for s in day.stops]})
        for day in response.itinerary.days
    ]
    new_itinerary = response.itinerary.model_copy(
        update={"stops": merged_stops, "days": merged_days}
    )
    return response.model_copy(update={"itinerary": new_itinerary})

_FAST_MODEL = "luxia3-llm-8b-0731"
_SMART_MODEL = "luxia3-llm-32b-0731"


def _select_model(intent: TravelIntent) -> str:
    """Use the fast 8B model for simple 1-day plans; 32B for everything complex."""
    if intent.duration_days >= 2:
        return _SMART_MODEL
    complex_intents = {"romantic_plan", "rainy_day_plan", "family_trip", "nightlife_plan"}
    if complex_intents.intersection(set(intent.request_intents)):
        return _SMART_MODEL
    return _FAST_MODEL


def _max_tokens_for(intent: TravelIntent) -> int:
    """Scale token budget with trip length to avoid paying for capacity we don't need."""
    return min(3500, max(1800, intent.duration_days * 1200))

_BASE_SYSTEM = (
    "You are TravelBuddy France, a practical travel-planning assistant. "
    "Use only the provided candidate_places for itinerary stops so coordinates remain accurate. "
    "Build France-only itineraries with realistic pacing, local-feeling recommendations, "
    "clear meal breaks, and low tourist-trap risk when requested. "
    "If the user is vague, default to a balanced 1-day mixed itinerary starting at 09:00, "
    "with lunch around 12:30 and dinner around 19:00 when food candidates are available. "
    "For multi-day requests, split itinerary.days into the exact number of requested days, "
    "do not repeat stops, and give each day a useful theme. "
    "Preserve source, rating, price, map, opening-hours, and evidence fields from candidates. "
    "Return only one valid JSON object matching required_schema. Do not wrap it in markdown."
)

_REFINEMENT_PREFIX = (
    "The user wants to refine their existing itinerary. "
    "Keep all stops the user has not asked to change. "
    "Only modify what the user explicitly requests. "
)


class LuxiaTravelPlanner:
    def __init__(self) -> None:
        self.client = LuxiaClient()

    def plan(
        self,
        request: ChatRequest,
        intent: TravelIntent,
        candidates: list[Place],
        previous_itinerary: Itinerary | None = None,
    ) -> ChatResponse:
        if not self.client.is_configured:
            raise RuntimeError("LUXIA_API_KEY is not configured.")

        payload = {
            "message": request.message,
            "history": [
                {
                    **item,
                    "content": scrub_permanently_closed_names(item.get("content", "")),
                }
                for item in request.history[-4:]
            ],
            "initial_intent": intent.model_dump(),
            "request_type_guidance": template_guidance(intent),
            "candidate_places": [_slim(p) for p in candidates],
        }
        if previous_itinerary is not None:
            payload["previous_itinerary"] = previous_itinerary.model_dump()

        system_prompt = (
            _REFINEMENT_PREFIX + _BASE_SYSTEM
            if previous_itinerary is not None
            else _BASE_SYSTEM
        )

        model = _select_model(intent)
        max_tokens = _max_tokens_for(intent)

        raw_response = self.client.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload)},
            ],
            temperature=0.0,
            max_tokens=max_tokens,
            model_override=model,
        )
        response = ChatResponse.model_validate(extract_json_object(raw_response))
        return _merge_metadata(response, candidates)
