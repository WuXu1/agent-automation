#!/usr/bin/env python3
"""Weather from Open-Meteo (free, no key). Read-only: it only calls open-meteo.com.

Usage:
  forecast.py now  [PLACE]                    current conditions, rain in the last 12h, next 6 hours
  forecast.py day  [PLACE] [--date YYYY-MM-DD] [--hours 7-10]   hourly lines for one day (default today, 06-22)
  forecast.py week [PLACE] [--days N]         one line per day (default 7, max 16)
PLACE is a name ("Leeds", "Central Park") or --lat X --lon Y. Default: the home place in
/data/.hermes/crew.json ("home": {"name", "lat", "lon"}). Times are in crew.json's
"timezone" (UTC if unset), temperatures in C, rain in mm, wind in km/h (or mph when
crew.json has "wind_unit": "mph").
Standard library only.
"""
import argparse
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CREW_JSON = os.environ.get("CREW_JSON", "/data/.hermes/crew.json")
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
NEARBY_KM = 300  # a name match this close to home beats a bigger place far away
SOURCE = "Source: Open-Meteo (model forecast, not an official weather warning)"
WMO = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "rime fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light showers", 81: "showers", 82: "heavy showers", 85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with hail",
}


class UsageError(Exception):
    """A bad request (no place, bad date): shown to the agent as a plain message."""


def load_config(path=None):
    """crew.json as a dict; {} when it is missing or unreadable."""
    try:
        with open(path or CREW_JSON, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def home_place(config):
    """(name, lat, lon) from crew.json's "home", or None."""
    home = config.get("home")
    if not isinstance(home, dict):
        return None
    try:
        return str(home.get("name") or "Home"), float(home["lat"]), float(home["lon"])
    except (KeyError, TypeError, ValueError):
        return None


def timezone_of(config):
    """(ZoneInfo, name) from crew.json's "timezone"; UTC when unset or unknown."""
    name = config.get("timezone") or "UTC"
    try:
        return ZoneInfo(name), name
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC"), "UTC"


def wind_unit(config):
    return "mph" if str(config.get("wind_unit", "")).lower() == "mph" else "km/h"


def get(url, params):
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"User-Agent": "hermes-weather-helper/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def km_between(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def pick_result(results, home):
    """The geocoder ranks by size; prefer a match near home, else take its first."""
    if home:
        near = [r for r in results if km_between(home[1], home[2], r["latitude"], r["longitude"]) <= NEARBY_KM]
        if near:
            return near[0]
    return results[0]


def resolve_place(name, lat, lon, config, geocode=None):
    """(label, lat, lon) for the request. `geocode(name)` returns Open-Meteo results (tests pass a fake)."""
    if lat is not None and lon is not None:
        return f"{lat:.2f}, {lon:.2f}", lat, lon
    if (lat is None) != (lon is None):
        raise UsageError("Give both --lat and --lon, or a place name.")
    home = home_place(config)
    if not name or (home and name.strip().lower() == home[0].lower()):
        if not home:
            raise UsageError(f"No place given and no home place set in {CREW_JSON}. "
                             "Give a place name or --lat/--lon.")
        return home
    if geocode is None:
        def geocode(q):
            return get(GEOCODE_URL, {"name": q, "count": 5, "language": "en", "format": "json"}).get("results") or []
    results = geocode(name)
    if not results:
        raise UsageError(f"Could not find a place called {name!r}. Try a nearby town or use --lat/--lon.")
    best = pick_result(results, home)
    label = ", ".join(p for p in (best.get("name"), best.get("admin1"), best.get("country")) if p)
    return label, best["latitude"], best["longitude"]


def fetch(lat, lon, days, tzname, unit):
    return get(FORECAST_URL, {
        "latitude": lat, "longitude": lon, "timezone": tzname,
        "temperature_unit": "celsius", "wind_speed_unit": "mph" if unit == "mph" else "kmh",
        "precipitation_unit": "mm", "past_hours": 12, "forecast_days": days,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,wind_gusts_10m",
        "hourly": "temperature_2m,apparent_temperature,precipitation_probability,precipitation,weather_code,wind_speed_10m,wind_gusts_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,"
                 "wind_speed_10m_max,wind_gusts_10m_max,sunrise,sunset",
    })


def cond(code):
    return WMO.get(int(code), f"code {code}") if code is not None else "?"


def n(value, digits=0, unit=""):
    return "?" if value is None else f"{value:.{digits}f}{unit}"


def hourly_rows(data):
    h = data["hourly"]
    return [{k: (h[k][i] if k != "time" else datetime.fromisoformat(t)) for k in h} for i, t in enumerate(h["time"])]


def hour_line(r, unit):
    return (f"{r['time']:%H:%M}  {n(r['temperature_2m'])}C (feels {n(r['apparent_temperature'])})  "
            f"rain {n(r['precipitation_probability'], 0, '%')} {n(r['precipitation'], 1, 'mm')}  "
            f"wind {n(r['wind_speed_10m'])} gust {n(r['wind_gusts_10m'])} {unit}  {cond(r['weather_code'])}")


def format_now(data, label, lat, lon, now, tzname, unit):
    """`now` is a naive local datetime in the forecast's timezone."""
    rows, cur = hourly_rows(data), data["current"]
    lines = [f"{label} ({lat:.2f}, {lon:.2f}), {now:%a %d %b %H:%M} {tzname}",
             f"Now: {n(cur['temperature_2m'])}C (feels {n(cur['apparent_temperature'])}), {cond(cur['weather_code'])}, "
             f"wind {n(cur['wind_speed_10m'])} {unit} gusting {n(cur['wind_gusts_10m'])}, "
             f"humidity {n(cur['relative_humidity_2m'], 0, '%')}"]
    past = [r for r in rows if now - timedelta(hours=12) < r["time"] <= now]
    total = sum(r["precipitation"] or 0 for r in past)
    hint = "ground probably wet" if total >= 0.5 else "ground maybe damp" if total >= 0.1 else "dry"
    lines.append(f"Rain in the last 12h: {total:.1f} mm ({hint}; a guess)")
    lines.append("Next 6 hours:")
    lines += ["  " + hour_line(r, unit) for r in [r for r in rows if r["time"] > now][:6]]
    lines.append(SOURCE)
    return lines


def parse_hours(spec):
    if not spec:
        return 6, 22
    s, _, e = spec.partition("-")
    try:
        start, end = int(s), int(e or s)
    except ValueError:
        start, end = -1, -1
    if not (0 <= start <= 23 and 0 <= end <= 23 and start <= end):
        raise UsageError("--hours must look like 7-10 (whole hours, 0-23).")
    return start, end


def format_day(data, label, lat, lon, day, hours, unit):
    start, end = hours
    d = data["daily"]
    i = d["time"].index(day)
    lines = [f"{label} ({lat:.2f}, {lon:.2f}), {datetime.fromisoformat(day):%A %d %b}",
             f"Day: {n(d['temperature_2m_min'][i])}-{n(d['temperature_2m_max'][i])}C, {cond(d['weather_code'][i])}, "
             f"rain {n(d['precipitation_probability_max'][i], 0, '%')} chance / {n(d['precipitation_sum'][i], 1, 'mm')}, "
             f"wind up to {n(d['wind_speed_10m_max'][i])} {unit} (gusts {n(d['wind_gusts_10m_max'][i])}), "
             f"sunrise {d['sunrise'][i][11:]} sunset {d['sunset'][i][11:]}"]
    lines += ["  " + hour_line(r, unit) for r in hourly_rows(data)
              if f"{r['time']:%Y-%m-%d}" == day and start <= r["time"].hour <= end]
    lines.append(SOURCE)
    return lines


def format_week(data, label, lat, lon, days, unit):
    d = data["daily"]
    lines = [f"{label} ({lat:.2f}, {lon:.2f}), next {days} days"]
    for i, t in enumerate(d["time"][:days]):
        lines.append(f"  {datetime.fromisoformat(t):%a %d %b}  {n(d['temperature_2m_min'][i])}-{n(d['temperature_2m_max'][i])}C  "
                     f"rain {n(d['precipitation_probability_max'][i], 0, '%')} {n(d['precipitation_sum'][i], 1, 'mm')}  "
                     f"wind {n(d['wind_speed_10m_max'][i])} gust {n(d['wind_gusts_10m_max'][i])} {unit}  "
                     f"{cond(d['weather_code'][i])}")
    lines.append(SOURCE.rstrip(")") + "; beyond ~4 days it is a rough guide)")
    return lines


def run(a, config):
    tz, tzname = timezone_of(config)
    unit = wind_unit(config)
    label, lat, lon = resolve_place(a.place, a.lat, a.lon, config)
    now = datetime.now(tz).replace(tzinfo=None)
    if a.cmd == "now":
        return format_now(fetch(lat, lon, 2, tzname, unit), label, lat, lon, now, tzname, unit)
    if a.cmd == "day":
        day = a.date or now.strftime("%Y-%m-%d")
        try:
            ahead = (datetime.fromisoformat(day).date() - now.date()).days
        except ValueError:
            raise UsageError("--date must look like 2026-10-06.") from None
        if ahead < 0 or ahead > 15:
            raise UsageError("Date must be today or up to 15 days ahead.")
        hours = parse_hours(a.hours)
        return format_day(fetch(lat, lon, min(16, max(2, ahead + 2)), tzname, unit), label, lat, lon, day, hours, unit)
    days = max(1, min(16, a.days))
    return format_week(fetch(lat, lon, days, tzname, unit), label, lat, lon, days, unit)


def parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("now", "day", "week"):
        s = sub.add_parser(name)
        s.add_argument("place", nargs="?")
        s.add_argument("--lat", type=float)
        s.add_argument("--lon", type=float)
        if name == "day":
            s.add_argument("--date")
            s.add_argument("--hours")
        if name == "week":
            s.add_argument("--days", type=int, default=7)
    return p


def main(argv=None):
    a = parser().parse_args(argv)
    try:
        print("\n".join(run(a, load_config())))
    except UsageError as e:
        sys.exit(str(e))
    except (OSError, ValueError, KeyError) as e:
        sys.exit(f"Weather lookup failed ({type(e).__name__}: {e}). Try again in a minute.")


if __name__ == "__main__":
    main()
