# Handoff — where this stands

Context for picking this up in a fresh session from inside `weather-mcp/`.

## What this is

Day 3 homework for the Databricks "Rise of the AI Data Engineer" bootcamp:
**build your own MCP server exposing weather tools, and wire an Agent Bricks
agent to it.** Both deploy as Databricks Apps, mirroring Day 3's
`mcp_server/` + `dashboard/` split.

Sibling project: `../mealplan-app/` — the capstone (already submitted and
passed). It has its own MCP server at `mealplan-app/mcp_server/` built the same
way; worth looking at for the secret-handling pattern, since this project needs
no API key and therefore doesn't demonstrate it.

## Status

**Code is complete and tested. Nothing is deployed yet.**

| | |
|---|---|
| `mcp_server/weather_broker.py` | Adapter — all HTTP, parsing, threshold logic |
| `mcp_server/weather_mcp_server.py` | 7 thin `@mcp.tool` wrappers |
| `mcp_server/app.yaml`, `requirements.txt` | Databricks App config |
| `README.md` | Submission doc: tools, setup, Agent Bricks system prompt, demo questions |
| `test_weather_tools.py` | 47 checks against the live API — **all passing** |

Run the tests any time with:

```bash
pip install requests "mcp>=1.2.0,<2.0.0"
python test_weather_tools.py
```

No API key needed, so they work from anywhere.

## Decisions already made — don't re-litigate

**Open-Meteo, not NWS.** No key, no signup, and global. The NWS API is US-only
and this is demoed from Finland, so Helsinki and Tampere have to work. Open-Meteo's
geocoding endpoint resolves any place name, replacing a hardcoded city table.

**Broker/server split is mandatory**, per the assignment: no `requests` calls
inside a `@mcp.tool` function. Keep it that way.

**`mcp` is pinned to `<2.0.0`.** FastMCP lives inside `mcp` in 1.x (the Day 3
layout); 2.0 split it into a standalone `fastmcp` package. The import has a
fallback for both, but the pin is what's tested.

**Non-US alerts return `supported: false`, not an empty list.** An empty list
reads as "no severe weather" when the truth is "this service doesn't cover
here". Deliberate — don't "simplify" it.

**Timezone slack of two days in `_day_for`.** Forecasts return in the
*location's* timezone, so a city west of the caller can still be on yesterday's
date. With one day of slack, Reykjavik failed while Helsinki passed. Found by
the tests, not in production.

## What's left

1. **Deploy `mcp_server/`** as a Databricks App — Compute → Apps → Create app →
   Custom, source = this Git folder, browse to the `mcp_server/` subfolder.
   Edit `NWS_USER_AGENT` in `app.yaml` to a real contact address first.
2. **Verify** with the `curl tools/list` snippet in README.md, then call
   `health_check`.
3. **Register with Agent Bricks** at `https://<app-url>/mcp`, pasting the
   system prompt from README.md.
4. **Screenshot 3+ natural-language questions** with the agent's tool calls and
   answers — the assignment requires this. Suggested questions are in README.md
   under "Demonstrating it works".
5. *(Optional stretch)* A small dashboard app showing recent queries. Not
   required to pass.

## Constraints worth remembering

- **Databricks Free Edition.** Apps and Lakebase work. **Agent Bricks
  availability is unverified** — check before relying on it. If it isn't
  offered, the MCP server still deploys and can be demoed via `curl` or an MCP
  client; say so honestly in the submission rather than leaving a blank
  section.
- Free Edition has no Claude models. `databricks-llama-4-maverick` is the only
  multimodal endpoint.
- **Secrets:** this project needs none. If that changes, use a Databricks
  secret scope named for the project (not the bootcamp's shared `database`
  scope — two projects using the same secret name silently overwrite each
  other, which cost an hour on the capstone).

## Submission checklist

- [ ] MCP server deployed, URL noted
- [ ] Agent Bricks agent registered against it
- [ ] 3+ screenshots of NL questions → tool calls → answers
- [ ] README.md (already written — update the app URL once deployed)
- [ ] Repo link
