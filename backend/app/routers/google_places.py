from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services.google_places import (
    DATA_PATH,
    backfill_google_place_photos,
    refresh_google_places,
    resolve_source_image,
)

router = APIRouter(tags=["google-places"])


@router.get("/google-places/status")
def google_places_status() -> dict:
    return {
        "cache_exists": DATA_PATH.exists(),
        "cache_path": str(DATA_PATH),
    }


@router.post("/google-places/refresh")
def google_places_refresh() -> dict:
    try:
        return refresh_google_places()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/google-places/backfill-photos")
def google_places_backfill_photos(limit: int | None = None) -> dict:
    try:
        return backfill_google_place_photos(limit=limit)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/google-places/source-image")
def google_places_source_image(
    source_url: str = Query(default="", min_length=1),
) -> dict:
    return {"image_url": resolve_source_image(source_url)}
