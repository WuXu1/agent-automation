---
name: weather-forecast
description: Weather for {{OWNER}} ({{HOME_PLACE}} by default) - current conditions, hourly forecast for a day, a week outlook, and whether recent rain has left the ground wet. Use before planning outdoor training or sport, trips, or anything weather-dependent.
version: 1.0.0
metadata:
  author: agent-automation starter kit
---

# Weather forecast (Open-Meteo, read-only)

A fixed script fetches the forecast from Open-Meteo (free, no account). It only reads
weather data. With no place given it uses {{OWNER}}'s home place from
`/data/.hermes/hermes.json`; times are {{TIMEZONE}}, temperatures in C, rain in mm, wind in
km/h (mph if hermes.json sets `"wind_unit": "mph"`).

## Commands

Run with the terminal tool, exactly as written:

```
python3 /data/tools/weather/forecast.py now
python3 /data/tools/weather/forecast.py day --hours 7-9
python3 /data/tools/weather/forecast.py day --date 2026-10-06 --hours 7-9
python3 /data/tools/weather/forecast.py week --days 7
python3 /data/tools/weather/forecast.py now "York"
python3 /data/tools/weather/forecast.py day --lat 51.50 --lon -0.12
```

- `now`: current conditions, rain in the last 12 hours, and the next 6 hours.
- `day`: one day (today by default, up to 15 days ahead), hourly lines for `--hours A-B`
  (default 6-22) plus a day summary with sunrise and sunset.
- `week`: one line per day, up to 16 days.
- A place name is looked up on the fly; a match near home wins over a bigger place far away.
  Check the place printed on the first line: if it is the wrong town (a namesake in another
  country), use `--lat` and `--lon` or ask {{OWNER}} where.
- "No place given and no home place set": the home place is missing from hermes.json. Give a
  place name, and tell {{OWNER}} the home place needs setting in the kit's setup.

## How to use it

- **Outdoor training and sport:** check the hours {{OWNER}} will be out. Rules of thumb, not
  facts: rain above ~0.5 mm in the last 12 hours means wet ground or a damp court, gusts
  above ~40 km/h (~25 mph) make ball sports and cycling hard, and below ~5C needs a longer
  warm-up and layers. Say what you based it on and suggest an indoor alternative when it
  looks poor.
- **Planning and trips:** use `week` for the outlook and `day` for the hours that matter.
- **Be honest about certainty:** forecasts beyond about 4 days are a rough guide, and these
  are model forecasts. For official warnings (storms, ice, heat) tell {{OWNER}} to check the
  national weather service, or search the web for its current warnings.
- Give {{OWNER}} the answer in a line or two (conditions, rain, wind, what it means for the
  plan), not the raw table.
- If the script prints "Weather lookup failed", say so and try once more later. Don't invent a
  forecast.
