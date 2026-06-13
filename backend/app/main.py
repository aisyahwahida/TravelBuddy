from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import (
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

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1|\[::1\]):\d+$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(travel.router, prefix="/api")
app.include_router(export.router, prefix="/api")
app.include_router(reddit.router, prefix="/api")
app.include_router(google_places.router, prefix="/api")
app.include_router(open_data.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
