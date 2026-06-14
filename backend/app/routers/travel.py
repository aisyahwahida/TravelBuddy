from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.schemas.travel import ChatRequest, ChatResponse
from app.services.orchestrator import TravelOrchestrator
from app.services.session_store import ensure_session_id, save_chat_turn

router = APIRouter(tags=["travel"])
orchestrator = TravelOrchestrator()


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    try:
        return orchestrator.handle_chat(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """
    SSE endpoint that pushes real pipeline-stage status events before the final result.

    Event types:
      status  – {"message": "..."}  sent before each pipeline stage
      result  – full ChatResponse JSON
      error   – {"message": "..."}
      done    – {}
    """

    async def generate():
        def fmt(event: str, data: str) -> str:
            return f"event: {event}\ndata: {data}\n\n"

        if not request.message.strip():
            yield fmt("error", json.dumps({"message": "Message cannot be empty."}))
            yield fmt("done", "{}")
            return

        session_id = ensure_session_id(request.session_id)

        # Fast path: answer follow-up questions from session context
        if orchestrator.should_try_followup(request):
            yield fmt("status", json.dumps({"message": "Looking up your itinerary…"}))
            followup = await run_in_threadpool(orchestrator.answer_followup, request, session_id)
            if followup:
                save_chat_turn(request, followup)
                yield fmt("result", followup.model_dump_json())
                yield fmt("done", "{}")
                return

        yield fmt("status", json.dumps({"message": "Analyzing your travel preferences..."}))
        intent = await run_in_threadpool(orchestrator.extract_intent, request)

        yield fmt(
            "status",
            json.dumps({"message": f"Finding the best places in {intent.destination}..."}),
        )
        places = await run_in_threadpool(orchestrator.fetch_places, intent)

        yield fmt(
            "status",
            json.dumps(
                {
                    "message": (
                        f"Building your {intent.duration_days}-day itinerary"
                        f" from {len(places)} candidate places..."
                    )
                }
            ),
        )

        try:
            response = await run_in_threadpool(
                orchestrator.plan, request, intent, places, session_id=session_id
            )
            save_chat_turn(request, response)
            yield fmt("result", response.model_dump_json())
        except ValueError as exc:
            yield fmt("error", json.dumps({"message": str(exc)}))

        yield fmt("done", "{}")

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
