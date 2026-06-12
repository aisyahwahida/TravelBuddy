"""
Evaluation endpoints for the capstone three-system comparison.

POST /api/eval/llm-only      – Baseline 1: LLM only, no retrieval
POST /api/eval/basic-rag     – Baseline 2: city-match retrieval, no preference scoring
POST /api/eval/compare       – Run all three systems and return side-by-side results
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.travel import ChatRequest, ChatResponse, TravelIntent
from app.services.eval_baselines import BasicRagPlanner, LLMOnlyPlanner
from app.services.extractor import extract_travel_intent
from app.services.retriever import retrieve_places

router = APIRouter(tags=["eval"])

_llm_only = LLMOnlyPlanner()
_basic_rag = BasicRagPlanner()


def _basic_retrieve(intent: TravelIntent) -> list:
    """City-match retrieval with no preference extraction or scoring."""
    bare_intent = TravelIntent(
        destination=intent.destination,
        duration_days=intent.duration_days,
        interests=[],
        avoid=[],
    )
    return retrieve_places(bare_intent)[:12]


@router.post("/eval/llm-only", response_model=ChatResponse)
def eval_llm_only(request: ChatRequest) -> ChatResponse:
    try:
        intent = extract_travel_intent(request.message)
        return _llm_only.plan(request, intent)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/eval/basic-rag", response_model=ChatResponse)
def eval_basic_rag(request: ChatRequest) -> ChatResponse:
    try:
        intent = extract_travel_intent(request.message)
        places = _basic_retrieve(intent)
        return _basic_rag.plan(request, intent, places)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/eval/compare")
def eval_compare(request: ChatRequest) -> dict:
    """Run all three systems against the same prompt and return results for comparison."""
    from app.services.orchestrator import TravelOrchestrator
    personalized = TravelOrchestrator()

    intent = extract_travel_intent(request.message)
    results: dict[str, dict] = {}
    errors: dict[str, str] = {}

    try:
        results["llm_only"] = _llm_only.plan(request, intent).model_dump()
    except Exception as exc:
        errors["llm_only"] = str(exc)

    try:
        basic_places = _basic_retrieve(intent)
        results["basic_rag"] = _basic_rag.plan(request, intent, basic_places).model_dump()
    except Exception as exc:
        errors["basic_rag"] = str(exc)

    try:
        results["personalized_rag"] = personalized.handle_chat(request).model_dump()
    except Exception as exc:
        errors["personalized_rag"] = str(exc)

    return {
        "prompt": request.message,
        "destination": intent.destination,
        "duration_days": intent.duration_days,
        "results": results,
        "errors": errors,
    }
