from __future__ import annotations

import logging
import re

from app.schemas.travel import ChatRequest, ChatResponse, Itinerary, TravelIntent
from app.services.closed_places import scrub_permanently_closed_names
from app.services.evidence import build_evidence
from app.services.extractor import extract_travel_intent
from app.services.google_places import resolve_stay_location
from app.services.luxia_client import LuxiaClient
from app.services.luxia_planner import LuxiaTravelPlanner
from app.services.itinerary_validator import enforce_min_stop_quality, repair_itinerary, validate_itinerary
from app.services.planner import build_itinerary, split_stops_by_day
from app.services.place_safety import sanitize_itinerary, sanitize_response
from app.services.contextual_alternatives import build_contextual_alternative_options
from app.services.response_formatter import build_assistant_message
from app.services.retriever import retrieve_places
from app.services.session_store import ensure_session_id, get_session, save_chat_turn

logger = logging.getLogger(__name__)

CONTEXT_DESTINATIONS = {
    "paris",
    "lyon",
    "marseille",
    "nice",
    "bordeaux",
    "strasbourg",
    "lille",
}

_NEW_TRIP_PATTERNS = [
    r"\b\d+\s*days?\s+(in|at)\b",
    r"\btrip\s+to\b",
    r"\bplan\s+(me|us|a|my|our)\b",
    r"\bnew\s+(trip|plan|itinerary)\b",
    r"\b(give|create|make|build|show)\s+me\b.{0,25}\b(itinerary|plan)\b",
    r"\bwhat\s+should\s+(?:i|we)\s+do\s+in\b",
    r"\bi\s+(?:will|am going to)\s+(?:be\s+)?(?:in|visiting|going\s+to)\b",
]

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

_STAY_REROUTE_PATTERNS = [
    r"\b(?:redo|update|rework|restart|rebuild)\b.{0,25}\b(map|route|itinerary)\b",
    r"\bstart\b.{0,20}\b(?:from|at)\b.{0,40}\b(?:hotel|hostel|airbnb|apartment|place of stay|where i(?:'m| am) staying)\b",
    r"\b(?:from|near)\b.{0,25}\b(?:my|our)\b.{0,10}\b(?:hotel|hostel|airbnb|apartment)\b",
    r"\b(?:my|our)\b.{0,10}\b(?:hotel|hostel|airbnb|apartment)\b.{0,25}\b(?:for the route|for the map|for the itinerary|as the start)\b",
]


def _is_stay_reroute_request(message: str) -> bool:
    lowered = message.lower()
    return any(re.search(pattern, lowered) for pattern in _STAY_REROUTE_PATTERNS)


def _is_refinement(message: str, has_history: bool) -> bool:
    if not has_history:
        return False
    lowered = message.lower()
    return any(re.search(p, lowered) for p in _REFINEMENT_PATTERNS)


def _is_followup_qa(message: str, has_history: bool) -> bool:
    """Return True if the message is a question about an existing itinerary rather than a new plan request."""
    if not has_history:
        return False
    if _is_stay_reroute_request(message):
        return True
    if _is_refinement(message, has_history):
        return False
    lowered = message.lower()
    if any(re.search(p, lowered) for p in _NEW_TRIP_PATTERNS):
        return False
    return True


def _load_previous_intent(session_id: str) -> TravelIntent | None:
    if not session_id:
        return None
    try:
        session = get_session(session_id)
        turns = session.get("turns", [])
        if not turns:
            return None
        last_intent = turns[-1].get("intent")
        return TravelIntent.model_validate(last_intent) if last_intent else None
    except Exception:
        return None


def _load_previous_itinerary(session_id: str) -> Itinerary | None:
    if not session_id:
        return None
    try:
        session = get_session(session_id)
        data = session.get("latest_itinerary")
        return sanitize_itinerary(Itinerary.model_validate(data)) if data else None
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
        content = scrub_permanently_closed_names(item.get("content", "").strip())
        if content:
            context_lines.append(f"{role}: {content}")

    if not context_lines:
        return request.message

    return (
        "Previous same-chat context:\n"
        + "\n".join(context_lines)
        + f"\nCurrent user request: {request.message}"
    )


def _apply_day_normalization(response: ChatResponse, stay_anchor=None) -> ChatResponse:
    interests = response.extracted_intent.interests
    duration = response.extracted_intent.duration_days
    if _needs_day_normalization(interests, duration):
        response.itinerary.days = split_stops_by_day(
            response.itinerary.stops,
            duration,
            force_full_day=_is_mixed_default(interests),
            stay_anchor=stay_anchor,
        )
        response.itinerary.stops = [
            stop for day in response.itinerary.days for stop in day.stops
        ]
    elif not response.itinerary.days:
        response.itinerary.days = split_stops_by_day(
            response.itinerary.stops, duration, stay_anchor=stay_anchor
        )
    return response


def _response_underfills_request(response: ChatResponse, intent: TravelIntent) -> bool:
    requested_days = max(1, intent.duration_days)
    actual_days = len(response.itinerary.days) if response.itinerary.days else 1
    actual_stops = len(response.itinerary.stops)
    if requested_days <= 1:
        return False
    if actual_days < requested_days:
        return True
    if any(0 < len(day.stops) < 4 for day in response.itinerary.days):
        return True
    # Guard against model outputs that acknowledge a multi-day trip but only return
    # a tiny single-day-sized stop list.
    return actual_stops < requested_days * 2


def _resolve_stay_anchor(intent: TravelIntent):
    if not intent.stay_location:
        return None
    try:
        return resolve_stay_location(intent.stay_location, intent.destination)
    except Exception:
        return None


class TravelOrchestrator:
    def __init__(self) -> None:
        self.ai_planner = LuxiaTravelPlanner()
        self._qa_client = LuxiaClient()

    def is_followup_qa(self, request: ChatRequest) -> bool:
        return _is_followup_qa(request.message, bool(request.history))

    def should_try_followup(self, request: ChatRequest) -> bool:
        if self.is_followup_qa(request):
            return True
        return bool(request.session_id) and _is_stay_reroute_request(request.message)

    def answer_followup(self, request: ChatRequest, session_id: str) -> ChatResponse | None:
        """Answer a conversational question from session context, skipping the full planning pipeline."""
        previous_itinerary = _load_previous_itinerary(session_id)
        previous_intent = _load_previous_intent(session_id)
        if not previous_itinerary or not previous_intent:
            return None

        if _is_stay_reroute_request(request.message):
            updated_intent = self.extract_intent(request)
            merged_intent = previous_intent.model_copy(
                update={
                    "stay_location": updated_intent.stay_location or previous_intent.stay_location,
                }
            )
            if not merged_intent.stay_location:
                return ChatResponse(
                    assistant_message="Share your hotel or area name and I can rebuild the route from where you're staying.",
                    extracted_intent=previous_intent,
                    itinerary=previous_itinerary,
                    session_id=session_id,
                    evidence=[],
                    assumptions=[],
                    alternative_options=[],
                    is_followup=True,
                )
            stay_anchor = _resolve_stay_anchor(merged_intent)
            if not stay_anchor:
                return ChatResponse(
                    assistant_message=f"I couldn't pinpoint {merged_intent.stay_location} yet. Send the exact hotel or neighborhood name and I'll reset the route from there.",
                    extracted_intent=merged_intent,
                    itinerary=previous_itinerary,
                    session_id=session_id,
                    evidence=[],
                    assumptions=[],
                    alternative_options=[],
                    is_followup=True,
                )
            rerouted = build_itinerary(
                merged_intent,
                previous_itinerary.stops,
                stay_anchor=stay_anchor,
            )
            return ChatResponse(
                assistant_message=f"Updated the route to start from {stay_anchor.name}.",
                extracted_intent=merged_intent,
                itinerary=rerouted,
                session_id=session_id,
                evidence=build_evidence(rerouted.stops),
                assumptions=merged_intent.assumptions,
                alternative_options=[],
                is_followup=True,
            )

        if not self._qa_client.is_configured:
            return None

        # Build a compact itinerary context for the model
        context_lines: list[str] = []
        for day in previous_itinerary.days:
            stop_lines = "\n".join(
                f"  - {s.name} ({s.category}, {s.city}, lat={s.latitude:.4f}, lon={s.longitude:.4f})"
                for s in day.stops
            )
            context_lines.append(f"{day.title}:\n{stop_lines}")
        if not context_lines:
            context_lines = [
                f"  - {s.name} ({s.category}, {s.city})" for s in previous_itinerary.stops[:12]
            ]

        context = "\n".join(context_lines)
        destination = previous_intent.destination

        history_msgs = [
            {"role": item.get("role", "user"), "content": item.get("content", "")}
            for item in (request.history or [])[-6:]
        ]

        try:
            answer = self._qa_client.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"You are a helpful France travel assistant. "
                            f"The traveler has a planned itinerary for {destination}. "
                            "Answer their question concisely using the itinerary below as context. "
                            "For distance/transport between stops, give realistic metro or walking times. "
                            "For transit questions (train, metro, bus), name relevant Paris metro lines or RER lines when helpful. "
                            "Keep answers under 4 sentences unless a list is clearly needed.\n\n"
                            f"Planned itinerary for {destination}:\n{context}"
                        ),
                    },
                    *history_msgs,
                    {"role": "user", "content": request.message},
                ],
                temperature=0.3,
                max_tokens=400,
                model_override="luxia3-llm-8b-0731",
            )
        except Exception:
            return None

        answer = answer.strip()
        if not answer:
            return None

        return ChatResponse(
            assistant_message=answer,
            extracted_intent=previous_intent,
            itinerary=previous_itinerary,
            session_id=session_id,
            evidence=[],
            assumptions=[],
            alternative_options=[],
            is_followup=True,
        )

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
        """
        Build the itinerary deterministically, then run validation + repair.
        The LLM is used only to write the conversational assistant message —
        it never decides which places appear or in what order.
        """
        from app.services.intent_specificity import calculate_intent_specificity

        # ── Debug: intent profile ─────────────────────────────────────────────
        spec_score = calculate_intent_specificity(intent)
        logger.info(
            "plan: destination=%r duration=%d user_type=%r specificity=%d "
            "interests=%s budget=%r mood=%r",
            intent.destination,
            intent.duration_days,
            intent.user_type,
            spec_score,
            intent.interests,
            intent.budget,
            intent.mood,
        )

        stay_anchor = _resolve_stay_anchor(intent)

        # ── 1. Deterministic itinerary ────────────────────────────────────────
        itinerary = build_itinerary(intent, places, stay_anchor=stay_anchor)

        # ── Debug: post-build stop counts ─────────────────────────────────────
        pre_repair_counts = [len(day.stops) for day in itinerary.days]
        logger.info(
            "plan: post-build days=%d stop_counts=%s",
            len(itinerary.days), pre_repair_counts,
        )

        # ── 2. Validate + repair ──────────────────────────────────────────────
        raw_days = [day.stops for day in itinerary.days]
        issues = validate_itinerary(raw_days, intent)
        if issues:
            logger.info("plan: validator issues=%s", [str(i) for i in issues])
            repaired_day_stops = repair_itinerary(raw_days, places, intent)
        else:
            repaired_day_stops = raw_days

        # ── 3. Enforce minimum 4 stops/day (final backstop) ──────────────────
        repaired_day_stops = enforce_min_stop_quality(repaired_day_stops, places, intent)

        # ── 4. Rebuild ItineraryDay objects ───────────────────────────────────
        from app.schemas.travel import ItineraryDay
        repaired_days = [
            itinerary.days[i].model_copy(update={"stops": repaired_day_stops[i]})
            for i in range(len(itinerary.days))
            if i < len(repaired_day_stops) and repaired_day_stops[i]
        ]

        # ── 5. Enforce exact day count (trim any excess days) ─────────────────
        requested_days = intent.duration_days
        if len(repaired_days) > requested_days:
            logger.warning(
                "plan: trimming %d extra days (got %d, requested %d)",
                len(repaired_days) - requested_days,
                len(repaired_days),
                requested_days,
            )
            repaired_days = repaired_days[:requested_days]

        itinerary = itinerary.model_copy(
            update={
                "days": repaired_days,
                "stops": [s for day in repaired_days for s in day.stops],
            }
        )

        # ── Debug: post-repair stop counts and category distribution ──────────
        post_counts = [len(day.stops) for day in itinerary.days]
        cat_dist: dict[str, int] = {}
        for stop in itinerary.stops:
            cat = stop.category.lower()
            cat_dist[cat] = cat_dist.get(cat, 0) + 1
        top_cats = dict(sorted(cat_dist.items(), key=lambda x: -x[1])[:5])
        logger.info(
            "plan: post-repair days=%d stop_counts=%s top_categories=%s",
            len(itinerary.days), post_counts, top_cats,
        )

        # ── 6. Assemble response ──────────────────────────────────────────────
        response = ChatResponse(
            assistant_message=build_assistant_message(intent, itinerary, places),
            extracted_intent=intent,
            itinerary=itinerary,
            session_id=session_id,
            evidence=build_evidence(itinerary.stops),
            assumptions=intent.assumptions,
            alternative_options=build_contextual_alternative_options(places, itinerary, intent),
        )
        if intent.clarification_question:
            response.assistant_message = (
                f"{response.assistant_message}\n\n"
                f"Quick follow-up: {intent.clarification_question}"
            )
        return sanitize_response(response)

    # ── Top-level entry point (regular /api/chat endpoint) ──

    def handle_chat(self, request: ChatRequest) -> ChatResponse:
        if not request.message.strip():
            raise ValueError("Message cannot be empty.")

        session_id = ensure_session_id(request.session_id)
        if self.should_try_followup(request):
            followup = self.answer_followup(request, session_id)
            if followup:
                save_chat_turn(request, followup)
                return followup
        intent = self.extract_intent(request)
        places = self.fetch_places(intent)
        response = self.plan(request, intent, places, session_id=session_id)
        save_chat_turn(request, response)
        return response
