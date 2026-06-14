from app.schemas.travel import Itinerary, Place, TravelIntent
from app.services.response_formatter import build_assistant_message


def _sample_place() -> Place:
    return Place(
        name="Musee d'Orsay",
        city="Paris",
        category="Museum",
        reason="Popular museum",
        local_tip="Go early",
        tourist_trap_risk="low",
        latitude=48.86,
        longitude=2.326,
        source_url="https://www.reddit.com/r/travel/",
    )


def test_build_assistant_message_deduplicates_assumption_prefix() -> None:
    intent = TravelIntent(
        destination="Paris",
        duration_days=3,
        assumptions=["Assumed a moderate budget."],
    )
    itinerary = Itinerary(
        title="Paris",
        summary="",
        destination="Paris",
        themes=[],
        stops=[],
        days=[],
        avoidance_notes=[],
    )

    message = build_assistant_message(intent, itinerary, [_sample_place()])

    assert "I assumed a moderate budget." in message
    assert "I assumed: assumed a moderate budget.." not in message
