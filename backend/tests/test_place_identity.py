import unittest

from app.services.place_identity import dedupe_place_dicts, place_identity_key


class PlaceIdentityTests(unittest.TestCase):
    def test_alias_names_for_same_place_collapse_to_one_entry(self) -> None:
        places = [
            {
                "name": "Jardin du Luxembourg",
                "city": "Paris",
                "category": "park",
                "latitude": 48.8462,
                "longitude": 2.3372,
                "source_url": "https://example.com/a",
            },
            {
                "name": "Luxembourg Gardens",
                "city": "Paris",
                "category": "parks",
                "latitude": 48.8421,
                "longitude": 2.3311,
                "photo_name": "photo-1",
            },
            {
                "name": "Luxembourg Gardens (Jardin du Luxembourg)",
                "city": "Paris",
                "category": "Park",
                "latitude": 48.8462,
                "longitude": 2.3372,
                "google_maps_url": "https://www.google.com/maps/search/?api=1&query=48.8462,2.3372",
            },
        ]

        deduped = dedupe_place_dicts(places)

        self.assertEqual(len(deduped), 1)
        merged = deduped[0]
        self.assertTrue(merged.get("photo_name"))
        self.assertTrue(merged.get("source_url") or merged.get("google_maps_url"))

    def test_place_identity_key_matches_translated_aliases(self) -> None:
        a = {"name": "Jardin du Luxembourg", "city": "Paris", "category": "park"}
        b = {"name": "Luxembourg Gardens", "city": "Paris", "category": "parks"}

        self.assertEqual(place_identity_key(a), place_identity_key(b))

    def test_place_identity_key_matches_singular_plural_name_variants(self) -> None:
        a = {"name": "Champ de Mars", "city": "Paris", "category": "park"}
        b = {"name": "Champs de Mars", "city": "Paris", "category": "park"}

        self.assertEqual(place_identity_key(a), place_identity_key(b))

    def test_louvre_english_and_french_aliases_collapse(self) -> None:
        a = {"name": "Louvre Museum", "city": "Paris", "category": "Museum"}
        b = {"name": "Musee du Louvre", "city": "Paris", "category": "Museum"}

        self.assertEqual(place_identity_key(a), place_identity_key(b))

    def test_louvre_must_go_category_matches_regular_museum(self) -> None:
        a = {"name": "Louvre Museum", "city": "Paris", "category": "must-go museum"}
        b = {"name": "Musee du Louvre", "city": "Paris", "category": "museum"}

        self.assertEqual(place_identity_key(a), place_identity_key(b))


if __name__ == "__main__":
    unittest.main()
