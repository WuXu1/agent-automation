"""Offline tests for forecast.py: place resolution from crew.json and output formatting.

Run from this folder: python3 -m unittest
No network: geocoding is faked and the forecast is a canned Open-Meteo response.
"""
import json
import os
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

import forecast

HOME = {"name": "Testford", "lat": 52.2, "lon": 0.12}


def write_crew(folder, data):
    path = os.path.join(folder, "crew.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


def canned():
    """A small Open-Meteo-shaped response: 24 hourly rows on 2026-10-14 and two days."""
    times = [f"2026-10-14T{h:02d}:00" for h in range(24)]
    return {
        "current": {"temperature_2m": 11.4, "apparent_temperature": 8.6, "relative_humidity_2m": 81,
                    "weather_code": 61, "wind_speed_10m": 14.2, "wind_gusts_10m": 31.0},
        "hourly": {
            "time": times,
            "temperature_2m": [10.0 + h * 0.1 for h in range(24)],
            "apparent_temperature": [8.0] * 24,
            "precipitation_probability": [60] * 24,
            "precipitation": [0.2 if h < 9 else 0.0 for h in range(24)],
            "weather_code": [61] * 24,
            "wind_speed_10m": [12.0] * 24,
            "wind_gusts_10m": [25.0] * 24,
        },
        "daily": {
            "time": ["2026-10-14", "2026-10-15"],
            "weather_code": [61, 3],
            "temperature_2m_min": [7.2, 6.0],
            "temperature_2m_max": [13.8, 12.1],
            "precipitation_sum": [3.4, None],
            "precipitation_probability_max": [80, 20],
            "wind_speed_10m_max": [20.0, 15.0],
            "wind_gusts_10m_max": [41.0, 30.0],
            "sunrise": ["2026-10-14T07:25", "2026-10-15T07:27"],
            "sunset": ["2026-10-14T18:10", "2026-10-15T18:08"],
        },
    }


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_reads_home_and_timezone(self):
        cfg = forecast.load_config(write_crew(self.tmp.name, {"home": HOME, "timezone": "Europe/Paris"}))
        self.assertEqual(forecast.home_place(cfg), ("Testford", 52.2, 0.12))
        self.assertEqual(forecast.timezone_of(cfg), (ZoneInfo("Europe/Paris"), "Europe/Paris"))

    def test_missing_file_falls_back_to_utc(self):
        cfg = forecast.load_config(os.path.join(self.tmp.name, "nope.json"))
        self.assertEqual(cfg, {})
        self.assertIsNone(forecast.home_place(cfg))
        self.assertEqual(forecast.timezone_of(cfg)[1], "UTC")

    def test_unknown_timezone_falls_back_to_utc(self):
        self.assertEqual(forecast.timezone_of({"timezone": "Mars/Olympus"})[1], "UTC")

    def test_bad_home_is_ignored(self):
        self.assertIsNone(forecast.home_place({"home": {"name": "X", "lat": "north"}}))
        self.assertIsNone(forecast.home_place({"home": "Testford"}))

    def test_wind_unit(self):
        self.assertEqual(forecast.wind_unit({}), "km/h")
        self.assertEqual(forecast.wind_unit({"wind_unit": "mph"}), "mph")


class ResolvePlaceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = forecast.load_config(write_crew(tmp.name, {"home": HOME, "timezone": "Europe/London"}))

    def no_network(self, name):
        raise AssertionError(f"geocoder should not be called for {name!r}")

    def test_no_place_uses_home(self):
        self.assertEqual(forecast.resolve_place(None, None, None, self.cfg, self.no_network), ("Testford", 52.2, 0.12))

    def test_home_name_uses_home_without_lookup(self):
        self.assertEqual(forecast.resolve_place("testford", None, None, self.cfg, self.no_network)[1:], (52.2, 0.12))

    def test_lat_lon_wins(self):
        self.assertEqual(forecast.resolve_place("Anywhere", 1.5, 2.25, self.cfg, self.no_network), ("1.50, 2.25", 1.5, 2.25))

    def test_only_one_coordinate_is_an_error(self):
        with self.assertRaises(forecast.UsageError):
            forecast.resolve_place(None, 1.5, None, self.cfg, self.no_network)

    def test_no_place_and_no_home_is_a_clear_error(self):
        with self.assertRaises(forecast.UsageError) as ctx:
            forecast.resolve_place(None, None, None, {}, self.no_network)
        self.assertIn("no home place set", str(ctx.exception))

    def test_prefers_match_near_home(self):
        results = [
            {"name": "Cambridge", "admin1": "Massachusetts", "country": "United States", "latitude": 42.37, "longitude": -71.11},
            {"name": "Cambridge", "admin1": "England", "country": "United Kingdom", "latitude": 52.2, "longitude": 0.12},
        ]
        label, lat, lon = forecast.resolve_place("Cambridge", None, None, self.cfg, lambda q: results)
        self.assertEqual(label, "Cambridge, England, United Kingdom")
        self.assertEqual((lat, lon), (52.2, 0.12))

    def test_far_away_only_match_is_used(self):
        results = [{"name": "Lima", "country": "Peru", "latitude": -12.05, "longitude": -77.04}]
        self.assertEqual(forecast.resolve_place("Lima", None, None, self.cfg, lambda q: results)[0], "Lima, Peru")

    def test_unknown_place_is_an_error(self):
        with self.assertRaises(forecast.UsageError):
            forecast.resolve_place("Nowhereville", None, None, self.cfg, lambda q: [])


class FormatTests(unittest.TestCase):
    def test_now(self):
        lines = forecast.format_now(canned(), "Testford", 52.2, 0.12, datetime(2026, 10, 14, 10, 30), "Europe/London", "mph")
        self.assertEqual(lines[0], "Testford (52.20, 0.12), Wed 14 Oct 10:30 Europe/London")
        self.assertEqual(lines[1], "Now: 11C (feels 9), light rain, wind 14 mph gusting 31, humidity 81%")
        # 12h window (22:30 the day before, 10:30]: rows 00..10, of which 00..08 had 0.2 mm each = 1.8 mm
        self.assertEqual(lines[2], "Rain in the last 12h: 1.8 mm (ground probably wet; a guess)")
        self.assertEqual(lines[3], "Next 6 hours:")
        hours = lines[4:-1]
        self.assertEqual(len(hours), 6)
        self.assertEqual(hours[0], "  11:00  11C (feels 8)  rain 60% 0.0mm  wind 12 gust 25 mph  light rain")
        self.assertTrue(lines[-1].startswith("Source: Open-Meteo"))

    def test_day(self):
        lines = forecast.format_day(canned(), "Testford", 52.2, 0.12, "2026-10-14", (7, 9), "km/h")
        self.assertEqual(lines[0], "Testford (52.20, 0.12), Wednesday 14 Oct")
        self.assertEqual(lines[1], "Day: 7-14C, light rain, rain 80% chance / 3.4mm, wind up to 20 km/h (gusts 41), "
                                   "sunrise 07:25 sunset 18:10")
        self.assertEqual([l.split()[0] for l in lines[2:-1]], ["07:00", "08:00", "09:00"])

    def test_week_handles_missing_values(self):
        lines = forecast.format_week(canned(), "Testford", 52.2, 0.12, 2, "km/h")
        self.assertEqual(lines[0], "Testford (52.20, 0.12), next 2 days")
        self.assertEqual(lines[2], "  Thu 15 Oct  6-12C  rain 20% ?  wind 15 gust 30 km/h  overcast")
        self.assertIn("rough guide", lines[-1])

    def test_parse_hours(self):
        self.assertEqual(forecast.parse_hours(None), (6, 22))
        self.assertEqual(forecast.parse_hours("7-9"), (7, 9))
        self.assertEqual(forecast.parse_hours("18"), (18, 18))
        for bad in ("9-7", "seven", "7-25"):
            with self.assertRaises(forecast.UsageError):
                forecast.parse_hours(bad)


if __name__ == "__main__":
    unittest.main()
