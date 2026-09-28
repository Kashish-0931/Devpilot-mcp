# DevPilot — Technical Spec & Implementation Plan

## 1. Purpose

DevPilot is an AI ops assistant for infrastructure. It has two flows:

- **Ask flow** (on demand): a person asks Claude something like *"why is my API down?"*. Claude calls DevPilot's tools over **MCP** (Streamable HTTP, token-authenticated). DevPilot checks EC2, Docker, and CloudWatch logs, returns the data, and Claude explains the root cause and the fix.
- **Alert flow** (automatic, no one asks): the API goes down → a CloudWatch alarm fires → SNS passes the event to a Lambda → the Lambda collects logs, asks an LLM (Claude API) for a diagnosis, and sends a Telegram/email message, e.g. *"API down, the container crashed, missing env var."*

This document is the spec for the whole project and the concrete build plan for what we implement first (Stage 1). It supersedes ad-hoc description and is meant to be the reference as the project grows — update it as decisions change.

## 2. Current repo state (as of this plan)

`C:\Users\kunal\Desktop\DevPilot` — git repo, remote `origin` = `https://github.com/Kashish-0931/Devpilot-mcp.git` (empty on GitHub), local branch `main`, one initial commit (scaffold: `pyproject.toml`, `.gitignore`, `src/devpilot` package skeleton).

Existing files:
- `pyproject.toml` — project `devpilot`, `requires-python >=3.11`, deps `["boto3>=1.34"]`, dev deps `["pytest>=8.0", "moto[dynamodb]>=5.0"]`, src-layout (`where = ["src"]`). *(Stage 1 bumps this to `>=3.12` — see §6.10.)*
- `.gitignore` — standard Python ignores.
- `src/devpilot/__init__.py` — `__version__ = "0.1.0"`.
- `src/devpilot/journal/__init__.py` — already does `from .models import JournalEntry` / `from .store import JournalStore` (both files don't exist yet — this spec creates them).

Nothing else exists. No AWS resources are provisioned. The account is on the **AWS Free plan** — see §9 for the constraints that apply to every AWS-touching stage. Stage 1 itself stays code-only / locally testable (`moto` + optional DynamoDB Local), no real AWS account needed yet.

## 3. Tech stack (whole project)

| Layer | Tech |
|---|---|
| Language | Python 3.12 |
| MCP | Official MCP SDK **v2** (`from mcp.server import MCPServer`), Streamable HTTP transport |
| AWS SDK | boto3 |
| LLM | Claude API (diagnosis, summaries) — billed separately by Anthropic, not AWS |
| Embeddings + vectors | OpenAI/Voyage embeddings + Supabase pgvector *(provider undecided — open question, only needed at Stage 7)* |
| Container | Docker (`python:3.12-slim` base image) |
| Compute | EC2 (server), Lambda (alerts, webhooks) — region **ap-south-1** (Mumbai), Free-plan-eligible sizing only (§9) |
| Storage | DynamoDB (journal, `PAY_PER_REQUEST`), S3 (snapshots, reports) |
| Monitoring | CloudWatch Logs, Metrics, Alarms, Dashboard — kept within always-free limits (§9) |
| Messaging | SNS → Telegram bot / email |
| Deploy | SSM Run Command, ECR (images) |
| Security | IAM roles (least privilege), token auth, env secrets via **SSM Parameter Store SecureString** (not Secrets Manager — §9) |
| CI | GitHub Actions |
| IaC | **Terraform**, introduced as one dedicated pass *after Stage 5* that codifies Stages 2–5 (provisioned manually via the AWS console until then) |

## 4. MCP SDK facts (verified against `py.sdk.modelcontextprotocol.io`, not assumed)

- The official SDK is genuinely on a v2 line; the server class is literally `MCPServer` — `from mcp.server import MCPServer`.
- Tools register with `@mcp.tool()`; a plain type-hinted function signature *is* the schema (no manual JSON Schema).
- `mcp.streamable_http_app()` returns an ordinary ASGI app (serve with `uvicorn`); the MCP endpoint lives at `/mcp`. When run standalone (not mounted into a host app) it manages `mcp.session_manager`'s lifespan automatically.
- **Auth is built into `MCPServer` itself** via a `TokenVerifier` implementation passed as `token_verifier=`, paired with `auth=AuthSettings(...)` (required together, or `MCPServer()` raises `ValueError`). This is *not* implemented as Starlette middleware.
- **Known trap, avoided by design**: wrapping the streamable-HTTP ASGI app in Starlette's `BaseHTTPMiddleware` for auth silently breaks SSE streaming (`ClosedResourceError`) — documented SDK issue `modelcontextprotocol/python-sdk#2702`. Using the SDK's own `TokenVerifier` hook sidesteps this entirely.

## 5. Build order

Reordered from the original plan: local capability now comes before any AWS deployment, so the actual "watch and diagnose" behavior gets built and proven on a laptop — free, fast, disposable — before EC2/IAM/security-group complexity enters the picture. The AWS-deployment stage that used to be Stage 2 is now Stage 4, unchanged in content, just later.

1. **Journal** ✅ — append-only audit/event log (DynamoDB-backed), readable *and writable* by humans and by DevPilot itself. **Done** — see §6.
2. **Watch tools (local Docker)** — DevPilot's first "eyes": `check_container`, `tail_logs`, `check_endpoint`, `container_stats`, running entirely against local Docker (a `docker-compose` stack: DynamoDB Local + DevPilot + a deliberately-fragile `demo-app`). No AWS involved. **This spec covers it in full — see §7.**
3. **Security audit (AWS APIs from laptop)** — an on-demand `security_audit()` MCP tool checking AWS account posture (public S3 buckets, open SSH, root MFA, stale IAM keys) via read-only AWS API calls made directly from the laptop's own credentials — no persistent AWS resources, nothing deployed.
4. **Deploy to EC2** — containerize the MCP server, run it on a real EC2 instance for the first time. Provisioned **manually via the AWS console**: instance, IAM role, security group, ECR repo, and the `devpilot-journal` DynamoDB table itself (`pk` String, `sk` String, on-demand/`PAY_PER_REQUEST` capacity — same schema as Stage 1's dev-only `create_journal_table`, now created for real). *(This is the original Stage 2 plan, unchanged in content — a full runbook already exists and gets folded back into this spec when the stage starts.)*
5. **Alerts** — the automatic Alert flow (SNS → Lambda → LLM diagnosis → Telegram/email), reusing Stage 2's check functions instead of duplicating them.

   **↳ Terraform pass** (after Stage 5, before Stage 6): codifies everything provisioned manually in Stage 4 (EC2 instance, security group, ECR repo, DynamoDB table, IAM roles/policies) and Stage 5 (SNS topic, Lambda + role, CloudWatch alarms) into Terraform, so Stage 6 onward operates against IaC-managed infra instead of console-clicked resources.

6. **Deploy/rollback** — SSM Run Command + ECR deploy pipeline with automatic rollback, run against the now-Terraform-managed infra.
7. **Codebase brain** — RAG over the codebase via embeddings + Supabase pgvector, new MCP tool(s). Runs locally, no AWS compute.
8. **Dashboard** — UI over journal history, current health, recent alerts.

Stages 4–6 are the ones that touch real AWS deployment and must fit inside the **Free plan's 6-month window** (§9); Stages 1, 2, and 7 run entirely locally and aren't time-boxed by it. Stage 3 makes AWS *API calls* (read-only, from the laptop's own credentials) but deploys nothing persistent.

---

## 6. Stage 1 spec (full detail): Journal module + MCP server skeleton

### 6.1 File layout

```
src/devpilot/
  journal/
    models.py     # NEW — JournalEntry dataclass
    store.py      # NEW — JournalStore (DynamoDB-backed)
    config.py     # NEW — shared env var names/defaults
  server/
    __init__.py   # NEW
    app.py        # NEW — builds the MCPServer + registers tools
    auth.py        # NEW — TokenVerifier implementation
    tools.py        # NEW — tool functions (get_recent_journal_entries, log_journal_entry)
    __main__.py     # NEW — `python -m devpilot.server` entrypoint
scripts/
  bootstrap_local_table.py   # NEW — creates the journal table against DynamoDB Local, for manual smoke testing
tests/
  conftest.py             # NEW (repo root) — moto DynamoDB fixtures
  journal/test_models.py   # NEW
  journal/test_store.py    # NEW
  server/test_tools.py     # NEW
  server/test_auth.py      # NEW
```

`journal/__init__.py` (existing) needs no changes — it already imports `JournalEntry`/`JournalStore` from the files this stage creates.

### 6.2 Data model — `journal/models.py`

**`JournalEntry`** (frozen dataclass):

| Field | Type | Notes |
|---|---|---|
| `source` | `str` | who logged it: `"human"` (default for manual entries), `"watchdog"`, `"alert"`, `"deploy"`, `"security-scan"`, `"codebase-brain"` |
| `level` | `str` | one of `VALID_LEVELS = {"info", "warning", "error", "critical"}`; bad value raises `ValueError` in `__post_init__` |
| `message` | `str` | human-readable summary |
| `metadata` | `dict` | free-form structured detail, default `{}` |
| `id` | `str` | `uuid4()`, auto-generated |
| `timestamp` | `str` | UTC ISO8601 (`datetime.now(timezone.utc).isoformat()`), auto-generated |

Methods:
- `to_item() -> dict`: DynamoDB item — `pk="journal"`, `sk=f"{timestamp}#{id}"` (single-partition, time-sorted — a `Query` with `ScanIndexForward=False` gives newest-first with no table `Scan`), plus the plain fields. Uses the boto3 **resource** API so native Python types marshal automatically — no manual `TypeSerializer`.
- `from_item(item: dict) -> JournalEntry`: reconstructs from a DynamoDB item; prefers the explicit `timestamp` attribute over parsing it out of `sk`.

### 6.3 Store — `journal/store.py`

**`JournalStore(table=None, table_name=None, resource=None)`**
- If `table` given (a bound `Table` — the moto-test injection path), use it directly.
- Else resolve `table_name` from arg → `config.journal_table_name()` → build via `(resource or boto3.resource("dynamodb")).Table(table_name)`.
- No region/credential/endpoint logic anywhere — boto3's default chain owns that, so swapping to an EC2/Lambda IAM role later, or to DynamoDB Local for smoke testing, is a **no-code-change** config swap (see §6.3a).

Methods:
- `record(source, level, message, metadata=None) -> JournalEntry` — constructs the entry (validation happens before any AWS call), `put_item`s it, returns it.
- `recent(limit=50) -> list[JournalEntry]` — `Query(KeyConditionExpression=Key("pk").eq("journal"), ScanIndexForward=False, Limit=limit)`, mapped through `from_item`. **No pagination in v1** (`LastEvaluatedKey` deferred — acceptable now, must be revisited by Stage 8/dashboard).

Module-level **`create_journal_table(resource, table_name)`**: dev/test bootstrap only — `create_table` with the `pk`/`sk` schema, `PAY_PER_REQUEST` billing, `.wait_until_exists()`. Docstring states explicitly: *dev/test convenience only — from the post-Stage-5 Terraform pass onward, Terraform owns this table; do not call against real infrastructure.*

### 6.3a Local DynamoDB for smoke testing

`store.py` needs **no code changes** to support this — botocore already honors the per-service endpoint override env var. To smoke-test against a real (local) DynamoDB wire protocol instead of `moto`'s in-process mock (all commands in **PowerShell** syntax, per project convention — see §6.12a):

```powershell
docker run -d -p 8000:8000 amazon/dynamodb-local
$env:AWS_ENDPOINT_URL_DYNAMODB = "http://localhost:8000"
$env:AWS_ACCESS_KEY_ID = "dummy"
$env:AWS_SECRET_ACCESS_KEY = "dummy"
$env:AWS_DEFAULT_REGION = "ap-south-1"
```

DynamoDB Local doesn't validate credentials, but boto3 still refuses to build a client with none configured — the three dummy `AWS_*` vars satisfy that without ever touching a real AWS account. `boto3.resource("dynamodb")` picks up `AWS_ENDPOINT_URL_DYNAMODB` automatically once it's set.

`conftest.py` sets the same three dummy credential vars via an **autouse** fixture (§6.9), so the `pytest` suite can never fall through to a real AWS account even if a test forgets to inject the moto-mocked store.

**`scripts/bootstrap_local_table.py`**: a small script that builds a `boto3.resource("dynamodb")` (relying on the same env-var override) and calls `create_journal_table(resource, journal_table_name())` against it — run once before smoke-testing the server locally.

### 6.4 Config — `journal/config.py`

```python
JOURNAL_TABLE_ENV_VAR = "DEVPILOT_JOURNAL_TABLE"
DEFAULT_JOURNAL_TABLE = "devpilot-journal"

def journal_table_name() -> str:
    return os.environ.get(JOURNAL_TABLE_ENV_VAR, DEFAULT_JOURNAL_TABLE)
```

Single source of truth shared by `store.py`, `server/app.py`, `scripts/bootstrap_local_table.py`, and later stages.

### 6.5 Auth — `server/auth.py`

The expected token is read **once, at startup** (in `__main__.py`, §6.8 — not `app.py`) and passed all the way down as a plain argument — `verify_token` never touches `os.environ`, and a missing token fails the process immediately with a clear error instead of failing confusingly on the first request:

```python
from mcp.server.auth.provider import AccessToken, TokenVerifier
import hmac

class StaticTokenVerifier(TokenVerifier):
    def __init__(self, expected_token: str):
        self._expected = expected_token

    async def verify_token(self, token: str) -> AccessToken | None:
        if hmac.compare_digest(token, self._expected):
            return AccessToken(token=token, client_id="devpilot", scopes=[])
        return None
```

A single static bearer token via `DEVPILOT_MCP_TOKEN` is the right scope for Stage 1 (one server, one caller — Claude). Token rotation / multiple callers / real OAuth is explicitly out of scope until it's an actual requirement — don't build it preemptively.

### 6.6 Server — `server/app.py` (factory, no module-level `mcp`)

`app.py` exposes a **factory**, `create_app(...)`, instead of building a module-level `mcp`/`app` at import time. This does two things: it lets tests build an app wired to a moto-backed store without touching real config, and it means `tools.py` never needs to import anything from `app.py` — tool functions are plain, store-taking functions (§6.7) that `create_app` wraps in closures and registers, so there's **no circular import** between `app.py` and `tools.py` in either direction. Reading `DEVPILOT_MCP_TOKEN` and failing fast if it's missing moves entirely to `__main__.py` (§6.8) — `app.py` never reads `os.environ` itself, it just takes `token`/`port` as parameters:

```python
from mcp.server import MCPServer
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl

from devpilot.journal.store import JournalStore
from devpilot.server import tools
from devpilot.server.auth import StaticTokenVerifier


def create_app(token: str, store: JournalStore | None = None, port: int = 8080):
    store = store or JournalStore()

    mcp = MCPServer(
        "devpilot",
        token_verifier=StaticTokenVerifier(token),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(f"http://127.0.0.1:{port}"),
            resource_server_url=AnyHttpUrl(f"http://127.0.0.1:{port}/mcp"),
            required_scopes=[],
            validate_token_resource=False,
        ),
    )

    @mcp.tool()
    def get_recent_journal_entries(limit: int = 50) -> list[dict]:
        """Return the most recent DevPilot journal entries, newest first."""
        return tools.get_recent_journal_entries(store, limit)

    @mcp.tool()
    def log_journal_entry(message: str, level: str = "info", metadata: dict | None = None) -> dict:
        """Record a human-authored note or decision in the DevPilot journal."""
        return tools.log_journal_entry(store, message, level, metadata)

    return mcp.streamable_http_app()
```

`issuer_url`/`resource_server_url` are placeholders satisfying the SDK's OAuth-shaped interface — we are not doing real OAuth discovery, just reusing its bearer-token check. Revisit only if a real external OAuth issuer becomes a requirement.

**Must be `127.0.0.1`, not `localhost`** — the SDK validates that the host a client actually connects to matches `resource_server_url`, even with `validate_token_resource=False`. Every client-facing instruction in this spec (§6.12) uses `127.0.0.1` for the same reason (§6.12b) — if they ever drift apart, connections fail with a "Protected resource ... does not match expected ..." error, not a plain `401`.

### 6.7 Tools — `server/tools.py` (plain functions, store passed in)

Two tools in Stage 1 — the journal is readable *and* writable, not read-only. Each is a **plain function taking the store explicitly**, not a decorated closure — `create_app` (§6.6) is what wraps them as `@mcp.tool()`-registered closures. This is also exactly what lets `test_tools.py` call them directly with an injected moto-backed store, with no MCP framework or running server involved:

```python
from dataclasses import asdict

from devpilot.journal.store import JournalStore


def get_recent_journal_entries(store: JournalStore, limit: int = 50) -> list[dict]:
    return [asdict(entry) for entry in store.recent(limit)]


def log_journal_entry(store: JournalStore, message: str, level: str = "info", metadata: dict | None = None) -> dict:
    """Always source="human" — this tool is for people, not internal code."""
    entry = store.record(source="human", level=level, message=message, metadata=metadata or {})
    return asdict(entry)
```

`log_journal_entry` has **no `source` parameter** — it's a human-facing tool, so every entry it creates is `source="human"`. The other sources (`"watchdog"`, `"alert"`, `"deploy"`, `"security-scan"`, `"codebase-brain"`) are only ever passed by internal code calling `JournalStore.record(...)` directly (Stage 3 onward), never through this tool.

Both tools return plain dicts (not `to_item()`, which is DynamoDB-shaped), so MCP results are directly JSON-able. Stage 3 adds three more tools (`check_instance`, `check_container`, `tail_logs`) alongside these in the same module; Stage 4 adds `security_audit()`; Stage 7 adds `search_codebase`.

### 6.8 Entrypoint — `server/__main__.py`

This is where `DEVPILOT_MCP_TOKEN` is actually read and validated — the only place in Stage 1 that fails fast on a missing token:

```python
import os
import sys

import uvicorn

from devpilot.server.app import create_app


def main() -> None:
    token = os.environ.get("DEVPILOT_MCP_TOKEN")
    if not token:
        sys.exit("DEVPILOT_MCP_TOKEN must be set before starting the DevPilot MCP server")

    port = int(os.environ.get("DEVPILOT_MCP_PORT", "8080"))
    app = create_app(token, port=port)
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
```

Local run: `python -m devpilot.server`.

### 6.9 Tests (`moto`-backed, no real AWS)

- Root `conftest.py`:
  - **`fake_aws_credentials` fixture, `autouse=True`**: sets `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_DEFAULT_REGION` to dummy values (`monkeypatch.setenv`, so they're reverted after each test) — every test runs with fake credentials in the environment, so a test that forgets to inject the moto-mocked store still can't reach a real AWS account. It also `monkeypatch.delenv("AWS_ENDPOINT_URL_DYNAMODB", raising=False)`, so `pytest` always exercises `moto` even if the shell it runs in still has the DynamoDB Local override (§6.3a) set from a previous smoke-test session.
  - `dynamodb_resource` fixture (`moto.mock_aws`), `journal_table` fixture (calls `create_journal_table` with a fixed test table name), `journal_store` fixture (`JournalStore(table=journal_table)`).
- `test_models.py` — defaults (uuid4 `id`, ISO `timestamp`), bad-`level` → `ValueError`, frozen (`FrozenInstanceError` on mutation), `to_item`/`from_item` round-trip.
- `test_store.py` — `record()` then `recent()` returns it; multiple records come back newest-first; `limit` respected; nested `metadata` round-trips.
- `test_tools.py` — calls `tools.get_recent_journal_entries(store, limit)` **and** `tools.log_journal_entry(store, message, ...)` directly (plain functions, §6.7 — not over HTTP, no `create_app`) against an injected moto-backed store; confirms a `log_journal_entry` write shows up in a subsequent `get_recent_journal_entries` call, and that its `source` is always `"human"`.
- `test_auth.py` — `StaticTokenVerifier(expected).verify_token(...)`: correct token → `AccessToken`; wrong/missing → `None`. No running server required.

`scripts/bootstrap_local_table.py` is a manual smoke-test convenience, not covered by `pytest`.

### 6.10 `pyproject.toml` additions

- Bump `requires-python` to **`>=3.12`** (project moves to Python 3.12 across the board; Stage 2's Docker base image is `python:3.12-slim`).
- Add to runtime `dependencies`: `mcp>=2.0`, `uvicorn`.
- Dev deps (`pytest`, `moto[dynamodb]`) already sufficient — no changes needed there.
- Docker (for `amazon/dynamodb-local`, §6.3a) must be installed locally to run the smoke test — this is separate from Stage 2's use of Docker for the deployed server image.

### 6.11 Env var reference (fixed now, reused by every later stage)

| Var | Meaning | Default |
|---|---|---|
| `DEVPILOT_JOURNAL_TABLE` | DynamoDB table name | `devpilot-journal` |
| `DEVPILOT_MCP_TOKEN` | Shared bearer token, read once at startup by `__main__.py` (not `app.py` — see §6.8) | *(required, no default — server fails fast if unset)* |
| `DEVPILOT_MCP_PORT` | Local/EC2 listen port | `8080` |
| `AWS_ENDPOINT_URL_DYNAMODB` | Standard AWS SDK override, used only for local smoke testing against DynamoDB Local (§6.3a) — not a DevPilot-specific var | unset in normal/real use |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_DEFAULT_REGION` | Dummy credentials required by boto3 to talk to DynamoDB Local (§6.3a); real region resolution elsewhere still comes from boto3's normal chain, not this var | `dummy` / `dummy` / `ap-south-1`, local smoke-testing only |

Deliberately **no** `DEVPILOT_AWS_REGION` — boto3's normal credential/region chain (env, `~/.aws/config`, instance metadata) owns that; don't introduce a DevPilot-specific override unless a real need appears.

### 6.12a Shell convention

Every shell command in this spec is given in **Windows PowerShell** syntax (`$env:VAR = "value"`, not `export VAR=value` or `VAR=value`), matching the project's actual dev environment.

### 6.12 Connecting a client

- **MCP Inspector** (quick manual poking): run the server (`python -m devpilot.server`), then `npx @modelcontextprotocol/inspector` and point it at `http://127.0.0.1:8080/mcp` with an `Authorization: Bearer <DEVPILOT_MCP_TOKEN>` header — confirms both tools show up and are callable before wiring up a real client.
- **Claude Code CLI** — always as ONE line (a multi-line paste that gets split loses the `--header` silently, with no error pointing at why):
  ```powershell
  claude mcp add --transport http devpilot http://127.0.0.1:8080/mcp --header "Authorization: Bearer $env:DEVPILOT_MCP_TOKEN"
  ```
  registers DevPilot as an MCP server Claude Code can call in the Ask flow.
- **Claude Desktop note**: Desktop requires **HTTPS** for remote (non-localhost) MCP servers. `http://127.0.0.1:8080` is fine while developing on the same machine; once the server moves to EC2 (Stage 2), a Desktop connection needs TLS in front of it (e.g. a reverse proxy) — Claude Code's CLI connection over plain HTTP to `127.0.0.1` is not affected by this and remains the primary dev-loop path for Stage 1.

### 6.12b Lessons learned (from manual verification on Windows)

These came out of actually running the full local stack (DynamoDB Local + server + MCP Inspector) end to end on Windows — folded back into the spec so they're not re-discovered every time:

- **Use `127.0.0.1`, not `localhost`, in every URL** (Inspector, `claude mcp add`, curl, browser). `localhost` can resolve to the IPv6 loopback (`::1`) first on Windows, but the server only binds the IPv4 wildcard (`0.0.0.0`) — so `localhost` intermittently fails to connect while `127.0.0.1` always works.
- **`$env:` variables don't survive a terminal restart** — they're per-session. This is exactly why §6.11 added `.env` support (via `python-dotenv`, loaded in `__main__.py`): real env vars still win when set, but config now survives closing the terminal.
- **Run MCP Inspector in its own plain PowerShell window, not a VS Code integrated terminal** — VS Code's shell auto-activation (venv activation, prompt customization, etc.) can interrupt Inspector's own process management. Each Inspector restart also prints a fresh session/auth URL — always use the one from the *current* run, not a copied old one.
- **DynamoDB Local (`-inMemory`) loses all data on container restart** — including the table itself. Re-run `scripts/bootstrap_local_table.py` after every `docker restart`/recreate of the DynamoDB Local container, or the server will fail with a missing-table error.

### 6.13 Execution steps (in order)

1. `journal/config.py`, `journal/models.py`, `journal/store.py`.
2. `server/__init__.py`, `server/auth.py`, `server/tools.py` (plain functions), `server/app.py` (`create_app` factory), `server/__main__.py` (reads/validates `DEVPILOT_MCP_TOKEN`).
3. `scripts/bootstrap_local_table.py`.
4. Bump `requires-python` to `>=3.12`; add `mcp`, `uvicorn` to `pyproject.toml`.
5. `conftest.py` (including the autouse fake-credentials fixture) + the four test files.
6. venv, `pip install -e ".[dev]"`, `pytest`.
7. Manual smoke test (PowerShell):
   ```powershell
   docker run -d -p 8000:8000 amazon/dynamodb-local
   $env:AWS_ENDPOINT_URL_DYNAMODB = "http://localhost:8000"
   $env:AWS_ACCESS_KEY_ID = "dummy"
   $env:AWS_SECRET_ACCESS_KEY = "dummy"
   $env:AWS_DEFAULT_REGION = "ap-south-1"
   python scripts/bootstrap_local_table.py
   $env:DEVPILOT_MCP_TOKEN = "<some local token>"
   python -m devpilot.server
   ```
   Confirm the server fails fast if `DEVPILOT_MCP_TOKEN` is unset, then confirm 401 with a wrong token and success with the right one.
8. Connect via MCP Inspector, then via `claude mcp add ...` (§6.12); confirm both tools are visible and callable end-to-end (write with `log_journal_entry`, read it back with `get_recent_journal_entries`).
9. Commit, push to `origin/main`.

---

## 7. Stage 2 spec (full detail): Watch tools (local Docker)

DevPilot's first "eyes." Everything in this stage runs against **local Docker only** (via `docker compose`) — no AWS deployment, no EC2. The goal: prove the Ask flow can genuinely diagnose a broken service, end to end, before any AWS deployment complexity enters the picture.

### 7.1 `demo-app/` — the "patient"

A tiny Flask app whose only job is to be a realistic, controllable thing to watch and break. Controlled by one env var, `FAILURE_MODE`:

| `FAILURE_MODE` | Behavior |
|---|---|
| `none` | Healthy. `/health` and `/api` both return 200. |
| `missing_env` | Crashes at startup (`KeyError` reading `DATABASE_URL`, which is deliberately not set) — never reaches a running state. |
| `crash_loop` | Starts fine, exits after ~5s (`os._exit(1)`) — with `restart: unless-stopped` in compose, this repeats indefinitely. |
| `db_down` | `/api` logs `ERROR: could not connect to database host ... Connection refused` and returns 500. |
| `errors_500` | `/api` triggers a real exception, logs a traceback, returns 500. |
| `memory_leak` | A background thread keeps allocating (~10MB/s) until it hits the container's memory limit and gets OOM-killed (exit code 137). Compose sets a small `mem_limit` on `demo-app` so this happens within the length of a demo, not eventually. |
| `slow` | `/api` sleeps ~8s before responding. |
| `high_cpu` | `/api` busy-loops for a few seconds before responding. |

Two endpoints only: `/health` (always reports current mode, used for the "is it even listening" check) and `/api` (where the interesting failure behavior lives). `demo-app/Dockerfile` is a minimal `python:3.12-slim` + Flask image; `container_name: demo-app` is set explicitly in compose so the tools' `name` parameter is just the literal string `"demo-app"`, not a compose-generated name.

### 7.2 File layout

```
demo-app/
  app.py            # NEW — the Flask "patient", FAILURE_MODE-driven
  requirements.txt   # NEW — just flask
  Dockerfile          # NEW

src/devpilot/checks/
  __init__.py         # NEW
  docker_client.py     # NEW — get_docker_client() -> docker.DockerClient (docker.from_env())
  container_checks.py  # NEW — check_container, tail_logs, container_stats, classify_problem (pure functions)
  http_checks.py        # NEW — check_endpoint (pure function)
  redaction.py           # NEW — redact(text) -> str
  throttle.py             # NEW — JournalThrottle

src/devpilot/journal/config.py   # EDIT — add watch_containers()
src/devpilot/server/tools.py      # EDIT — 4 new thin @-registration-ready wrapper functions
src/devpilot/server/app.py         # EDIT — register the 4 new tools, wire watch list / docker client / throttle
scripts/bootstrap_local_table.py    # EDIT — add a small retry loop (compose starts services concurrently)

Dockerfile          # NEW (repo root) — packages devpilot.server itself, for compose
.dockerignore        # NEW (repo root)
docker-compose.yml    # NEW (repo root) — dynamodb-local + bootstrap + docker-socket-proxy + devpilot + demo-app

tests/checks/
  __init__.py
  test_container_checks.py   # NEW
  test_http_checks.py         # NEW
  test_redaction.py            # NEW
  test_throttle.py              # NEW
```

### 7.3 The four tools (DevPilot's "eyes")

All four are **read-only** — no ability to start, stop, or exec into a container, even though the underlying Docker access would technically allow it. That boundary is enforced in our own code, not by Docker.

- **`check_container(name)`** → `{name, status, exit_code, oom_killed, restart_count, started_at, finished_at, image, health}`. `status` is Docker's own container state (`running`/`exited`/`restarting`/...); `health` is `None` unless the image defines a `HEALTHCHECK` (then `"healthy"`/`"unhealthy"`/`"starting"`).
- **`tail_logs(name, lines=50, errors_only=False)`** → a list of log lines, each timestamped (`docker`'s own `timestamps=True` on `.logs()`), each passed through `redact()` (§7.5). `lines` is clamped to `[1, 500]`. `errors_only=True` keeps only lines containing (case-insensitive) `ERROR`, `Exception`, `Traceback`, `CRITICAL`, or `FATAL`.
- **`check_endpoint(url, timeout=10)`** → `{url, status_code, response_time_ms, body_snippet, error}`. `body_snippet` is redacted. **URL allow-list, enforced before any request is made**: the URL's host must be either a name in the watch list or `localhost`/`127.0.0.1` — anything else is a `ToolError`, not a silent request. A connection failure/timeout to an *allowed* host is not an error condition for the tool itself — it's exactly the kind of finding DevPilot exists to report, so it comes back as a normal result (`error` field set, `status_code: None`), not a raised exception.
- **`container_stats(name)`** → `{name, cpu_percent, memory_usage_bytes, memory_limit_bytes, memory_percent}`. One-shot (`container.stats(stream=False)`), not a live stream. CPU % uses the standard Docker CPU-delta formula.

All four validate the container name against the watch list **first** (§7.4) — `ToolError` if it's not on the list, before touching Docker at all. All four also catch `docker.errors.NotFound` (→ `ToolError`, container doesn't exist) and `docker.errors.DockerException` (→ `ToolError`, Docker itself is unreachable) around the actual Docker call.

### 7.4 Watch list — `DEVPILOT_WATCH_CONTAINERS`

A comma-separated env var (`journal/config.py`'s `watch_containers() -> list[str]`), e.g. `DEVPILOT_WATCH_CONTAINERS=demo-app`. Enforcement is **strict**: any of the four tools called against a container name not on this list raises a `ToolError` immediately — this isn't just documentation of intended use, it's a real boundary, since Docker-socket access (§7.6) is powerful enough that "which containers can even be named" is a meaningful scope limit.

### 7.5 Safety: redaction and the auto-journal throttle

- **`redact(text)`** (`checks/redaction.py`) — applied to every `tail_logs` line and every `check_endpoint` body snippet before it ever leaves DevPilot. Pattern-replaces (case-insensitive) `password=`, `token=`, `secret=`, `api_key=` (value → `[REDACTED]`), `Authorization: Bearer ...` (token → `[REDACTED]`), and AWS access key IDs (`AKIA[0-9A-Z]{16}` → `[REDACTED_AWS_KEY]`). A best-effort safety net, not a guarantee against every possible secret shape.
- **Journal throttle** (`checks/throttle.py`, `JournalThrottle`) — when `check_container` finds a problem (via `classify_problem()`: `oom_killed` → `"oom_killed"`, else `status != "running"` → `"not_running"`, else `health == "unhealthy"` → `"unhealthy"`, else no problem), the wrapper in `server/tools.py` writes a `source="watchdog"` journal entry — but **at most once per `(container, problem_type)` pair per 10 minutes**, in-memory (`should_log(name, problem_type) -> bool`, an injectable clock for deterministic tests). This stops repeated diagnosis calls from flooding the journal with duplicate findings.

### 7.6 Docker access: `docker-socket-proxy`, not a raw socket mount

Giving a container access to the host's Docker socket (`/var/run/docker.sock`) is giving it practical root-equivalent control over the *entire host* — a container that can talk to the socket can launch a new container that mounts the whole host filesystem, which is a well-known, trivial container-escape path. This is real, not theoretical, so it's not mounted directly into DevPilot's own container. Instead:

- A dedicated `docker-socket-proxy` service (`tecnativa/docker-socket-proxy`) is the **only** thing that mounts the real socket (read-only: `/var/run/docker.sock:/var/run/docker.sock:ro`), and exposes a deliberately narrow HTTP API: `CONTAINERS=1` (enables the GET endpoints `check_container`/`tail_logs`/`container_stats` need — inspect, logs, stats), `POST=0` (blocks every write/start/stop/exec operation categorically, regardless of anything else enabled).
- DevPilot's own container never touches the socket at all — it just sets `DOCKER_HOST=tcp://docker-socket-proxy:2375`, which `docker.from_env()` (`checks/docker_client.py`) honors automatically, with zero code change. This is also what lets DevPilot's container run as a **non-root user** (matching Stage 1's Dockerfile hardening), unlike the raw-socket-mount approach which effectively needs root to have socket permissions on Windows/Docker Desktop.
- **Running DevPilot directly on Windows** (`python -m devpilot.server`, no compose) skips the proxy entirely — `docker.from_env()` talks to Docker Desktop's named pipe directly, which is exactly the same trust level as running `docker` CLI commands yourself; no extra risk introduced there.
- This same tradeoff resurfaces at Stage 4 (deploy to EC2) — a real server, not Docker Desktop's abstraction — and will need re-deciding there; not solved now, just flagged.

### 7.7 `docker-compose.yml`

Five services: `dynamodb-local`, a one-shot `bootstrap` (runs `scripts/bootstrap_local_table.py`, depends on `dynamodb-local`, exits when done), `docker-socket-proxy`, `devpilot` (depends on `bootstrap` completing and `docker-socket-proxy` starting; `DOCKER_HOST` points at the proxy; **bound to `127.0.0.1:8080:8080`, not `0.0.0.0`** — not reachable from outside the machine even accidentally), and `demo-app` (`container_name: demo-app`, `restart: unless-stopped` so `crash_loop` actually loops, a small `mem_limit` so `memory_leak` gets OOM-killed within a demo-length time window). Compose networking means services reach each other by service/container name (`http://demo-app:5000`, `http://dynamodb-local:8000`) — no `host.docker.internal` needed once everything is in the same compose stack. Config comes from the repo's existing `.env` file, which compose reads automatically.

### 7.8 Tests (mocked Docker/HTTP clients — no real Docker needed for `pytest`)

Same philosophy as Stage 1's `moto` mocking: lightweight fake `docker` client/container objects (not a real daemon) so `pytest` runs anywhere, fast. Coverage: container `running`/`exited`/`oom_killed`/`restarting`/not-found/not-in-watch-list/Docker-unreachable; `tail_logs`'s `errors_only` filter; `redact()` against each secret pattern; `check_endpoint` against 200/500/timeout responses and the URL allow-list (watched name, `localhost`, and a rejected arbitrary host); `container_stats`' CPU/memory math against a crafted fake stats payload; `JournalThrottle` (logs once, suppresses within the window, logs again after it, using an injectable fake clock — no real sleeping).

### 7.9 README additions

A 3-step quickstart (clone → copy `.env.example` to `.env` → `docker compose up`), how to connect Claude Code, and a table mapping every `FAILURE_MODE` to how to trigger it, the question to ask Claude, and the expected diagnosis — ending in the capstone demo: ask a fresh Claude Code session *"why is demo-app down?"* and watch it call `check_container` → `tail_logs` → explain the root cause, unprompted. Also documents the `docker-socket-proxy` tradeoff (§7.6) plainly, and one explicit limitation: DevPilot catches problems with *symptoms* (crashes, errors, slowness, resource exhaustion) — it has no way to notice a silent logic bug that produces a wrong-but-plausible answer with no error at all.

---

## 8. Stages 3–8 spec (architecture-level)

- **Security audit (AWS APIs from laptop)** — an on-demand `security_audit()` MCP tool, called from the laptop using the developer's own AWS credentials (not deployed anywhere): checks public S3 buckets, port 22 open to `0.0.0.0/0`, root account without MFA, IAM access keys older than 90 days. Read-only AWS API calls only — no persistent resources, so nothing to tear down. Once Stage 4 CI exists, the same logic can additionally run there against build artifacts (image/dependency scanning, Trivy/`pip-audit`) — that CI integration is additive, not required for Stage 3 itself.
- **Deploy to EC2** *(the original Stage 2 plan — content unchanged, just later)* — containerize `devpilot.server` (`python:3.12-slim`, `python -m devpilot.server`), push to ECR, run on a single EC2 instance with a least-privilege instance IAM role (`PutItem`/`Query` scoped to the journal table ARN). Provisioned **manually via the AWS console** — instance, security group, ECR repo, IAM role, **and** the `devpilot-journal` DynamoDB table (`pk` String, `sk` String, on-demand capacity) — in region **ap-south-1**, sized per §9 (t3.micro). The Stage 2 `check_container`/`tail_logs` tools (§7) get reused here, now pointed at containers running on the EC2 instance instead of a laptop — the same Docker-socket-access tradeoff from §7 applies again, this time on a real server. Folded into the **Terraform pass** after Stage 5, which codifies this stage's resources retroactively.
- **Alerts** — CloudWatch Alarm → SNS → Lambda, reusing the Stage 2 check-function logic instead of duplicating it, calling the Claude API for diagnosis (kept minimal — alerts only, §9), sending Telegram/email, writing the outcome to the journal (`source="alert"`). Lambda's role needs journal-table write access; `JournalStore` already works fine constructed fresh per invocation. Secrets (Telegram bot token, Claude API key) live in **SSM Parameter Store SecureString**, not Secrets Manager (§9). Provisioned manually for now; folded into the Terraform pass below.
- **Terraform pass (after Stage 5, before Stage 6)** — codifies everything provisioned manually in Stage 4 and Stage 5: EC2 instance, security group, ECR repo, DynamoDB table (replacing Stage 1's dev-only `create_journal_table`), instance IAM role, SNS topic, Lambda + role, CloudWatch alarms, SSM parameters. From here on, infra changes go through Terraform, not the console.
- **Deploy/rollback** — GitHub Actions builds/pushes to ECR, uses SSM Run Command (not SSH) to redeploy against the now-Terraform-managed EC2 instance, health-checks (reusing the Stage 2 check functions), rolls back to the prior image tag on failure — every attempt logged (`source="deploy"`).
- **Codebase brain** — chunk/embed the codebase (OpenAI or Voyage — **open decision**, see §10) into Supabase pgvector; new `search_codebase` MCP tool alongside the existing ones. Runs locally, no AWS compute — not subject to the Free-plan 6-month window. Logs ingestion runs (`source="codebase-brain"`).
- **Dashboard** — reads `JournalStore.recent()` (this is where deferred pagination must finally be addressed) to show history/health/alerts. Hosting choice (S3+CloudFront static site, or a small API) should stay within Free-plan-eligible services per §9.

## 9. Free plan constraints

The AWS account is on the **Free plan** — never assume Paid-plan features or pricing are available. These constraints apply to every AWS-touching stage (4–6; Stage 3 makes read-only API calls only, no persistent resources):

- **Region**: `ap-south-1` (Mumbai) everywhere — one region for everything, no cross-region resources.
- **Services allowlist**: only Free-plan-eligible services. **Never** use AWS Organizations, Control Tower, IAM Identity Center, Marketplace, Savings Plans, or Reserved Instances.
- **Secrets**: Telegram bot token and Claude API key go in **SSM Parameter Store SecureString** (standard tier), **not** Secrets Manager (Secrets Manager has no free tier; Parameter Store's standard SecureString parameters do).
- **EC2**: a single `t3.micro` instance, 8 GB `gp3` EBS volume. Note the public IPv4 address now carries a small charge (~$3.60/month) — factor that in, and **stop the instance when not actively in use** to avoid unnecessary charges.
- **CloudWatch**: stay within always-free limits — ≤10 alarms, basic (not detailed) metrics, short log retention (e.g. 7 days, not indefinite).
- **Cost Explorer API**: avoid calling it from tools — it's billed per API request even on the Free plan. If a cost-visibility tool is ever added, cache results daily rather than calling on every invocation.
- **DynamoDB**: `PAY_PER_REQUEST` billing is fine — the always-free tier comfortably covers this project's scale.
- **Claude API**: billed separately by Anthropic, not AWS — keep calls minimal (the Alert flow's diagnosis call is the main one; avoid adding speculative LLM calls elsewhere in AWS-side code).
- **Time-boxing**: the Free plan ends after 6 months. Stages 4–6 (everything that provisions real AWS infrastructure) must fit inside that window. Stages 1, 2, and 7 run entirely locally and aren't constrained by it; Stage 3's API calls aren't either (nothing persistent to time-box).

### Teardown checklist (per AWS-touching stage)

| Stage | Tear down |
|---|---|
| 2 — Watch tools (local) | Nothing AWS-side — `docker compose down` (add `-v` to also drop DynamoDB Local's in-memory data, which is lost on restart anyway). |
| 3 — Security audit | Nothing to tear down — read-only API calls, no resources created. |
| 4 — Deploy to EC2 | Stop (or terminate) the EC2 instance when idle; release any allocated Elastic IP; delete unused ECR images. |
| 5 — Alerts | Delete/disable CloudWatch alarms, the SNS topic + subscriptions, the Lambda function, and the SSM parameters holding secrets if the project is paused. |
| Terraform pass | Once codified, `terraform destroy` tears down Stage 4–5's resources in one command — the fastest way to fully stop AWS charges between working sessions. |
| 6 — Deploy/rollback | Remove SSM documents/associations; no persistent compute beyond Stage 4's instance. |

## 10. Open decisions (revisit when that stage starts, not now)

1. **Embeddings provider** — OpenAI vs Voyage for Stage 7 (codebase brain). Not needed until then.
2. **Auth beyond a single static token** — revisit only if multiple callers, token rotation, or real OAuth become an actual need.
3. **`recent()` pagination** — must be addressed by Stage 8 at the latest.
4. **`tail_logs`'s error-keyword filter** (§7) — simple substring matching (`ERROR`/`Exception`/`Traceback`/`CRITICAL`/`FATAL`), not real log-level parsing. Fine for `demo-app`'s plain-text logs; revisit if it proves too noisy/quiet against messier real-world logs later.
5. **Watchdog journal-entry throttling** (§7) — 1 entry per container per problem-type per 10 minutes, in-memory only (resets on restart, not shared across multiple DevPilot instances). Fine for a single-instance personal project; revisit if that ever changes.

## 11. Verification / acceptance criteria for Stage 1

- `pytest` passes locally, fully moto-backed — no real AWS account needed — including the new `log_journal_entry` round-trip test.
- `python -m devpilot.server` refuses to start with a clear error if `DEVPILOT_MCP_TOKEN` is unset; once set, rejects requests with no/wrong bearer token (401) and accepts the correct one.
- Manual smoke test against **DynamoDB Local** (not just `moto`) via `scripts/bootstrap_local_table.py` and `AWS_ENDPOINT_URL_DYNAMODB` succeeds — proving the store works against real DynamoDB wire protocol, not only the mock.
- `log_journal_entry` writes are visible in a subsequent `get_recent_journal_entries` call, newest first.
- Both tools are confirmed reachable via MCP Inspector and via `claude mcp add --transport http ...` from Claude Code.
- `git push -u origin main` succeeds — this becomes the first commit on `https://github.com/Kashish-0931/Devpilot-mcp`.

## 12. Verification / acceptance criteria for Stage 2

- `pytest` passes locally with mocked Docker/HTTP clients — no real Docker daemon needed to run the suite.
- `docker compose up --build` brings up all five services; `demo-app` (default `FAILURE_MODE`) shows as unhealthy/crashed, `dynamodb-local` and `devpilot` are healthy.
- `check_container("demo-app")` correctly reports the broken state; a container name not in `DEVPILOT_WATCH_CONTAINERS` is rejected with a `ToolError`.
- `tail_logs("demo-app", errors_only=True)` surfaces the actual failure line for whatever `FAILURE_MODE` is active.
- A `source="watchdog"` journal entry is created on the first problem detection, and **not** duplicated by repeated checks within 10 minutes (throttle working).
- `check_endpoint` against `http://demo-app:5000/api` (or `/health`) works; against an arbitrary non-watched host, it's rejected before any request is made.
- `container_stats("demo-app")` returns sane CPU%/memory figures.
- **The capstone demo**: a fresh Claude Code session, asked *"why is demo-app down?"*, calls the tools itself and correctly explains the root cause — for at least the default `FAILURE_MODE`.
- `git push` succeeds with Stage 2 on `origin/main`.
