from app.schemas.travel import AlternativePlace, ChatResponse, Itinerary, ItineraryDay, Place, TravelIntent
from app.services.place_safety import is_closed_place, sanitize_response
from app.services.response_formatter import build_alternative_options


def _place(
    name: str,
    business_status: str = "",
    open_status_label: str = "",
) -> Place:
    return Place(
        name=name,
        city="Paris",
        category="Museum",
        reason="Popular stop",
        local_tip="Go early",
        tourist_trap_risk="low",
        latitude=48.86,
        longitude=2.326,
        business_status=business_status,
        open_status_label=open_status_label,
        source_url="https://example.com",
    )


def test_is_closed_place_treats_temporary_closures_as_closed() -> None:
    assert is_closed_place(_place("Temp Closed", business_status="CLOSED_TEMPORARILY"))
    assert is_closed_place(_place("Temp Closed Label", open_status_label="Temporarily closed according to Google Maps"))


def test_sanitize_response_removes_temporarily_closed_places() -> None:
    open_place = _place("Open Place")
    temp_closed = _place("Temp Closed", business_status="CLOSED_TEMPORARILY")
    response = ChatResponse(
        assistant_message="Paris plan ready with Open Place and Temp Closed.",
        extracted_intent=TravelIntent(destination="Paris"),
        itinerary=Itinerary(
            title="Paris",
            summary="",
            destination="Paris",
            themes=[],
            stops=[open_place, temp_closed],
            days=[ItineraryDay(day=1, title="Day 1", summary="", stops=[open_place, temp_closed])],
            avoidance_notes=[],
        ),
        evidence=[],
        alternative_options=[AlternativePlace(name="Temp Closed", city="Paris"), AlternativePlace(name="Open Place", city="Paris")],
    )

    sanitized = sanitize_response(response)

    assert [place.name for place in sanitized.itinerary.stops] == ["Open Place"]
    assert [place.name for place in sanitized.itinerary.days[0].stops] == ["Open Place"]
    assert "Temp Closed" not in sanitized.assistant_message


def test_build_alternative_options_skips_temporarily_closed_places() -> None:
    open_place = _place("Open Place")
    temp_closed = _place("Temp Closed", business_status="CLOSED_TEMPORARILY")

    alternatives = build_alternative_options([temp_closed, open_place])

    assert [place.name for place in alternatives] == ["Open Place"]
