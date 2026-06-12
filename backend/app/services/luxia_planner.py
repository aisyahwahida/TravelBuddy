import json

from app.schemas.travel import ChatRequest, ChatResponse, Place, TravelIntent
from app.services.luxia_client import LuxiaClient, extract_json_object
from app.services.prompt_templates import template_guidance


class LuxiaTravelPlanner:
    def __init__(self) -> None:
        self.client = LuxiaClient()

    def plan(
        self,
        request: ChatRequest,
        intent: TravelIntent,
        candidates: list[Place],
    ) -> ChatResponse:
        if not self.client.is_configured:
            raise RuntimeError("LUXIA_API_KEY is not configured.")

        schema_hint = ChatResponse.model_json_schema()
        payload = {
            "message": request.message,
            "history": request.history[-8:],
            "initial_intent": intent.model_dump(),
            "request_type_guidance": template_guidance(intent),
            "candidate_places": [place.model_dump() for place in candidates],
            "required_schema": schema_hint,
        }
        system_prompt = (
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

        raw_response = self.client.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload)},
            ],
            temperature=0.0,
            max_tokens=2200,
        )
        return ChatResponse.model_validate(extract_json_object(raw_response))
