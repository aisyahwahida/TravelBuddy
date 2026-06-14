from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import (
    eval,
    export,
    google_places,
    health,
    open_data,
    reddit,
    sessions,
    travel,
)

app = FastAPI(
    title="TravelBuddy France API",
    version="0.1.0",
    description="AI travel buddy backend focused on local-style recommendations in France.",
)


@app.on_event("startup")
async def _prewarm() -> None:
    """Load the embedding model and cache before the first request hits."""
    try:
        from app.services.embedding_store import _get_cache, _get_model
        _get_model()
        _get_cache()
    except Exception:
        pass

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=(
        r"^http://(localhost|127\.0\.0\.1|\[::1\]):\d+$"
        r"|^http://travelbuddy-frontend-[a-z0-9-]+\.s3-website[-.][a-z0-9-]+\.amazonaws\.com$"
        r"|^http://[a-zA-Z0-9-]+\.elasticbeanstalk\.com$"
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

app.include_router(health.router)
app.include_router(travel.router, prefix="/api")
app.include_router(eval.router, prefix="/api")
app.include_router(export.router, prefix="/api")
app.include_router(reddit.router, prefix="/api")
app.include_router(google_places.router, prefix="/api")
app.include_router(open_data.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
