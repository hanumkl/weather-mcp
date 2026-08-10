# Weather MCP Server + Agent Bricks Agent

Day 3 homework — a FastMCP server exposing weather tools, deployed as its own
Databricks App and driven by an Agent Bricks agent.

## Submission

| | |
|---|---|
| **Repo** | https://github.com/hanumkl/weather-mcp |
| **Databricks App** | `https://mcp-weather-7474644226225525.aws.databricksapps.com` |
| **MCP endpoint** | `https://mcp-weather-7474644226225525.aws.databricksapps.com/mcp` |
| **Agent** | Playground + Llama 4 Maverick, system prompt below |
| **Demo** | 3 screenshots in [`screenshots/`](screenshots/) |
| **Tools** | 7, against a required minimum of 3 |
| **Tests** | 47 checks against the live API, all passing |

The app URL is workspace-authenticated, so the screenshots are the shareable
evidence of it working.

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

**Name the app with an `mcp-` prefix.** Databricks' tool picker lists only apps
whose names start with `mcp-`; an app called `weather` deploys and serves fine
but is invisible to every agent in the workspace. This one is `mcp-weather`.

Deployed to: `https://mcp-weather-7474644226225525.aws.databricksapps.com`
The MCP endpoint is that URL plus `/mcp`.

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

Opening `/mcp` in a browser is also a useful smoke test: a healthy server
answers `{"error": {"message": "Not Acceptable: Client must accept
text/event-stream"}}`, which is the server speaking MCP correctly to a client
that cannot.

### 3. Wire it to an agent

**AI/ML → Playground**, pick a model with the tool-calling wrench icon
(`Llama 4 Maverick` was used here), then **Tools → Add tools → MCP Servers →
Custom MCP Server → `mcp-weather`**. Paste the system prompt below into
**Add system prompt**.

Two things that cost time here, both worth knowing:

- **The model must support tool calling.** `Meta Llama 3.1 8B Instruct` has no
  wrench icon, silently ignores the tools, and answers from memory — inventing
  both the numbers and a plausible-sounding source. The system prompt cannot
  prevent this; only picking a tool-capable model can.
- **Ask one question per chat.** Several turns in, Llama starts *printing*
  `[predict_umbrella_needed(location=Helsinki, date=2026-08-11)]` as text
  instead of emitting a real call. Resetting the chat fixes it.

The same server also registers under **Agents → + MCP → Connect an existing MCP
server** as a Unity Catalog MCP service. The connection is created successfully,
but tool discovery through the AI Gateway returned an empty error on Free
Edition; the Playground route above works and was used for the demo.

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
- If the error is about the date, retry THE SAME tool with a corrected date.
  The error states today's date; use it. Never substitute a different tool —
  answering an umbrella question with get_forecast loses the threshold logic
  that predict_umbrella_needed exists to apply.
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

Screenshots of the deployed agent are in [`screenshots/`](screenshots/), all
against the live `mcp-weather` app via Playground + Llama 4 Maverick.

**1. Current conditions** — [`01-current-conditions.png`](screenshots/01-current-conditions.png)
> What's the weather like in Tampere right now?

`get_current_weather({"location": "Tampere"})` → resolves to *Tampere,
Pirkanmaa, Finland*, 15.9 °C, 86 % humidity, 20.5 km/h wind, `"source":
"Open-Meteo"`. The answer restates the tool's numbers exactly.

**2. Derived prediction + error handling** — [`02-umbrella-prediction.png`](screenshots/02-umbrella-prediction.png)
> Do I need an umbrella in Helsinki tomorrow?

`predict_umbrella_needed` was called with the wrong year (`2024-08-11`), and
the server answered `{"error": "2024-08-11 is in the past; this service only
forecasts forward"}` — a clean, readable error rather than a traceback. The
agent then recovered on its own with `get_forecast({"location": "Helsinki",
"days": 1})` and reported the real numbers. Unplanned, but it demonstrates the
error contract better than a successful call would have.

**3. Multi-city comparison** — [`03-compare-locations.png`](screenshots/03-compare-locations.png)
> Compare the weather in Barcelona, Helsinki and Reykjavik

One `compare_locations` call returns all three ranked with scores and verdicts
— Barcelona 100, Reykjavik 100, Helsinki 85 (*slight rain*) — plus `"best"`
and an empty `"unresolved"`. The agent relays the ranking and the reason
Helsinki scores lower.

Note that the derived tools are doing the judgement, not the model: the scores,
the thresholds and the "in the past" rejection all come from the server.

---

## Tests

```bash
pip install requests "fastmcp>=3.2.0"
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
