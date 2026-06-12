from __future__ import annotations

import re

from app.schemas.travel import ChatRequest, ChatResponse, Itinerary, TravelIntent
from app.services.evidence import build_evidence
from app.services.extractor import extract_travel_intent
from app.services.luxia_planner import LuxiaTravelPlanner
from app.services.planner import build_itinerary, split_stops_by_day
from app.services.response_formatter import (
    build_alternative_options,
    build_assistant_message,
)
from app.services.retriever import retrieve_places
from app.services.session_store import ensure_session_id, get_session, save_chat_turn

CONTEXT_DESTINATIONS = {
    "paris",
    "lyon",
    "marseille",
    "nice",
    "bordeaux",
    "strasbourg",
    "lille",
}

_REFINEMENT_PATTERNS = [
    r"\bchange\b",
    r"\bswap\b",
    r"\breplace\b",
    r"\bremove\b",
    r"\bday\s+\d+\b",
    r"\binstead\b",
    r"\brefine\b",
    r"\bmodify\b",
    r"\badd\b.{1,30}\bday\b",
    r"\bmore\b.{1,25}\b(food|museum|park|cafe|quiet|romantic)\b",
    r"\bless\b.{1,25}\b(tourist|crowd|busy)\b",
]


def _is_refinement(message: str, has_history: bool) -> bool:
    if not has_history:
        return False
    lowered = message.lower()
    return any(re.search(p, lowered) for p in _REFINEMENT_PATTERNS)


def _load_previous_itinerary(session_id: str) -> Itinerary | None:
    if not session_id:
        return None
    try:
        session = get_session(session_id)
        data = session.get("latest_itinerary")
        return Itinerary.model_validate(data) if data else None
    except Exception:
        return None


def _is_mixed_default(interests: list[str]) -> bool:
    return "mixed" in {interest.lower() for interest in interests}


def _needs_day_normalization(interests: list[str], duration_days: int) -> bool:
    normalized = {interest.lower() for interest in interests}
    return (
        duration_days > 1
        or "mixed" in normalized
        or bool({"must_go", "first_time", "iconic", "landmarks"}.intersection(normalized))
    )


def _current_message_has_destination(message: str) -> bool:
    lowered = message.lower()
    return any(destination in lowered for destination in CONTEXT_DESTINATIONS)


def _message_with_context(request: ChatRequest) -> str:
    if not request.history or _current_message_has_destination(request.message):
        return request.message

    recent_history = request.history[-6:]
    context_lines = []
    for item in recent_history:
        role = item.get("role", "user")
        content = item.get("content", "").strip()
        if content:
            context_lines.append(f"{role}: {content}")

    if not context_lines:
        return request.message

    return (
        "Previous same-chat context:\n"
        + "\n".join(context_lines)
        + f"\nCurrent user request: {request.message}"
    )


def _apply_day_normalization(response: ChatResponse) -> ChatResponse:
    interests = response.extracted_intent.interests
    duration = response.extracted_intent.duration_days
    if _needs_day_normalization(interests, duration):
        response.itinerary.days = split_stops_by_day(
            response.itinerary.stops,
            duration,
            force_full_day=_is_mixed_default(interests),
        )
        response.itinerary.stops = [
            stop for day in response.itinerary.days for stop in day.stops
        ]
    elif not response.itinerary.days:
        response.itinerary.days = split_stops_by_day(
            response.itinerary.stops, duration
        )
    return response


class TravelOrchestrator:
    def __init__(self) -> None:
        self.ai_planner = LuxiaTravelPlanner()

    # ── Public stage methods (used by both handle_chat and the streaming endpoint) ──

    def extract_intent(self, request: ChatRequest) -> TravelIntent:
        return extract_travel_intent(_message_with_context(request))

    def fetch_places(self, intent: TravelIntent):
        return retrieve_places(intent)

    def plan(
        self,
        request: ChatRequest,
        intent: TravelIntent,
        places,
        *,
        session_id: str = "",
    ) -> ChatResponse:
        previous_itinerary = (
            _load_previous_itinerary(session_id)
            if _is_refinement(request.message, bool(request.history))
            else None
        )
        try:
            response = self.ai_planner.plan(
                request, intent, places, previous_itinerary=previous_itinerary
            )
            response.session_id = session_id
            response = _apply_day_normalization(response)
            response.evidence = build_evidence(response.itinerary.stops)
            response.assumptions = response.extracted_intent.assumptions
            used = {stop.name for stop in response.itinerary.stops}
            response.alternative_options = build_alternative_options(places, used)
            if response.extracted_intent.clarification_question:
                response.assistant_message = (
                    f"{response.assistant_message}\n\n"
                    f"Quick follow-up: {response.extracted_intent.clarification_question}"
                )
            return response
        except Exception:
            itinerary = build_itinerary(intent, places)
            assistant_message = build_assistant_message(intent, itinerary, places)
            return ChatResponse(
                assistant_message=assistant_message,
                extracted_intent=intent,
                itinerary=itinerary,
                session_id=session_id,
                evidence=build_evidence(itinerary.stops),
                assumptions=intent.assumptions,
                alternative_options=build_alternative_options(
                    places, {stop.name for stop in itinerary.stops}
                ),
            )

    # ── Top-level entry point (regular /api/chat endpoint) ──

    def handle_chat(self, request: ChatRequest) -> ChatResponse:
        if not request.message.strip():
            raise ValueError("Message cannot be empty.")

        session_id = ensure_session_id(request.session_id)
        intent = self.extract_intent(request)
        places = self.fetch_places(intent)
        response = self.plan(request, intent, places, session_id=session_id)
        save_chat_turn(request, response)
        return response
