# Weather MCP Server + Agent Bricks Agent

Day 3 homework — a FastMCP server exposing weather tools, deployed as its own
Databricks App and driven by an Agent Bricks agent.

```
weather-mcp/
  README.md                    this file
  mcp_server/                  the deployable Databricks App
    weather_mcp_server.py        thin @mcp.tool wrappers, docstrings only
    weather_broker.py            adapter: all HTTP calls and parsing
    requirements.txt
    app.yaml
  test_weather_tools.py        47 checks against the live API
```

The split follows Day 3's `alpaca_mcp_server.py` / `alpaca_broker.py`:
**no `requests` calls inside a `@mcp.tool` function.** Every HTTP call, all the
parsing and all the threshold logic live in the broker.

---

## Weather API and auth

**[Open-Meteo](https://open-meteo.com)** — no signup, no API key, no credit
card. ~10,000 calls/day for non-commercial use.

Two reasons over the alternatives:

- **Global.** The NWS API is US-only, and this is being demoed from Finland.
  Open-Meteo answers for Helsinki and Tampere as readily as Chicago.
- **Geocoding from the same provider.** A city name in any language resolves
  through Open-Meteo's free geocoding endpoint, so there's no hardcoded city
  lookup table to outgrow.

**Auth: none required.** There is therefore no API key to store — and nothing
is hardcoded, because there is nothing to hardcode. The only credential-shaped
value anywhere is the contact address the US NWS asks for in its `User-Agent`
header for the alerts endpoint, set as a plain env var in `app.yaml`.

Had a key been needed, it would go in a Databricks secret and be read with
`WorkspaceClient().secrets.get_secret()` — the pattern used in the companion
`mealplan-app/mcp_server/mealplan_store.py`.

---

## Tools

Seven, against a required minimum of three.

| Tool | Kind | What it does |
|---|---|---|
| `get_current_weather` | current | Temperature, feels-like, humidity, wind, conditions |
| `get_forecast` | forecast | 1–16 days: highs, lows, precipitation chance, wind, sunrise/sunset |
| `predict_umbrella_needed` | **derived** | Umbrella or not, with the thresholds stated |
| `get_travel_recommendation` | **derived** | 0–100 travel score with itemised deductions |
| `compare_locations` | stretch | Ranks up to 6 places for the same day |
| `get_severe_alerts` | stretch | Active NWS alerts — US only, and honest about it |
| `health_check` | ops | Is the upstream API reachable |

### The derived tools do real reasoning

**`predict_umbrella_needed`** applies thresholds and returns them, so the answer
can be argued with:

- umbrella if precipitation chance ≥ 40% **or** total ≥ 1.0 mm
- **but** if wind ≥ 40 km/h it recommends a raincoat instead — an umbrella that
  inverts is worse than none
- snow is handled separately, because "bring an umbrella" is wrong advice for
  snowfall

**`get_travel_recommendation`** starts at 100 and subtracts for named reasons —
heavy precipitation, thunderstorms, snow, fog, high wind, severe cold, extreme
heat — then returns the deductions individually. A user in Finland can see the
freezing penalty was applied and discount it. An opaque score can't be argued
with; an itemised one can.

Both are configurable from `app.yaml` (`UMBRELLA_CHANCE_PCT`, `UMBRELLA_MM`)
without a code change.

---

## Design decisions worth knowing

**Ambiguous place names raise rather than guess.** `resolve_location` returns a
`resolved_name` like *"Helsinki, Uusimaa, Finland"*, and the tool docstrings
tell the agent to repeat it back so the user can catch a wrong match. An
unknown name returns an error asking for a country or region rather than
silently picking the wrong Springfield.

**Non-US alerts return `supported: false`, not an empty list.** An empty alert
list reads as "no severe weather", which is a dangerous thing to imply when the
truth is "this service doesn't cover here". The note says so explicitly.

**Timezone handling.** Forecasts come back in the *location's* timezone, so a
city west of the caller can still be on yesterday's date. Asking for
`horizon + 1` days returned a window that didn't contain the requested date at
all — Reykjavik failed while Helsinki succeeded. Now fetches two days of slack
and, if the date is genuinely before the local window, says that rather than
returning a bare "no forecast".

**Every tool returns `{"error": "..."}` on failure**, never a traceback. The
agent can act on that — ask the user to clarify, or report the service is down.

---

## Setup

### 1. Deploy the MCP server

1. **Workspace → Create → Git folder**, pointing at this repo
2. **Compute → Apps → Create app → Custom**
3. Source: the Git folder, then browse to the **`mcp_server/`** subfolder (the
   one containing `app.yaml`)
4. Edit `NWS_USER_AGENT` in `app.yaml` to a real contact address
5. Deploy, and note the app URL

The MCP endpoint is at `https://<app-url>/mcp`.

### 2. Verify before wiring the agent

```bash
curl -N -H "Authorization: Bearer $DATABRICKS_TOKEN" \
     -H "Content-Type: application/json" \
     -H "Accept: application/json, text/event-stream" \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
     https://<app-url>/mcp
```

Should list seven tools with their schemas. Then call `health_check` — it
distinguishes "the upstream API is down" from "that place doesn't exist", which
otherwise look identical from a failed tool call.

### 3. Register with Agent Bricks

**Agent Bricks → Create agent → Tools → Add external MCP server**, pointing at
`https://<app-url>/mcp`. Paste the system prompt below.

---

## Agent system prompt

```
You are a weather assistant. You have tools that fetch real forecasts. Use
them for every factual claim — never answer from memory, and never invent a
temperature, a precipitation chance or an alert.

TOOL ORDER:
- "What's it like now?" → get_current_weather
- "What about tomorrow / this weekend?" → get_forecast
- "Do I need an umbrella?" → predict_umbrella_needed, not get_forecast. It
  applies thresholds you should not re-derive yourself.
- "Should I travel / go out on <date>?" → get_travel_recommendation
- "Where should we go?" → compare_locations
- "Any warnings or alerts?" → get_severe_alerts

GUARDRAILS:
- Always repeat back the resolved location name the tool returns, e.g.
  "Helsinki, Uusimaa, Finland". If it isn't what the user meant, they can only
  notice if you say it.
- If a tool returns {"error": ...}, tell the user what failed and what would
  fix it — usually adding a country or region to the place name. Do not retry
  silently and do not guess the weather.
- Only answer for locations the tools can resolve. If geocoding fails twice,
  ask the user to be more specific rather than trying a third variation.
- Forecasts only reach 16 days ahead. Beyond that, say so.
- get_severe_alerts covers the United States only. For anywhere else it
  returns supported=false — report that as "alerts aren't available for this
  location", never as "there are no alerts".
- When you relay a derived answer, include the reasoning the tool returned.
  "40% chance and 2mm expected, so yes" is useful; a bare "yes" is not.
- Never present a travel score without at least one of its deductions.

STYLE:
Brief and practical. Lead with the answer, then the numbers behind it.
```

---

## Demonstrating it works

Three natural-language questions covering the three required capabilities:

**1. Current conditions**
> What's the weather like in Tampere right now?

Expect: `get_current_weather` → temperature, conditions, humidity, wind, with
the resolved location repeated back.

**2. Forecast**
> What's the forecast for Helsinki over the next five days?

Expect: `get_forecast` → five days of highs, lows and precipitation chances.

**3. Derived prediction**
> Do I need an umbrella in Helsinki tomorrow?

Expect: `predict_umbrella_needed` → a yes/no *plus* the reasoning: *"100%
chance of precipitation, 4.8 mm expected, max wind 29.9 km/h"*.

Worth also capturing:

> We want a weekend trip — compare Helsinki, Barcelona and Reykjavik.

> Are there any severe weather alerts for Miami?

That last one is a good demo of a guardrail: ask it about Helsinki instead and
the agent should say alerts aren't *available* rather than that there are none.

---

## Tests

```bash
pip install requests "mcp>=1.2.0,<2.0.0"
python test_weather_tools.py
```

47 checks against the **live** Open-Meteo API — no key needed, so the whole
pipeline is verifiable before deployment. Covers geocoding (including unknown
and empty names), current conditions, forecast bounds, both derived tools and
their thresholds, date validation (past, malformed, beyond horizon), the
compare ranking with a deliberately broken city in the list, the US-only alert
behaviour, MCP tool registration and docstrings, and that errors surface as
dicts rather than tracebacks.

The timezone bug above was found by these tests, not in production.
