"""
Adapter for the weather MCP server.

Same role as Day 3's `alpaca_broker.py`: every HTTP call and all the parsing
lives here, so the `@mcp.tool` functions upstairs stay thin wrappers with
docstrings. Nothing in weather_mcp_server.py calls requests directly.

Data source: Open-Meteo (https://open-meteo.com)
  - No signup, no API key, no credit card. ~10,000 calls/day non-commercial.
  - Global coverage, which matters here: the NWS API is US-only and this is
    being demoed from Finland.
  - Geocoding comes from the same provider, so a city name in any language
    resolves without a hardcoded lookup table.

Severe alerts come from the US National Weather Service, which is the only one
of the two that publishes them - so that tool is explicitly US-only and says so
rather than returning an empty list that reads like "no alerts".
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from typing import Any

import requests

logger = logging.getLogger("weather-mcp.broker")

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
NWS_BASE = "https://api.weather.gov"
TIMEOUT = int(os.environ.get("WEATHER_TIMEOUT", "30"))

# NWS asks for a contact address so they can reach you if a client misbehaves.
NWS_USER_AGENT = os.environ.get(
    "NWS_USER_AGENT", "weather-mcp-bootcamp (student@example.com)")

# WMO weather interpretation codes. Open-Meteo returns a number; humans and
# LLMs both need the word.
WMO_CODES: dict[int, str] = {
    0: "clear sky",
    1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "depositing rime fog",
    51: "light drizzle", 53: "moderate drizzle", 55: "dense drizzle",
    56: "light freezing drizzle", 57: "dense freezing drizzle",
    61: "slight rain", 63: "moderate rain", 65: "heavy rain",
    66: "light freezing rain", 67: "heavy freezing rain",
    71: "slight snowfall", 73: "moderate snowfall", 75: "heavy snowfall",
    77: "snow grains",
    80: "slight rain showers", 81: "moderate rain showers",
    82: "violent rain showers",
    85: "slight snow showers", 86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail", 99: "thunderstorm with heavy hail",
}

WET_CODES = set(range(51, 68)) | set(range(80, 83)) | {95, 96, 99}
SNOW_CODES = set(range(71, 78)) | {85, 86}


class WeatherError(RuntimeError):
    """Raised for anything the caller should see as a clean message."""


def describe(code: Any) -> str:
    try:
        return WMO_CODES.get(int(code), f"unknown conditions (code {code})")
    except (TypeError, ValueError):
        return "unknown conditions"


def _get(url: str, params: dict, headers: dict | None = None) -> dict:
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise WeatherError(f"could not reach {url}: {exc}") from exc
    if resp.status_code == 404:
        raise WeatherError(f"{url} returned 404 - the location may be outside "
                           f"this service's coverage")
    if resp.status_code >= 400:
        raise WeatherError(f"{url} returned {resp.status_code}: {resp.text[:200]}")
    return resp.json()


# ---------------------------------------------------------------------------
# geocoding
# ---------------------------------------------------------------------------

def resolve_location(location: str) -> dict:
    """Turn a place name into coordinates.

    Uses Open-Meteo's geocoding rather than a hardcoded city table, so
    "Helsinki", "Tampere" and "Chicago" all work without code changes. Raises
    WeatherError with the original input when nothing matches, so the agent can
    ask the user to be more specific instead of silently picking the wrong
    Springfield.
    """
    if not location or not location.strip():
        raise WeatherError("location is required")

    data = _get(GEOCODE_URL, {"name": location.strip(), "count": 1,
                              "language": "en", "format": "json"})
    results = data.get("results") or []
    if not results:
        raise WeatherError(
            f"could not find a place called {location!r}. Try adding a country "
            f"or region, e.g. 'Springfield, Illinois'."
        )

    top = results[0]
    parts = [top.get("name"), top.get("admin1"), top.get("country")]
    return {
        "latitude": top["latitude"],
        "longitude": top["longitude"],
        "resolved_name": ", ".join(p for p in parts if p),
        "country_code": top.get("country_code"),
        "timezone": top.get("timezone"),
    }


# ---------------------------------------------------------------------------
# current + forecast
# ---------------------------------------------------------------------------

def get_current(location: str) -> dict:
    place = resolve_location(location)
    data = _get(FORECAST_URL, {
        "latitude": place["latitude"],
        "longitude": place["longitude"],
        "current": ("temperature_2m,relative_humidity_2m,apparent_temperature,"
                    "precipitation,weather_code,wind_speed_10m,wind_direction_10m"),
        "timezone": "auto",
    })
    cur = data.get("current") or {}
    units = data.get("current_units") or {}
    return {
        "location": place["resolved_name"],
        "observed_at": cur.get("time"),
        "temperature_c": cur.get("temperature_2m"),
        "feels_like_c": cur.get("apparent_temperature"),
        "humidity_pct": cur.get("relative_humidity_2m"),
        "precipitation_mm": cur.get("precipitation"),
        "wind_speed_kmh": cur.get("wind_speed_10m"),
        "wind_direction_deg": cur.get("wind_direction_10m"),
        "conditions": describe(cur.get("weather_code")),
        "weather_code": cur.get("weather_code"),
        "units": units,
        "source": "Open-Meteo",
    }


def get_forecast(location: str, days: int = 5) -> dict:
    days = max(1, min(int(days or 5), 16))     # Open-Meteo caps at 16
    place = resolve_location(location)
    data = _get(FORECAST_URL, {
        "latitude": place["latitude"],
        "longitude": place["longitude"],
        "daily": ("weather_code,temperature_2m_max,temperature_2m_min,"
                  "precipitation_sum,precipitation_probability_max,"
                  "wind_speed_10m_max,sunrise,sunset"),
        "forecast_days": days,
        "timezone": "auto",
    })
    d = data.get("daily") or {}
    out = []
    for i, day in enumerate(d.get("time", [])):
        out.append({
            "date": day,
            "high_c": _at(d, "temperature_2m_max", i),
            "low_c": _at(d, "temperature_2m_min", i),
            "precipitation_mm": _at(d, "precipitation_sum", i),
            "precipitation_chance_pct": _at(d, "precipitation_probability_max", i),
            "max_wind_kmh": _at(d, "wind_speed_10m_max", i),
            "conditions": describe(_at(d, "weather_code", i)),
            "weather_code": _at(d, "weather_code", i),
            "sunrise": _at(d, "sunrise", i),
            "sunset": _at(d, "sunset", i),
        })
    return {"location": place["resolved_name"], "days": len(out),
            "forecast": out, "source": "Open-Meteo"}


def _at(block: dict, key: str, index: int):
    values = block.get(key) or []
    return values[index] if index < len(values) else None


def _day_for(location: str, target: str | None) -> tuple[dict, dict]:
    """Return (place-bearing forecast, the one day asked for)."""
    want = (target or date.today().isoformat()).strip()
    try:
        wanted = datetime.strptime(want, "%Y-%m-%d").date()
    except ValueError:
        raise WeatherError(f"date must be YYYY-MM-DD, got {target!r}")

    horizon = (wanted - date.today()).days
    if horizon < 0:
        raise WeatherError(f"{want} is in the past; this service only forecasts "
                           f"forward")
    if horizon > 15:
        raise WeatherError(f"{want} is {horizon} days out; forecasts only go 16 "
                           f"days ahead")

    # Two days of slack, not one. Forecasts come back in the *location's*
    # timezone, so a city west of the caller can still be on yesterday's date -
    # asking for horizon+1 days then returned a window that didn't contain the
    # date at all. Reykjavik failed this way while Helsinki succeeded.
    fc = get_forecast(location, days=min(horizon + 2, 16))
    match = next((d for d in fc["forecast"] if d["date"] == want), None)
    if match is None:
        available = [d["date"] for d in fc["forecast"]]
        if available and want < available[0]:
            raise WeatherError(
                f"{want} is already past in {fc['location']} (local forecast "
                f"starts {available[0]}) - timezones differ from yours"
            )
        raise WeatherError(
            f"no forecast for {want} in {fc['location']}; available: "
            f"{available[0]}..{available[-1]}" if available
            else f"no forecast returned for {want}"
        )
    return fc, match


# ---------------------------------------------------------------------------
# derived judgement - the part that is not a passthrough
# ---------------------------------------------------------------------------

UMBRELLA_CHANCE = int(os.environ.get("UMBRELLA_CHANCE_PCT", "40"))
UMBRELLA_MM = float(os.environ.get("UMBRELLA_MM", "1.0"))


def predict_umbrella(location: str, target_date: str | None = None) -> dict:
    """Decide whether an umbrella is worth carrying.

    Thresholds, stated so the answer can be argued with:
      - precipitation chance >= 40%, OR
      - total precipitation >= 1.0 mm

    Wind above 40 km/h flips the advice to a raincoat: an umbrella that
    inverts is worse than no umbrella. Snow is called out separately, because
    "bring an umbrella" is the wrong advice for snowfall.
    """
    fc, day = _day_for(location, target_date)
    chance = day["precipitation_chance_pct"] or 0
    mm = day["precipitation_mm"] or 0.0
    wind = day["max_wind_kmh"] or 0.0
    code = day["weather_code"]

    wet = chance >= UMBRELLA_CHANCE or mm >= UMBRELLA_MM
    snowing = code in SNOW_CODES

    if snowing:
        verdict, advice = False, "Snow rather than rain - a hood beats an umbrella."
    elif wet and wind >= 40:
        verdict, advice = False, ("Wet but windy at %.0f km/h - an umbrella will "
                                  "invert. Wear a raincoat." % wind)
    elif wet:
        verdict, advice = True, "Bring an umbrella."
    else:
        verdict, advice = False, "You can leave the umbrella at home."

    return {
        "location": fc["location"],
        "date": day["date"],
        "umbrella_needed": verdict,
        "advice": advice,
        "reasoning": (f"{chance}% chance of precipitation, {mm} mm expected, "
                      f"max wind {wind} km/h, conditions: {day['conditions']}."),
        "thresholds_used": {"chance_pct": UMBRELLA_CHANCE,
                            "precipitation_mm": UMBRELLA_MM,
                            "wind_kmh_for_raincoat": 40},
        "source": "Open-Meteo",
    }


def travel_recommendation(location: str, target_date: str | None = None) -> dict:
    """Score a day for travel and say what drove the score.

    Starts at 100 and subtracts for specific, named reasons rather than
    returning an opaque number:
      heavy precipitation, freezing temperatures, high wind, thunderstorms,
      fog, and extreme heat.

    Below 50 the recommendation is to reconsider. The deductions are returned
    so a user can disagree with the weighting - someone used to Finnish winters
    will discount the freezing penalty.
    """
    fc, day = _day_for(location, target_date)
    score = 100
    reasons: list[str] = []

    chance = day["precipitation_chance_pct"] or 0
    mm = day["precipitation_mm"] or 0.0
    wind = day["max_wind_kmh"] or 0.0
    low = day["low_c"]
    high = day["high_c"]
    code = day["weather_code"]

    if mm >= 10:
        score -= 30; reasons.append(f"heavy precipitation ({mm} mm)")
    elif mm >= 3:
        score -= 15; reasons.append(f"moderate precipitation ({mm} mm)")
    elif chance >= 60:
        score -= 10; reasons.append(f"{chance}% chance of precipitation")

    if code in {95, 96, 99}:
        score -= 25; reasons.append("thunderstorms forecast")
    if code in SNOW_CODES:
        score -= 20; reasons.append("snowfall forecast")
    if code in {45, 48}:
        score -= 10; reasons.append("fog - expect delays")

    if wind >= 60:
        score -= 25; reasons.append(f"very high wind ({wind} km/h)")
    elif wind >= 40:
        score -= 10; reasons.append(f"windy ({wind} km/h)")

    if low is not None and low <= -10:
        score -= 15; reasons.append(f"severe cold (low {low}°C)")
    elif low is not None and low <= 0:
        score -= 5; reasons.append(f"freezing (low {low}°C)")
    if high is not None and high >= 35:
        score -= 15; reasons.append(f"extreme heat (high {high}°C)")

    score = max(0, min(100, score))
    if score >= 80:
        verdict = "good day to travel"
    elif score >= 50:
        verdict = "workable, but plan around the weather"
    else:
        verdict = "consider rescheduling"

    return {
        "location": fc["location"],
        "date": day["date"],
        "travel_score": score,
        "verdict": verdict,
        "deductions": reasons or ["nothing notable - clear conditions"],
        "conditions": day["conditions"],
        "high_c": high, "low_c": low,
        "packing_hint": _packing(high, low, code, chance),
        "source": "Open-Meteo",
    }


def _packing(high, low, code, chance) -> str:
    items = []
    if low is not None and low <= 0:
        items.append("proper winter coat")
    elif low is not None and low <= 10:
        items.append("warm jacket")
    if high is not None and high >= 28:
        items.append("light clothing and water")
    if code in WET_CODES or (chance or 0) >= 40:
        items.append("rain protection")
    if code in SNOW_CODES:
        items.append("boots with grip")
    return ", ".join(items) if items else "nothing special"


def compare_locations(locations: list[str], target_date: str | None = None) -> dict:
    """Rank several places for the same day by travel score."""
    if not locations:
        raise WeatherError("give at least one location")
    if len(locations) > 6:
        raise WeatherError("at most 6 locations at a time")

    rows, failed = [], []
    for loc in locations:
        try:
            rec = travel_recommendation(loc, target_date)
            rows.append({"location": rec["location"], "score": rec["travel_score"],
                         "conditions": rec["conditions"], "high_c": rec["high_c"],
                         "low_c": rec["low_c"], "verdict": rec["verdict"]})
        except WeatherError as exc:
            # One bad city shouldn't lose the whole comparison.
            failed.append({"location": loc, "error": str(exc)})

    rows.sort(key=lambda r: r["score"], reverse=True)
    return {"date": target_date or date.today().isoformat(),
            "ranked": rows, "unresolved": failed,
            "best": rows[0]["location"] if rows else None,
            "source": "Open-Meteo"}


# ---------------------------------------------------------------------------
# severe alerts (US only - be explicit about it)
# ---------------------------------------------------------------------------

def severe_alerts(location: str) -> dict:
    """Active NWS alerts. US-only, and says so for anywhere else."""
    place = resolve_location(location)
    if (place.get("country_code") or "").upper() != "US":
        return {
            "location": place["resolved_name"],
            "supported": False,
            "alerts": [],
            "note": ("Severe weather alerts come from the US National Weather "
                     "Service, which only covers the United States. There are "
                     "no alerts available for this location - which is not the "
                     "same as there being no severe weather."),
        }

    data = _get(f"{NWS_BASE}/alerts/active",
                {"point": f"{place['latitude']},{place['longitude']}"},
                headers={"User-Agent": NWS_USER_AGENT,
                         "Accept": "application/geo+json"})
    alerts = []
    for feature in data.get("features", []):
        p = feature.get("properties", {})
        alerts.append({
            "event": p.get("event"), "severity": p.get("severity"),
            "urgency": p.get("urgency"), "headline": p.get("headline"),
            "instruction": p.get("instruction"), "expires": p.get("expires"),
        })
    return {"location": place["resolved_name"], "supported": True,
            "alert_count": len(alerts), "alerts": alerts,
            "source": "US National Weather Service"}
