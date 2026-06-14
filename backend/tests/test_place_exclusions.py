from app.services.place_exclusions import is_excluded_place


def test_is_excluded_place_matches_known_bad_entry() -> None:
    assert is_excluded_place("Fontaine Gilly", "Aix-en-Provence")


def test_is_excluded_place_keeps_normal_entry() -> None:
    assert not is_excluded_place("Musee d'Orsay", "Paris")
