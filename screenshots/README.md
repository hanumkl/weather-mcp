# Demo screenshots

Agent Bricks Playground driving the deployed `mcp-weather` MCP server
(Llama 4 Maverick + the system prompt from the root README).

Each screenshot shows the natural-language question, the tool call the agent
made, and the answer it derived from the tool's output.

| File | Question | Tool exercised |
|---|---|---|
| `01-current-conditions.png` | What's the weather like in Tampere right now? | `get_current_weather` |
| `02-umbrella-prediction.png` | Do I need an umbrella in Helsinki tomorrow? | `predict_umbrella_needed` |
| `03-compare-locations.png` | Where should we go this weekend — Barcelona, Helsinki, or Reykjavik? | `compare_locations` |

Capture the tool-call block *and* the final answer for each — the tool
invocation is the part being demonstrated, not just the prose reply.
