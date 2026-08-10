"""
Tests the weather MCP server against the live Open-Meteo API.

No key needed, so unlike the mealplan agent this can be verified end to end
before it is ever deployed.
"""
import sys
from datetime import date, timedelta

import os
MCP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_server")
sys.path.insert(0, MCP)

import weather_broker as broker  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"  <- {detail}"))
    if not cond:
        failures.append(name)


print("=== geocoding ===")
p = broker.resolve_location("Helsinki")
check("resolves Helsinki", "Helsinki" in p["resolved_name"], p)
check("country code returned", p["country_code"] == "FI", p)
check("coordinates plausible", 59 < p["latitude"] < 61, p["latitude"])

p2 = broker.resolve_location("Chicago")
check("resolves a US city", p2["country_code"] == "US", p2)

try:
    broker.resolve_location("Xyzzyplughblah")
    check("unknown place raises", False, "no error")
except broker.WeatherError as e:
    check("unknown place raises a helpful error", "could not find" in str(e), str(e))

try:
    broker.resolve_location("")
    check("empty location raises", False)
except broker.WeatherError:
    check("empty location raises", True)

print("\n=== current conditions ===")
cur = broker.get_current("Tampere")
check("returns a temperature", isinstance(cur["temperature_c"], (int, float)), cur)
check("conditions are words, not a code",
      isinstance(cur["conditions"], str) and not cur["conditions"].isdigit(),
      cur["conditions"])
check("resolved name echoed back", "Tampere" in cur["location"], cur["location"])
check("humidity in range", 0 <= (cur["humidity_pct"] or 0) <= 100, cur["humidity_pct"])
print(f"    → {cur['location']}: {cur['temperature_c']}°C, {cur['conditions']}")

print("\n=== forecast ===")
fc = broker.get_forecast("Helsinki", days=5)
check("five days returned", len(fc["forecast"]) == 5, len(fc["forecast"]))
check("days are consecutive",
      [d["date"] for d in fc["forecast"]] ==
      [(date.today() + timedelta(days=i)).isoformat() for i in range(5)],
      [d["date"] for d in fc["forecast"]])
check("high >= low each day",
      all(d["high_c"] >= d["low_c"] for d in fc["forecast"]),
      [(d["high_c"], d["low_c"]) for d in fc["forecast"]])
check("days clamped to 16", len(broker.get_forecast("Oslo", days=99)["forecast"]) <= 16)
check("days clamped at 1 minimum", len(broker.get_forecast("Oslo", days=0)["forecast"]) >= 1)

print("\n=== umbrella prediction (derived) ===")
u = broker.predict_umbrella("Helsinki")
check("returns a boolean verdict", isinstance(u["umbrella_needed"], bool), u)
check("explains with real numbers", "%" in u["reasoning"], u["reasoning"])
check("thresholds disclosed", u["thresholds_used"]["chance_pct"] == 40, u)
check("advice is a sentence", len(u["advice"]) > 10, u["advice"])
print(f"    → {u['location']}: {u['advice']}")
print(f"      {u['reasoning']}")

try:
    broker.predict_umbrella("Helsinki", "2020-01-01")
    check("past date rejected", False)
except broker.WeatherError as e:
    check("past date rejected", "past" in str(e), str(e))
try:
    broker.predict_umbrella("Helsinki", "not-a-date")
    check("bad date format rejected", False)
except broker.WeatherError as e:
    check("bad date format rejected", "YYYY-MM-DD" in str(e), str(e))
try:
    broker.predict_umbrella("Helsinki",
                            (date.today() + timedelta(days=40)).isoformat())
    check("beyond horizon rejected", False)
except broker.WeatherError as e:
    check("beyond horizon rejected", "16 days" in str(e), str(e))

tomorrow = (date.today() + timedelta(days=1)).isoformat()
check("tomorrow works", broker.predict_umbrella("Helsinki", tomorrow)["date"] == tomorrow)

print("\n=== travel recommendation (derived) ===")
t = broker.travel_recommendation("Helsinki")
check("score in range", 0 <= t["travel_score"] <= 100, t["travel_score"])
check("verdict present", len(t["verdict"]) > 5, t)
check("deductions explained", isinstance(t["deductions"], list) and t["deductions"], t)
check("packing hint present", isinstance(t["packing_hint"], str), t)
print(f"    → {t['location']}: {t['travel_score']}/100, {t['verdict']}")
print(f"      because: {', '.join(t['deductions'])}")

print("\n=== compare locations ===")
c = broker.compare_locations(["Helsinki", "Barcelona", "Reykjavik"])
check("all three ranked", len(c["ranked"]) == 3, c["ranked"])
check("sorted descending",
      [r["score"] for r in c["ranked"]] == sorted([r["score"] for r in c["ranked"]],
                                                  reverse=True),
      [r["score"] for r in c["ranked"]])
check("best matches top of list", c["best"] == c["ranked"][0]["location"], c)
print(f"    → best: {c['best']} ({c['ranked'][0]['score']}/100)")

mixed = broker.compare_locations(["Helsinki", "Zzzznotaplace"])
check("one bad city doesn't sink the comparison",
      len(mixed["ranked"]) == 1 and len(mixed["unresolved"]) == 1, mixed)

try:
    broker.compare_locations([])
    check("empty list rejected", False)
except broker.WeatherError:
    check("empty list rejected", True)
try:
    broker.compare_locations(["a"] * 7)
    check("too many rejected", False)
except broker.WeatherError:
    check("too many rejected", True)

print("\n=== severe alerts ===")
fi = broker.severe_alerts("Helsinki")
check("non-US says unsupported rather than empty", fi["supported"] is False, fi)
check("explains why, without implying safety",
      "not the same as there being no severe weather" in fi["note"], fi["note"])
us = broker.severe_alerts("Miami")
check("US is supported", us["supported"] is True, us)
check("alert count is an int", isinstance(us["alert_count"], int), us)
print(f"    → Miami: {us['alert_count']} active alerts")

print("\n=== MCP registration ===")
import asyncio  # noqa: E402
import weather_mcp_server as server  # noqa: E402

tools = asyncio.run(server.mcp.list_tools())
names = {t.name for t in tools}
expected = {"get_current_weather", "get_forecast", "predict_umbrella_needed",
            "get_travel_recommendation", "compare_locations",
            "get_severe_alerts", "health_check"}
check("all tools registered", names == expected, names ^ expected)
check("meets the 3-tool minimum", len(names) >= 3, len(names))
# fastmcp 3.x sets `description` to the docstring's summary line only, so assert
# against the source docstring (Args/Returns and all) rather than the summary.
def _doc(name):
    return getattr(getattr(server, name), "__doc__", "") or ""


# ...and it exposes the input schema as `parameters`, where 1.x used `inputSchema`.
def _schema(t):
    return getattr(t, "inputSchema", None) or getattr(t, "parameters", None)


check("every tool documented",
      all(len(_doc(t.name)) > 60 for t in tools),
      [t.name for t in tools if len(_doc(t.name)) <= 60])
check("tools expose input schemas", all(_schema(t) is not None for t in tools))

print("\n=== errors are clean, never tracebacks ===")
bad = server.get_current_weather("Zzzznotaplace")
check("unknown place returns an error dict", "error" in bad, bad)
check("error is readable", "could not find" in bad["error"], bad)
check("no traceback leaked", "Traceback" not in str(bad))

print("\n=== health check ===")
h = server.health_check()
check("health ok", h.get("status") == "ok", h)

print("\n=== no hardcoded secrets ===")
src = (open(f"{MCP}/weather_broker.py").read()
       + open(f"{MCP}/weather_mcp_server.py").read())
check("no api keys", not any(k in src for k in ("api_key=", "dapi", "AIza", "sk-")))

print("\n" + "=" * 60)
if failures:
    print(f"FAILED: {len(failures)}")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("ALL PASSED")
