# DevPilot

An AI ops assistant for infrastructure, with two flows:

- **Ask flow** (on demand): you ask Claude something like *"why is my API down?"*. Claude calls DevPilot's tools over **MCP** (Streamable HTTP, token-authenticated). DevPilot checks EC2, Docker, and CloudWatch logs, returns the data, and Claude explains the root cause and the fix.
- **Alert flow** (automatic, no one asks): the API goes down → a CloudWatch alarm fires → SNS passes the event to a Lambda → the Lambda collects logs, asks an LLM (Claude API) for a diagnosis, and sends a Telegram/email message, e.g. *"API down, the container crashed, missing env var."*

Full architecture, the 8-stage build order, and design rationale live in [`spec.md`](./spec.md).

## Status: Stage 2 complete

- **Stage 1**: the **journal** (an append-only, DynamoDB-backed event log DevPilot and humans both read and write), plus `get_recent_journal_entries`/`log_journal_entry`.
- **Stage 2**: DevPilot's first "eyes" — four read-only Docker/HTTP inspection tools, tested locally against a deliberately-fragile `demo-app` via `docker compose`, no AWS deployment involved:
  - `check_container(name)` — status, exit code, OOM/health/restart info.
  - `tail_logs(name, lines, errors_only)` — recent logs, secrets redacted.
  - `check_endpoint(url, timeout)` — HTTP status/latency/body snippet (host must be a watched container or `localhost`).
  - `container_stats(name)` — one-shot CPU/memory usage.

  Watched containers are an explicit allow-list (`DEVPILOT_WATCH_CONTAINERS`) — anything else is refused. A problem found by `check_container` auto-logs a `source="watchdog"` journal entry (throttled to at most one per container/problem-type per 10 minutes).

The original Stage 2 (deploy to EC2) is now **Stage 4** — see [`spec.md`](./spec.md) for the full build order. Not started yet.

## Prerequisites

- **Python 3.12+**
- **Docker Desktop** (running)
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

Fully `moto`-mocked (and mocked Docker/HTTP clients for the Stage 2 tools) — no Docker daemon, no real AWS, no network calls. Should show all tests passing.

## Quickstart (Stage 2 — docker compose)

```powershell
git clone https://github.com/Kashish-0931/Devpilot-mcp.git
cd Devpilot-mcp
Copy-Item .env.example .env
docker compose up --build
```

That's it — this starts five containers: DynamoDB Local, a one-shot table-bootstrap step, `docker-socket-proxy` (see "Docker access" below), DevPilot itself (`http://127.0.0.1:8080/mcp`), and `demo-app` (`FAILURE_MODE=missing_env` by default — it starts **already broken**, on purpose).

Connect Claude Code (one line — see Troubleshooting for why that matters):
```powershell
claude mcp add --transport http devpilot http://127.0.0.1:8080/mcp --header "Authorization: Bearer <your DEVPILOT_MCP_TOKEN>"
claude mcp get devpilot   # should show: Status: Connected
```

Open a **new** `claude` session in this folder (an already-open session won't see the newly-registered server) and ask:

> why is demo-app down?

Claude should call `check_container`, see it's not running, call `tail_logs`, find the real error (a missing `DATABASE_URL`), and explain the fix — without you telling it what's wrong.

### `FAILURE_MODE` — every way `demo-app` can break

Set `FAILURE_MODE` in `.env` (or `docker compose up -e FAILURE_MODE=... demo-app` to override one-off), then `docker compose up -d --build demo-app` to apply it:

| `FAILURE_MODE` | What happens | Ask Claude | Expected diagnosis |
|---|---|---|---|
| `none` | Healthy | "check demo-app" | Running, healthy |
| `missing_env` | Crashes at startup (`KeyError: DATABASE_URL`) | "why is demo-app down?" | Not running; logs show the missing env var |
| `crash_loop` | Runs ~5s, exits, restarts, repeats | "why does demo-app keep restarting?" | High restart count; logs show the simulated crash |
| `db_down` | `/api` returns 500, logs a connection-refused error | "why do demo-app's API calls fail?" | 500 from `check_endpoint`; logs show DB connection refused |
| `errors_500` | `/api` throws a real exception | "is demo-app returning errors?" | 500 + a traceback in the logs |
| `memory_leak` | Grows ~10MB/s until OOM-killed (exit 137) | "is demo-app using too much memory?" | `container_stats` shows rising memory; eventually `oom_killed: true` |
| `slow` | `/api` takes ~8s to respond | "is demo-app slow?" | High `response_time_ms` from `check_endpoint` |
| `high_cpu` | `/api` busy-loops for a few seconds | "is demo-app using too much CPU?" | High `cpu_percent` from `container_stats` |

**A real limitation, not a bug**: DevPilot catches problems with *symptoms* — crashes, errors, slowness, resource exhaustion. It has no way to notice a silent logic bug that produces a wrong-but-plausible answer with no error at all.

### Docker access: why there's a `docker-socket-proxy` service

DevPilot's container needs to ask the Docker daemon about *other* containers (`demo-app`). Giving a container direct access to the host's Docker socket is giving it practical root-equivalent control over the whole machine — a well-known container-escape path, not a theoretical one. So DevPilot's own container never touches the real socket; only the small, purpose-built `docker-socket-proxy` service does (mounted **read-only**), and it's configured to allow only the read-only calls the four tools need (`CONTAINERS=1`) with everything else — starting, stopping, `exec`ing into a container — blocked (`POST=0`). This is also what lets DevPilot's own container run as a non-root user. See `spec.md` §7.6 for the full reasoning.

## Alternative: running the server directly (no compose)

Useful for Stage 1-only work, or debugging the server in isolation. Startup order matters — DynamoDB Local first, then the table, then the server, then (optionally) a client:

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

Run this as **one line** — if it gets split across lines (e.g. a multi-line paste with no continuation character), `--header` silently gets dropped and the server will reject every request with `401`:

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
| `401` from the server | Token mismatch — the `Authorization: Bearer ...` header doesn't match `DEVPILOT_MCP_TOKEN` in `.env` (or whatever's currently set). Missing token also gives `401`. If you ran `claude mcp add` as a multi-line paste, check `claude mcp get devpilot` actually shows a `Headers:` line — a split command silently drops `--header` with no error. |
| `Protected resource ... does not match expected ...` (not a plain `401`) | You connected via `localhost` while the server advertises `127.0.0.1` (or vice versa) — the SDK's OAuth resource check is strict about this even though they're the same machine. Always use `127.0.0.1` everywhere (Inspector, `claude mcp add`), matching `app.py`. |
| `only one usage of each socket address ... 8080` | Something's already listening on port 8080 — likely a previous `python -m devpilot.server` still running. Find it (`netstat -ano \| findstr :8080`) and stop it, or set a different `DEVPILOT_MCP_PORT`. |
| Server won't start, prints `DEVPILOT_MCP_TOKEN must be set` | Expected — the server fails fast rather than starting insecurely. Set it in `.env` or `$env:DEVPILOT_MCP_TOKEN`. |
| `ToolError: 'x' is not in DEVPILOT_WATCH_CONTAINERS` | Expected — the four watch tools refuse any container not on the allow-list. Add it to `DEVPILOT_WATCH_CONTAINERS` in `.env` and restart `devpilot` (`docker compose restart devpilot`). |
| `could not reach Docker` from a watch tool | Inside compose: check `docker-socket-proxy` is up (`docker compose ps`). Running directly on Windows: make sure Docker Desktop itself is running. |
| `docker compose up` fails to bind port 8000/8080 | Something else already has it — likely a leftover container from a previous `docker run` (Stage 1's manual smoke test) or a previous compose run. `docker ps` to find it, `docker stop <name>`, retry. |
| `demo-app` doesn't reflect a `FAILURE_MODE` change | Env var changes need a rebuild+recreate, not just a restart: `docker compose up -d --build demo-app`. |
| Same `source="watchdog"` finding doesn't reappear in the journal | Expected — throttled to once per container/problem-type per 10 minutes (in-memory, resets if `devpilot` restarts). Not a bug. |
