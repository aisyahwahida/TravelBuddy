import unittest
from unittest.mock import patch

from app.schemas.travel import ChatRequest, ChatResponse, Itinerary, ItineraryDay, LocationAnchor, Place, TravelIntent
from app.services.orchestrator import TravelOrchestrator, _is_stay_reroute_request, _response_underfills_request


def make_place(name: str, category: str, tags: list[str], lat: float) -> Place:
    return Place(
        name=name,
        city="Paris",
        category=category,
        reason=f"Reason for {name}",
        local_tip="",
        tourist_trap_risk="low",
        latitude=lat,
        longitude=2.35,
        tags=tags,
        source_url="https://www.reddit.com/r/travel/",
    )


def make_multi_day_places() -> list[Place]:
    return [
        make_place("Eiffel Tower", "Landmark", ["must_go", "landmark"], 48.8584),
        make_place("Louvre Museum", "Museum", ["museum"], 48.8606),
        make_place("Luxembourg Gardens", "Park", ["park"], 48.8462),
        make_place("Seine Walk", "Walk", ["walks"], 48.8570),
        make_place("Le Comptoir", "Restaurant", ["restaurant"], 48.8521),
        make_place("Marche Bastille", "Market", ["market"], 48.8532),
        make_place("Musee Rodin", "Museum", ["museum"], 48.8553),
        make_place("Tuileries Garden", "Park", ["park"], 48.8635),
        make_place("Montmartre", "Neighborhood", ["walks"], 48.8867),
        make_place("Cafe de Flore", "Cafe", ["cafe"], 48.8546),
        make_place("Notre Dame", "Landmark", ["must_go", "landmark"], 48.8530),
        make_place("Canal Saint-Martin", "Neighborhood", ["walks"], 48.8721),
    ]


class _FakePlanner:
    def __init__(self, response: ChatResponse) -> None:
        self._response = response

    def plan(self, request, intent, candidates, previous_itinerary=None) -> ChatResponse:
        return self._response


class OrchestratorDurationGuardrailsTests(unittest.TestCase):
    def test_hotel_transit_question_does_not_trigger_reroute_shortcut(self) -> None:
        self.assertFalse(
            _is_stay_reroute_request(
                "im planning to stay at hotel la canopee. is there any metro around there"
            )
        )

    def test_underfill_detection_flags_multi_day_plan_with_too_few_stops(self) -> None:
        intent = TravelIntent(destination="Paris", duration_days=6, interests=["family"])
        itinerary = Itinerary(
            title="Paris",
            summary="",
            destination="Paris",
            themes=[],
            stops=[
                make_place("Stop A", "Park", ["park"], 48.85),
                make_place("Stop B", "Museum", ["museum"], 48.86),
                make_place("Stop C", "Restaurant", ["restaurant"], 48.87),
                make_place("Stop D", "Landmark", ["landmark"], 48.88),
            ],
            days=[
                ItineraryDay(
                    day=1,
                    title="Day 1 - Family day",
                    summary="",
                    stops=[],
                )
            ],
            avoidance_notes=[],
        )
        response = ChatResponse(
            assistant_message="1-day Paris plan ready: 4 stops, balanced pace.",
            extracted_intent=TravelIntent(destination="Paris", duration_days=1),
            itinerary=itinerary,
        )

        self.assertTrue(_response_underfills_request(response, intent))

    def test_plan_preserves_requested_duration_and_rebuilds_underfilled_output(self) -> None:
        intent = TravelIntent(
            destination="Paris",
            duration_days=6,
            interests=["family", "parks", "museum"],
            request_intents=["itinerary", "family_trip"],
        )
        places = make_multi_day_places()
        weak_itinerary = Itinerary(
            title="Paris",
            summary="",
            destination="Paris",
            themes=[],
            stops=places[:4],
            days=[
                ItineraryDay(
                    day=1,
                    title="Day 1 - Family day",
                    summary="",
                    stops=places[:4],
                )
            ],
            avoidance_notes=[],
        )
        weak_response = ChatResponse(
            assistant_message="1-day Paris plan ready: 4 stops, balanced pace.",
            extracted_intent=TravelIntent(destination="Paris", duration_days=1),
            itinerary=weak_itinerary,
        )
        orchestrator = TravelOrchestrator()
        orchestrator.ai_planner = _FakePlanner(weak_response)

        response = orchestrator.plan(
            ChatRequest(message="Plan me 6 family days in Paris"),
            intent,
            places,
            session_id="test-session",
        )

        self.assertEqual(response.extracted_intent.duration_days, 6)
        self.assertEqual(len(response.itinerary.days), 6)
        self.assertTrue(response.assistant_message.startswith("6-days Paris plan ready"))

    @patch("app.services.orchestrator.save_chat_turn")
    def test_handle_chat_uses_followup_fast_path_for_hotel_reroute(self, mock_save) -> None:
        orchestrator = TravelOrchestrator()
        followup_response = ChatResponse(
            assistant_message="Updated the route to start from Hotel Tourisme Avenue.",
            extracted_intent=TravelIntent(destination="Paris", duration_days=3, stay_location="Hotel Tourisme Avenue"),
            itinerary=Itinerary(
                title="Paris",
                summary="",
                destination="Paris",
                themes=[],
                stops=[],
                days=[],
                avoidance_notes=[],
                start_location=LocationAnchor(
                    name="Hotel Tourisme Avenue",
                    city="Paris",
                    latitude=48.855,
                    longitude=2.298,
                ),
            ),
            session_id="followup-session",
            is_followup=True,
        )
        request = ChatRequest(
            message="Can you redo the map from my hotel near Champ de Mars?",
            history=[{"role": "user", "content": "Plan me 3 days in Paris"}],
            session_id="followup-session",
        )

        with patch.object(orchestrator, "answer_followup", return_value=followup_response) as mock_answer, \
             patch.object(orchestrator, "extract_intent", side_effect=AssertionError("extract_intent should not run")), \
             patch.object(orchestrator, "fetch_places", side_effect=AssertionError("fetch_places should not run")), \
             patch.object(orchestrator, "plan", side_effect=AssertionError("plan should not run")):
            response = orchestrator.handle_chat(request)

        self.assertTrue(response.is_followup)
        self.assertEqual(response.itinerary.start_location.name, "Hotel Tourisme Avenue")
        mock_answer.assert_called_once()
        mock_save.assert_called_once()

    @patch("app.services.orchestrator.save_chat_turn")
    def test_handle_chat_uses_stay_reroute_even_without_history_when_session_exists(self, mock_save) -> None:
        orchestrator = TravelOrchestrator()
        followup_response = ChatResponse(
            assistant_message="Updated the route to start from Champ de Mars.",
            extracted_intent=TravelIntent(destination="Paris", duration_days=2, stay_location="Champ de Mars"),
            itinerary=Itinerary(
                title="Paris",
                summary="",
                destination="Paris",
                themes=[],
                stops=[],
                days=[],
                avoidance_notes=[],
                start_location=LocationAnchor(
                    name="Champ de Mars",
                    city="Paris",
                    latitude=48.8558,
                    longitude=2.2983,
                ),
            ),
            session_id="followup-session",
            is_followup=True,
        )
        request = ChatRequest(
            message="Redo the map from my hotel near Champ de Mars.",
            history=[],
            session_id="followup-session",
        )

        with patch.object(orchestrator, "answer_followup", return_value=followup_response) as mock_answer, \
             patch.object(orchestrator, "extract_intent", side_effect=AssertionError("extract_intent should not run")), \
             patch.object(orchestrator, "fetch_places", side_effect=AssertionError("fetch_places should not run")), \
             patch.object(orchestrator, "plan", side_effect=AssertionError("plan should not run")):
            response = orchestrator.handle_chat(request)

        self.assertTrue(response.is_followup)
        self.assertEqual(response.itinerary.start_location.name, "Champ de Mars")
        mock_answer.assert_called_once()
        mock_save.assert_called_once()

    @patch("app.services.orchestrator._resolve_stay_anchor")
    @patch.object(TravelOrchestrator, "extract_intent")
    @patch("app.services.orchestrator._load_previous_intent")
    @patch("app.services.orchestrator._load_previous_itinerary")
    def test_answer_followup_reroutes_itinerary_from_stay_location(
        self,
        mock_previous_itinerary,
        mock_previous_intent,
        mock_extract_intent,
        mock_resolve_stay_anchor,
    ) -> None:
        previous_intent = TravelIntent(destination="Paris", duration_days=2, interests=["cafes", "restaurants"])
        previous_itinerary = Itinerary(
            title="Paris",
            summary="",
            destination="Paris",
            themes=[],
            stops=[
                make_place("Cafe des Musees", "Cafe", ["cafe"], 48.8601),
                make_place("Le Chardenoux", "Restaurant", ["restaurant"], 48.8652),
                make_place("Carette", "Cafe", ["cafe"], 48.8674),
                make_place("Bistrot Instinct", "Restaurant", ["restaurant"], 48.8689),
            ],
            days=[],
            avoidance_notes=[],
        )
        stay_anchor = LocationAnchor(
            name="Hotel Tourisme Avenue",
            city="Paris",
            address="66 Avenue de la Motte-Picquet",
            latitude=48.8503,
            longitude=2.2999,
            google_maps_url="https://maps.google.com/?q=Hotel+Tourisme+Avenue",
        )
        mock_previous_intent.return_value = previous_intent
        mock_previous_itinerary.return_value = previous_itinerary
        mock_extract_intent.return_value = previous_intent.model_copy(
            update={"stay_location": "Hotel Tourisme Avenue"}
        )
        mock_resolve_stay_anchor.return_value = stay_anchor

        orchestrator = TravelOrchestrator()
        response = orchestrator.answer_followup(
            ChatRequest(
                message="Please redo the route from my hotel near Champ de Mars.",
                history=[{"role": "user", "content": "Plan me 2 days in Paris"}],
                session_id="followup-session",
            ),
            "followup-session",
        )

        self.assertIsNotNone(response)
        assert response is not None
        self.assertTrue(response.is_followup)
        self.assertEqual(response.extracted_intent.stay_location, "Hotel Tourisme Avenue")
        self.assertIsNotNone(response.itinerary.start_location)
        self.assertEqual(response.itinerary.start_location.name, "Hotel Tourisme Avenue")
        self.assertTrue(response.assistant_message.startswith("Updated the route to start from"))


if __name__ == "__main__":
    unittest.main()
