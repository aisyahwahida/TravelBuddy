from pydantic import BaseModel, Field


class Place(BaseModel):
    name: str
    city: str
    neighborhood: str = ""
    address: str = ""
    category: str
    reason: str
    local_tip: str
    tourist_trap_risk: str
    best_time: str = ""
    estimated_duration_minutes: int = Field(default=75, ge=15, le=360)
    latitude: float
    longitude: float
    map_source: str = ""
    map_url: str = ""
    price_label: str = ""
    google_maps_url: str = ""
    google_rating: float | None = None
    google_user_rating_count: int | None = None
    google_price_level: str = ""
    google_price_label: str = ""
    business_status: str = ""
    opening_hours: list[str] = Field(default_factory=list)
    open_now: bool | None = None
    open_status_label: str = ""
    tags: list[str] = Field(default_factory=list)
    source_type: str = "curated"
    source_title: str = ""
    source_url: str = ""
    confidence: float = Field(default=1.0, ge=0, le=1)


class TravelIntent(BaseModel):
    destination: str
    duration_days: int = Field(default=1, ge=1, le=14)
    request_intents: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    pace: str = "balanced"
    visit_day: str = ""
    budget: str = ""
    mood: str = ""
    travel_style: str = ""
    group_type: str = ""
    food_preference: str = ""
    indoor_outdoor: str = ""
    time_of_day: str = ""
    transportation: str = ""
    walking_constraints: str = ""
    assumptions: list[str] = Field(default_factory=list)
    clarification_question: str = ""


class ItineraryDay(BaseModel):
    day: int
    title: str
    summary: str
    stops: list[Place] = Field(default_factory=list)


class Itinerary(BaseModel):
    title: str
    summary: str
    destination: str
    themes: list[str]
    stops: list[Place]
    days: list[ItineraryDay] = Field(default_factory=list)
    avoidance_notes: list[str]
    practical_notes: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str
    history: list[dict[str, str]] = Field(default_factory=list)
    session_id: str = ""


class EvidenceItem(BaseModel):
    place_name: str
    source_type: str
    source_title: str
    source_url: str
    support_summary: str


class ChatResponse(BaseModel):
    assistant_message: str
    extracted_intent: TravelIntent
    itinerary: Itinerary
    session_id: str = ""
    evidence: list[EvidenceItem] = Field(default_factory=list)
    alternative_options: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class ExportRequest(BaseModel):
    itinerary: Itinerary
