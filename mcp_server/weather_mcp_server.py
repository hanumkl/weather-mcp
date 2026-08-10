"""
Weather MCP server (FastMCP, streamable HTTP).

Day 3 homework. Deployed as its own Databricks App and registered with Agent
Bricks as an external MCP server.

Every function here is a thin wrapper. All HTTP calls, parsing and the
threshold logic live in `weather_broker.py` - the same split as Day 3's
alpaca_mcp_server.py / alpaca_broker.py.

Seven tools:
    get_current_weather        current conditions
    get_forecast               multi-day forecast
    predict_umbrella_needed    derived judgement, stated thresholds
    get_travel_recommendation  derived judgement, scored with reasons
    compare_locations          rank several places for one day
    get_severe_alerts          NWS alerts, US-only and honest about it
    health_check               is the upstream API reachable

Data source: Open-Meteo. No API key, no signup, global coverage.
"""

from __future__ import annotations

import logging
import os

# FastMCP ships inside `mcp` 1.x (the Day 3 layout) and as a standalone
# `fastmcp` package from mcp 2.0. requirements.txt pins 1.x; accept either so a
# differently-resolved image still starts.
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover
    from fastmcp import FastMCP

import weather_broker as broker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("weather-mcp")

mcp = FastMCP("weather")


def _safe(fn, **kwargs) -> dict:
    """Return a clean error dict instead of a stack trace.

    The agent can act on {"error": "..."} - ask the user to clarify a place
    name, or say the service is down. A traceback just ends the conversation.
    """
    try:
        return fn(**kwargs)
    except broker.WeatherError as exc:
        return {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("%s failed", getattr(fn, "__name__", fn))
        return {"error": f"{type(exc).__name__}: {exc}"}


@mcp.tool()
def get_current_weather(location: str) -> dict:
    """Current conditions for a place, right now.

    Resolves the place name automatically, so "Helsinki", "Tampere",
    "Chicago, IL" and "Bandung" all work. If the name is ambiguous or unknown
    it returns an error asking for a country or region rather than guessing
    which Springfield you meant.

    Args:
        location: City name, optionally with region or country.

    Returns:
        dict: location (the resolved full name - always repeat this back so
              the user can catch a wrong match), observed_at, temperature_c,
              feels_like_c, humidity_pct, precipitation_mm, wind_speed_kmh,
              conditions as plain words, and units.
    """
    return _safe(broker.get_current, location=location)


@mcp.tool()
def get_forecast(location: str, days: int = 5) -> dict:
    """Daily forecast for the next N days.

    Args:
        location: City name, optionally with region or country.
        days: How many days ahead, 1-16. Defaults to 5.

    Returns:
        dict: location and a forecast list, each entry with date, high_c,
              low_c, precipitation_mm, precipitation_chance_pct, max_wind_kmh,
              conditions, sunrise and sunset.
    """
    return _safe(broker.get_forecast, location=location, days=days)


@mcp.tool()
def predict_umbrella_needed(location: str, date: str = None) -> dict:
    """Should they take an umbrella? A judgement call, not a raw forecast.

    Applies explicit thresholds and returns them so the answer can be argued
    with:
      - umbrella if precipitation chance >= 40% OR total >= 1.0 mm
      - but if wind >= 40 km/h it recommends a raincoat instead, because an
        umbrella that inverts is worse than none
      - snow is called out separately - "bring an umbrella" is wrong advice
        for snowfall

    Args:
        location: City name.
        date: 'YYYY-MM-DD'. Defaults to today. Must be within 16 days.

    Returns:
        dict: umbrella_needed (bool), advice, reasoning with the actual
              numbers, and thresholds_used. Relay the reasoning - "40% chance
              and 2mm expected" is more useful than a bare yes.
    """
    return _safe(broker.predict_umbrella, location=location, target_date=date)


@mcp.tool()
def get_travel_recommendation(location: str, date: str = None) -> dict:
    """Score a day for travel, 0-100, and explain the deductions.

    Starts at 100 and subtracts for named reasons: heavy precipitation,
    thunderstorms, snow, fog, high wind, severe cold, extreme heat. Above 80
    is good, 50-80 workable, below 50 suggests rescheduling.

    The deductions are returned individually so the user can disagree with the
    weighting - someone used to Finnish winters will discount the freezing
    penalty, and they should be able to see it was applied.

    Args:
        location: City name.
        date: 'YYYY-MM-DD'. Defaults to today. Must be within 16 days.

    Returns:
        dict: travel_score, verdict, deductions (the specific reasons),
              conditions, high_c, low_c, packing_hint.
    """
    return _safe(broker.travel_recommendation, location=location,
                 target_date=date)


@mcp.tool()
def compare_locations(locations: list[str], date: str = None) -> dict:
    """Rank several places for the same day, best weather first.

    Useful for "where should we go this weekend?". A place that can't be
    resolved is reported in `unresolved` rather than failing the whole
    comparison.

    Args:
        locations: 1-6 city names.
        date: 'YYYY-MM-DD'. Defaults to today.

    Returns:
        dict: ranked list with score and conditions per place, best, and
              unresolved.
    """
    return _safe(broker.compare_locations, locations=locations, target_date=date)


@mcp.tool()
def get_severe_alerts(location: str) -> dict:
    """Active severe weather alerts. United States only.

    Alerts come from the US National Weather Service, the only one of the two
    upstream services that publishes them. For a non-US location this returns
    supported=false with an explanation - an empty alert list would otherwise
    read as "no severe weather", which is a dangerous thing to imply.

    Args:
        location: City name.

    Returns:
        dict: supported, alert_count, alerts with event, severity, urgency,
              headline, instruction and expiry.
    """
    return _safe(broker.severe_alerts, location=location)


@mcp.tool()
def health_check() -> dict:
    """Confirm the upstream weather API is reachable.

    Distinguishes "the service is down" from "that place doesn't exist", which
    otherwise look identical from a failed tool call.
    """
    def _check():
        probe = broker.get_current("Helsinki")
        return {"status": "ok", "upstream": "Open-Meteo",
                "probe_location": probe["location"],
                "probe_temperature_c": probe["temperature_c"]}
    return _safe(_check)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    logger.info("weather MCP server on :%s (streamable-http)", port)
    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = port
    mcp.run(transport="streamable-http")
