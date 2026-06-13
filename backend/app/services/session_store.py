"""Session persistence — DynamoDB when available, local JSON files as fallback."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.schemas.travel import ChatRequest, ChatResponse, Itinerary
from app.services.place_safety import sanitize_itinerary

logger = logging.getLogger(__name__)

SESSION_DIR = Path(__file__).resolve().parents[1] / "data" / "sessions"
DYNAMO_TABLE = os.environ.get("SESSION_TABLE", "travelbuddy-sessions")
DYNAMO_REGION = os.environ.get("AWS_REGION", "us-east-1")

_table = None
_table_checked = False


def _get_table():
    """Return a boto3 DynamoDB Table, or None if unavailable."""
    global _table, _table_checked
    if _table_checked:
        return _table
    _table_checked = True
    try:
        import boto3
        dynamodb = boto3.resource("dynamodb", region_name=DYNAMO_REGION)
        tbl = dynamodb.Table(DYNAMO_TABLE)
        tbl.load()  # DescribeTable — confirms the table exists and creds work
        _table = tbl
        logger.info("DynamoDB session store ready (table=%s)", DYNAMO_TABLE)
    except Exception as exc:
        logger.warning("DynamoDB unavailable, using file fallback: %s", exc)
        _table = None
    return _table


# ── helpers ──────────────────────────────────────────────────────────────────

def ensure_session_id(session_id: str = "") -> str:
    return session_id.strip() or str(uuid4())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── file-backed store (local dev / DynamoDB fallback) ─────────────────────────

def _file_path(session_id: str) -> Path:
    safe = "".join(ch for ch in session_id if ch.isalnum() or ch in {"-", "_"})
    return SESSION_DIR / f"{safe}.json"


def _file_read(session_id: str) -> dict:
    path = _file_path(session_id)
    if not path.exists():
        now = _now_iso()
        return {"session_id": session_id, "created_at": now, "updated_at": now,
                "turns": [], "latest_itinerary": None}
    return json.loads(path.read_text(encoding="utf-8"))


def _file_write(session: dict) -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    _file_path(session["session_id"]).write_text(
        json.dumps(session, indent=2, ensure_ascii=True), encoding="utf-8"
    )


def _sanitize_session(session: dict) -> dict:
    latest = session.get("latest_itinerary")
    if latest:
        session["latest_itinerary"] = sanitize_itinerary(
            Itinerary.model_validate(latest)
        ).model_dump()
    return session


# ── DynamoDB-backed store ─────────────────────────────────────────────────────
# We serialize the full session dict to a JSON *string* stored in a single
# "data" attribute. This avoids boto3's Decimal/float issues entirely.

def _dynamo_read(session_id: str) -> dict | None:
    table = _get_table()
    if table is None:
        return None
    try:
        resp = table.get_item(Key={"session_id": session_id})
        item = resp.get("Item")
        if not item:
            return None
        return _sanitize_session(json.loads(item["data"]))
    except Exception as exc:
        logger.warning("DynamoDB read failed: %s", exc)
        return None


def _dynamo_write(session: dict) -> None:
    table = _get_table()
    if table is None:
        return
    try:
        table.put_item(Item={
            "session_id": session["session_id"],
            "updated_at": session.get("updated_at", _now_iso()),
            "data": json.dumps(session, ensure_ascii=True),
        })
    except Exception as exc:
        logger.warning("DynamoDB write failed: %s", exc)


def _dynamo_list() -> list[dict] | None:
    table = _get_table()
    if table is None:
        return None
    try:
        resp = table.scan(
            ProjectionExpression="session_id, updated_at, #d",
            ExpressionAttributeNames={"#d": "data"},
        )
        result = []
        for item in resp.get("Items", []):
            data = json.loads(item.get("data", "{}"))
            data = _sanitize_session(data)
            result.append({
                "session_id": item["session_id"],
                "created_at": data.get("created_at", ""),
                "updated_at": item.get("updated_at", ""),
                "turn_count": len(data.get("turns", [])),
                "latest_destination": (data.get("latest_itinerary") or {}).get("destination", ""),
            })
        return sorted(result, key=lambda x: x["updated_at"], reverse=True)
    except Exception as exc:
        logger.warning("DynamoDB scan failed: %s", exc)
        return None


# ── public API ────────────────────────────────────────────────────────────────

def _read_session(session_id: str) -> dict:
    data = _dynamo_read(session_id)
    if data is not None:
        return data
    return _sanitize_session(_file_read(session_id))


def save_chat_turn(request: ChatRequest, response: ChatResponse) -> None:
    response = response.model_copy(
        update={"itinerary": sanitize_itinerary(response.itinerary)}
    )
    session = _read_session(response.session_id)
    session["updated_at"] = _now_iso()
    session["latest_itinerary"] = response.itinerary.model_dump()
    session["turns"].append({
        "user_message": request.message,
        "assistant_message": response.assistant_message,
        "intent": response.extracted_intent.model_dump(),
        "evidence": [item.model_dump() for item in response.evidence],
    })
    _dynamo_write(session)
    _file_write(session)  # always keep local copy as safety net


def list_sessions() -> list[dict]:
    dynamo = _dynamo_list()
    if dynamo is not None:
        return dynamo
    # file fallback
    if not SESSION_DIR.exists():
        return []
    sessions = []
    for path in SESSION_DIR.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        data = _sanitize_session(data)
        sessions.append({
            "session_id": data.get("session_id", path.stem),
            "created_at": data.get("created_at", ""),
            "updated_at": data.get("updated_at", ""),
            "turn_count": len(data.get("turns", [])),
            "latest_destination": (data.get("latest_itinerary") or {}).get("destination", ""),
        })
    return sorted(sessions, key=lambda x: x["updated_at"], reverse=True)


def get_session(session_id: str) -> dict:
    data = _dynamo_read(session_id)
    if data is not None:
        return data
    path = _file_path(session_id)
    if not path.exists():
        raise FileNotFoundError(session_id)
    return _sanitize_session(json.loads(path.read_text(encoding="utf-8")))
