"""
Evaluation baseline planners for the capstone three-system comparison.

System 1 – LLMOnlyPlanner:   no retrieved places, LLM uses training knowledge only
System 2 – BasicRagPlanner:  city-match retrieval only, no preference extraction/scoring
System 3 – TravelOrchestrator (main app): full personalized RAG pipeline
"""
from __future__ import annotations

import json

from app.schemas.travel import ChatRequest, ChatResponse, Place, TravelIntent
from app.services.luxia_client import LuxiaClient, extract_json_object

_LLM_ONLY_SYSTEM = (
    "You are TravelBuddy France, a France travel expert. "
    "Generate a detailed, helpful itinerary using your own knowledge of France. "
    "Include specific real place names, accurate neighborhoods, and realistic GPS coordinates. "
    "Return one valid JSON object matching required_schema. Do not wrap in markdown."
)

_BASIC_RAG_SYSTEM = (
    "You are TravelBuddy France. Use only the provided candidate_places for itinerary stops "
    "so coordinates remain accurate. Return one valid JSON object matching required_schema. "
    "Do not wrap in markdown."
)


class LLMOnlyPlanner:
    """Baseline 1: LLM generates itinerary from training knowledge — no retrieved places."""

    def __init__(self) -> None:
        self.client = LuxiaClient()

    def plan(self, request: ChatRequest, intent: TravelIntent) -> ChatResponse:
        if not self.client.is_configured:
            raise RuntimeError("LUXIA_API_KEY is not configured.")

        payload = {
            "message": request.message,
            "history": request.history[-4:],
            "destination": intent.destination,
            "duration_days": intent.duration_days,
            "required_schema": ChatResponse.model_json_schema(),
        }
        raw = self.client.chat(
            messages=[
                {"role": "system", "content": _LLM_ONLY_SYSTEM},
                {"role": "user", "content": json.dumps(payload)},
            ],
            temperature=0.2,
            max_tokens=3000,
        )
        return ChatResponse.model_validate(extract_json_object(raw))


class BasicRagPlanner:
    """Baseline 2: city-filtered candidate retrieval, no preference scoring or extraction."""

    def __init__(self) -> None:
        self.client = LuxiaClient()

    def plan(
        self,
        request: ChatRequest,
        intent: TravelIntent,
        places: list[Place],
    ) -> ChatResponse:
        if not self.client.is_configured:
            raise RuntimeError("LUXIA_API_KEY is not configured.")

        payload = {
            "message": request.message,
            "destination": intent.destination,
            "duration_days": intent.duration_days,
            "candidate_places": [p.model_dump() for p in places[:12]],
            "required_schema": ChatResponse.model_json_schema(),
        }
        raw = self.client.chat(
            messages=[
                {"role": "system", "content": _BASIC_RAG_SYSTEM},
                {"role": "user", "content": json.dumps(payload)},
            ],
            temperature=0.0,
            max_tokens=3000,
        )
        return ChatResponse.model_validate(extract_json_object(raw))
