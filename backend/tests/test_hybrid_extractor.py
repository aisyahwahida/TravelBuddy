import unittest
from unittest.mock import patch

from app.services.extractor import HybridIntentHint, extract_travel_intent


class HybridExtractorTests(unittest.TestCase):
    @patch("app.services.extractor._extract_with_luxia")
    def test_explicit_duration_from_user_wins_over_conflicting_luxia_hint(self, mock_extract) -> None:
        mock_extract.return_value = HybridIntentHint(
            destination="Paris",
            duration_days=1,
            interests=["family", "parks"],
            request_intents=["itinerary", "family_trip"],
        )

        intent = extract_travel_intent(
            "we're a family of four with two kids aged 8 and 11, "
            "it's our first time in paris and we'll stay for 6 days"
        )

        self.assertEqual(intent.duration_days, 6)
        self.assertEqual(intent.destination, "Paris")
        self.assertIn("family_trip", intent.request_intents)

    @patch("app.services.extractor._extract_with_luxia")
    def test_luxia_can_fill_soft_fields_when_prompt_is_vague(self, mock_extract) -> None:
        mock_extract.return_value = HybridIntentHint(
            destination="Paris",
            mood="relaxed",
            pace="slow",
            food_preference="japanese",
            request_intents=["itinerary", "food_recommendation"],
            interests=["ramen", "quiet"],
        )

        intent = extract_travel_intent("plan something cozy in paris")

        self.assertEqual(intent.destination, "Paris")
        self.assertEqual(intent.pace, "slow")
        self.assertEqual(intent.food_preference, "japanese")
        self.assertIn("food_recommendation", intent.request_intents)
        self.assertIn("quiet", intent.interests)

    def test_word_number_duration_is_parsed_without_hardcoding_a_prompt(self) -> None:
        intent = extract_travel_intent("I need a six day trip in Lyon with museums and food.")

        self.assertEqual(intent.duration_days, 6)
        self.assertEqual(intent.destination, "Lyon")
        self.assertTrue({"museum", "museums"}.intersection(intent.interests))

    def test_stay_location_is_extracted_from_hotel_phrase(self) -> None:
        intent = extract_travel_intent(
            "Redo the map from my hotel near Champ de Mars-Tour Eiffel in Paris for 3 days."
        )

        self.assertEqual(intent.destination, "Paris")
        self.assertEqual(intent.duration_days, 3)
        self.assertEqual(intent.stay_location, "Champ de Mars-Tour Eiffel in Paris")


if __name__ == "__main__":
    unittest.main()
