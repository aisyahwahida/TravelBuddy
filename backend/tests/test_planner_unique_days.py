import unittest

from app.schemas.travel import Place
from app.services.planner import MAX_DAY_LEG_MINUTES, _estimated_leg_minutes, split_stops_by_day


def make_place(
    name: str,
    category: str,
    tags: list[str],
    lat: float,
    lon: float = 2.35,
    city: str = "Paris",
) -> Place:
    return Place(
        name=name,
        city=city,
        category=category,
        reason=f"Reason for {name}",
        local_tip="",
        tourist_trap_risk="low",
        latitude=lat,
        longitude=lon,
        tags=tags,
    )


class SplitStopsByDayTests(unittest.TestCase):
    def test_places_do_not_repeat_across_days_when_padding(self) -> None:
        stops = [
            make_place("Musee A", "museum", ["museum"], 48.850),
            make_place("Park A", "park", ["park"], 48.851),
            make_place("Cafe A", "cafe", ["cafe"], 48.852),
            make_place("Restaurant A", "restaurant", ["restaurant"], 48.853),
            make_place("Market A", "market", ["market"], 48.854),
            make_place("Museum B", "museum", ["museum"], 48.855),
        ]

        days = split_stops_by_day(stops, duration_days=2, force_full_day=True)
        flattened = [stop for day in days for stop in day.stops]
        flattened_keys = [(stop.name.lower(), stop.city.lower()) for stop in flattened]

        self.assertEqual(len(flattened_keys), len(set(flattened_keys)))

    def test_cafes_named_after_museums_do_not_force_museum_day_title(self) -> None:
        stops = [
            make_place("Cafe des Musees", "cafe", ["cafe"], 48.850),
            make_place("Carette", "cafe", ["cafe"], 48.851),
            make_place("Le Chardenoux", "restaurant", ["restaurant"], 48.852),
            make_place("Bistrot Instinct", "restaurant", ["restaurant"], 48.853),
        ]

        days = split_stops_by_day(stops, duration_days=1, force_full_day=True)

        self.assertEqual(len(days), 1)
        self.assertNotIn("Museum hopping day", days[0].title)

    def test_long_itinerary_balances_four_to_six_stops_per_day(self) -> None:
        stops = [
            make_place(f"Museum {index}", "museum", ["museum"], 48.800 + index * 0.001)
            for index in range(24)
        ] + [
            make_place(f"Restaurant {index}", "restaurant", ["restaurant"], 48.850 + index * 0.001)
            for index in range(12)
        ] + [
            make_place(f"Park {index}", "park", ["park"], 48.880 + index * 0.001)
            for index in range(12)
        ]

        days = split_stops_by_day(stops, duration_days=8, force_full_day=True)
        counts = [len(day.stops) for day in days]

        self.assertEqual(len(days), 8)
        self.assertTrue(all(4 <= count <= 6 for count in counts), counts)

    def test_displayed_day_route_drops_impossible_long_legs(self) -> None:
        stops = [
            make_place("Paris Museum", "museum", ["museum"], 48.850, 2.350),
            make_place("Paris Park", "park", ["park"], 48.852, 2.352),
            make_place("Paris Cafe", "cafe", ["cafe"], 48.854, 2.354),
            make_place("Paris Market", "market", ["market"], 48.856, 2.356),
            make_place("Nice Museum", "museum", ["museum"], 43.700, 7.260, city="Nice"),
        ]

        days = split_stops_by_day(stops, duration_days=1, force_full_day=True)
        route = days[0].stops
        leg_minutes = [
            _estimated_leg_minutes(route[index - 1], route[index])
            for index in range(1, len(route))
        ]

        self.assertGreaterEqual(len(route), 4)
        self.assertTrue(
            all(minutes <= MAX_DAY_LEG_MINUTES for minutes in leg_minutes),
            leg_minutes,
        )


if __name__ == "__main__":
    unittest.main()
