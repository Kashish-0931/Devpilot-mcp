# DevPilot

An AI ops assistant for infrastructure, with two flows:

- **Ask flow** (on demand): you ask Claude something like *"why is my API down?"*. Claude calls DevPilot's tools over **MCP** (Streamable HTTP, token-authenticated). DevPilot checks EC2, Docker, and CloudWatch logs, returns the data, and Claude explains the root cause and the fix.
- **Alert flow** (automatic, no one asks): the API goes down → a CloudWatch alarm fires → SNS passes the event to a Lambda → the Lambda collects logs, asks an LLM (Claude API) for a diagnosis, and sends a Telegram/email message, e.g. *"API down, the container crashed, missing env var."*

Full architecture, the 8-stage build order, and design rationale live in [`spec.md`](./spec.md).

## Status: Stage 1 complete

Stage 1 (of 8) is built and verified: the **journal** (an append-only, DynamoDB-backed event log DevPilot and humans both read and write) plus a minimal **MCP server** exposing two tools:

- `get_recent_journal_entries(limit)` — read the journal, newest first.
- `log_journal_entry(message, level, metadata)` — write a human-authored entry.

Stage 2 (Docker + EC2) onward is not started yet.

## Prerequisites

- **Python 3.12+**
- **Docker Desktop** (running) — for DynamoDB Local during manual testing
- **Node.js** (for `npx`, to run MCP Inspector) — only needed if you want to poke at the server manually
- A GitHub-cloned copy of this repo

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
```

`.env` holds your local config (dummy DynamoDB Local credentials, a dev MCP token) — see [`.env.example`](./.env.example). It's gitignored; edit `.env`, never commit it. Real environment variables (`$env:...`) always take precedence over `.env` if both are set.

## Running the tests

```powershell
pytest
```

Fully `moto`-mocked — no Docker, no real AWS, no network calls. Should show all tests passing.

## Running it locally (manual smoke test)

Startup order matters — DynamoDB Local first, then the table, then the server, then (optionally) a client:

```powershell
# 1. Start DynamoDB Local (in-memory -- data is lost when the container restarts)
docker run -d --name dynamodb -p 8000:8000 amazon/dynamodb-local -jar DynamoDBLocal.jar -inMemory -sharedDb

# 2. Create the journal table (re-run this after every container restart)
python scripts/bootstrap_local_table.py

# 3. Start the server (reads config from .env)
python -m devpilot.server
# or: .\scripts\run_local.ps1
```

The server listens on `http://127.0.0.1:8080/mcp` (port from `DEVPILOT_MCP_PORT`, default `8080`).

### Connect with MCP Inspector (visual, see the raw protocol)

In a **separate, plain PowerShell window** (not a VS Code integrated terminal — see Troubleshooting):

```powershell
npx @modelcontextprotocol/inspector
```

In the UI that opens: Transport Type = `Streamable HTTP`, URL = `http://127.0.0.1:8080/mcp`, add header `Authorization: Bearer <your DEVPILOT_MCP_TOKEN>`, Connect. Both tools should appear and be callable.

### Connect with Claude Code

```powershell
claude mcp add --transport http devpilot http://127.0.0.1:8080/mcp --header "Authorization: Bearer <your DEVPILOT_MCP_TOKEN>"
claude mcp get devpilot   # should show: Status: Connected
```

Then open a **new** `claude` session in this folder and just ask it to log or read journal entries — it'll use the tools automatically. (A session that was already open before you ran `claude mcp add` won't see the new server; its tool list was fixed at startup.)

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Can't connect to `localhost:8080` | Use `127.0.0.1` instead. `localhost` can resolve to IPv6 (`::1`) on Windows; the server only binds IPv4 (`0.0.0.0`). |
| Config seems to reset after closing the terminal | `$env:` variables are per-session. Put persistent values in `.env` instead — see Setup above. |
| MCP Inspector misbehaves / disconnects unexpectedly | Run it in a plain PowerShell window, not a VS Code integrated terminal — VS Code's shell auto-activation can interrupt it. Also make sure you're using the URL from the *current* Inspector run, not a stale one from a previous restart. |
| Server error about a missing table | DynamoDB Local (`-inMemory`) loses all data, including the table, on container restart. Re-run `python scripts/bootstrap_local_table.py`. |
| `401` from the server | Token mismatch — the `Authorization: Bearer ...` header doesn't match `DEVPILOT_MCP_TOKEN` in `.env` (or whatever's currently set). Missing token also gives `401`. |
| `only one usage of each socket address ... 8080` | Something's already listening on port 8080 — likely a previous `python -m devpilot.server` still running. Find it (`netstat -ano \| findstr :8080`) and stop it, or set a different `DEVPILOT_MCP_PORT`. |
| Server won't start, prints `DEVPILOT_MCP_TOKEN must be set` | Expected — the server fails fast rather than starting insecurely. Set it in `.env` or `$env:DEVPILOT_MCP_TOKEN`. |
