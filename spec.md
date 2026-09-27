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

Nothing else exists. No AWS resources are provisioned. The account is on the **AWS Free plan** — see §8 for the constraints that apply to every AWS-touching stage. Stage 1 itself stays code-only / locally testable (`moto` + optional DynamoDB Local), no real AWS account needed yet.

## 3. Tech stack (whole project)

| Layer | Tech |
|---|---|
| Language | Python 3.12 |
| MCP | Official MCP SDK **v2** (`from mcp.server import MCPServer`), Streamable HTTP transport |
| AWS SDK | boto3 |
| LLM | Claude API (diagnosis, summaries) — billed separately by Anthropic, not AWS |
| Embeddings + vectors | OpenAI/Voyage embeddings + Supabase pgvector *(provider undecided — open question, only needed at Stage 7)* |
| Container | Docker (`python:3.12-slim` base image) |
| Compute | EC2 (server), Lambda (alerts, webhooks) — region **ap-south-1** (Mumbai), Free-plan-eligible sizing only (§8) |
| Storage | DynamoDB (journal, `PAY_PER_REQUEST`), S3 (snapshots, reports) |
| Monitoring | CloudWatch Logs, Metrics, Alarms, Dashboard — kept within always-free limits (§8) |
| Messaging | SNS → Telegram bot / email |
| Deploy | SSM Run Command, ECR (images) |
| Security | IAM roles (least privilege), token auth, env secrets via **SSM Parameter Store SecureString** (not Secrets Manager — §8) |
| CI | GitHub Actions |
| IaC | **Terraform**, introduced as one dedicated pass *after Stage 5* that codifies Stages 2–5 (provisioned manually via the AWS console until then) |

## 4. MCP SDK facts (verified against `py.sdk.modelcontextprotocol.io`, not assumed)

- The official SDK is genuinely on a v2 line; the server class is literally `MCPServer` — `from mcp.server import MCPServer`.
- Tools register with `@mcp.tool()`; a plain type-hinted function signature *is* the schema (no manual JSON Schema).
- `mcp.streamable_http_app()` returns an ordinary ASGI app (serve with `uvicorn`); the MCP endpoint lives at `/mcp`. When run standalone (not mounted into a host app) it manages `mcp.session_manager`'s lifespan automatically.
- **Auth is built into `MCPServer` itself** via a `TokenVerifier` implementation passed as `token_verifier=`, paired with `auth=AuthSettings(...)` (required together, or `MCPServer()` raises `ValueError`). This is *not* implemented as Starlette middleware.
- **Known trap, avoided by design**: wrapping the streamable-HTTP ASGI app in Starlette's `BaseHTTPMiddleware` for auth silently breaks SSE streaming (`ClosedResourceError`) — documented SDK issue `modelcontextprotocol/python-sdk#2702`. Using the SDK's own `TokenVerifier` hook sidesteps this entirely.

## 5. Build order

1. **Journal** — append-only audit/event log (DynamoDB-backed), readable *and writable* by humans and by DevPilot itself. *Not started* (despite an earlier doc marking it done — no code exists). **This spec covers it in full.**
2. **Docker + EC2** — containerize the MCP server, run on EC2. Provisioned **manually via the AWS console** for now: instance, IAM role, security group, ECR repo, and the `devpilot-journal` DynamoDB table itself (`pk` String, `sk` String, on-demand/`PAY_PER_REQUEST` capacity — same schema as Stage 1's dev-only `create_journal_table`, now created for real).
3. **Watchdog** — shared check functions (EC2 status, Docker container status, CloudWatch log tail), exposed both as MCP tools and used by a background polling loop.
4. **Security scan** — CI scanning (Trivy, `pip-audit`) plus an on-demand `security_audit()` MCP tool for AWS account posture.
5. **Alerts** — the automatic Alert flow (SNS → Lambda → LLM diagnosis → Telegram/email).

   **↳ Terraform pass** (after Stage 5, before Stage 6): codifies everything provisioned manually in Stages 2–5 — EC2 instance, security group, ECR repo, DynamoDB table, IAM roles/policies, SNS topic, Lambda + role, CloudWatch alarms — into Terraform, so Stage 6 onward operates against IaC-managed infra instead of console-clicked resources.

6. **Deploy/rollback** — SSM Run Command + ECR deploy pipeline with automatic rollback, run against the now-Terraform-managed infra.
7. **Codebase brain** — RAG over the codebase via embeddings + Supabase pgvector, new MCP tool(s). Runs locally, no AWS compute.
8. **Dashboard** — UI over journal history, current health, recent alerts.

Stages 2–6 are the ones that touch real AWS and must fit inside the **Free plan's 6-month window** (§8); Stages 1 and 7 run entirely locally and aren't time-boxed by it.

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

## 7. Stages 2–8 spec (architecture-level)

- **Docker + EC2** — containerize `devpilot.server` (`python:3.12-slim`, `python -m devpilot.server`), push to ECR, run on a single EC2 instance with a least-privilege instance IAM role (`PutItem`/`Query` scoped to the journal table ARN). Provisioned **manually via the AWS console** — instance, security group, ECR repo, IAM role, **and** the `devpilot-journal` DynamoDB table (`pk` String, `sk` String, on-demand capacity) — in region **ap-south-1**, sized per §8 (t3.micro). Folded into the **Terraform pass** after Stage 5, which codifies this stage's resources retroactively.
- **Watchdog** — shared check functions (`check_instance`, `check_container`, `tail_logs`) written **once** and used two ways: exposed as `@mcp.tool()` functions in `server/tools.py` so the Ask flow can call them on demand, *and* called directly from a background polling loop (second container, or systemd/cron on the same instance) that writes findings to the journal (`source="watchdog"`) via `JournalStore.record(...)` **in-process** — the first proof the store works outside the MCP-tool request path. No AWS resources beyond what Stage 2 already provisioned unless a separate schedule is added later.
- **Security scan** — CI-run image/dependency scanning (Trivy, `pip-audit`) before ECR push stays as-is, results logged to the journal (`source="security-scan"`). **Additionally**, an on-demand `security_audit()` MCP tool checks AWS account posture directly: public S3 buckets, port 22 open to `0.0.0.0/0`, root account without MFA, IAM access keys older than 90 days — so the Ask flow can answer "is anything insecure right now" the same way it answers infra-health questions, not just via CI.
- **Alerts** — CloudWatch Alarm → SNS → Lambda, reusing the `check_instance`/`check_container`/`tail_logs` logic from Stage 3 instead of duplicating it, calling the Claude API for diagnosis (kept minimal — alerts only, §8), sending Telegram/email, writing the outcome to the journal (`source="alert"`). Lambda's role needs journal-table write access; `JournalStore` already works fine constructed fresh per invocation. Secrets (Telegram bot token, Claude API key) live in **SSM Parameter Store SecureString**, not Secrets Manager (§8). Provisioned manually for now; folded into the Terraform pass below.
- **Terraform pass (after Stage 5, before Stage 6)** — codifies everything provisioned manually in Stages 2–5: EC2 instance, security group, ECR repo, DynamoDB table (replacing Stage 1's dev-only `create_journal_table`), instance IAM role, SNS topic, Lambda + role, CloudWatch alarms, SSM parameters. From here on, infra changes go through Terraform, not the console.
- **Deploy/rollback** — GitHub Actions builds/pushes to ECR, uses SSM Run Command (not SSH) to redeploy against the now-Terraform-managed EC2 instance, health-checks (reusing Stage 3's check functions), rolls back to the prior image tag on failure — every attempt logged (`source="deploy"`).
- **Codebase brain** — chunk/embed the codebase (OpenAI or Voyage — **open decision**, see §9) into Supabase pgvector; new `search_codebase` MCP tool alongside the existing ones. Runs locally, no AWS compute — not subject to the Free-plan 6-month window. Logs ingestion runs (`source="codebase-brain"`).
- **Dashboard** — reads `JournalStore.recent()` (this is where deferred pagination must finally be addressed) to show history/health/alerts. Hosting choice (S3+CloudFront static site, or a small API) should stay within Free-plan-eligible services per §8.

## 8. Free plan constraints

The AWS account is on the **Free plan** — never assume Paid-plan features or pricing are available. These constraints apply to every AWS-touching stage (2–6):

- **Region**: `ap-south-1` (Mumbai) everywhere — one region for everything, no cross-region resources.
- **Services allowlist**: only Free-plan-eligible services. **Never** use AWS Organizations, Control Tower, IAM Identity Center, Marketplace, Savings Plans, or Reserved Instances.
- **Secrets**: Telegram bot token and Claude API key go in **SSM Parameter Store SecureString** (standard tier), **not** Secrets Manager (Secrets Manager has no free tier; Parameter Store's standard SecureString parameters do).
- **EC2**: a single `t3.micro` instance, 8 GB `gp3` EBS volume. Note the public IPv4 address now carries a small charge (~$3.60/month) — factor that in, and **stop the instance when not actively in use** to avoid unnecessary charges.
- **CloudWatch**: stay within always-free limits — ≤10 alarms, basic (not detailed) metrics, short log retention (e.g. 7 days, not indefinite).
- **Cost Explorer API**: avoid calling it from tools — it's billed per API request even on the Free plan. If a cost-visibility tool is ever added, cache results daily rather than calling on every invocation.
- **DynamoDB**: `PAY_PER_REQUEST` billing is fine — the always-free tier comfortably covers this project's scale.
- **Claude API**: billed separately by Anthropic, not AWS — keep calls minimal (the Alert flow's diagnosis call is the main one; avoid adding speculative LLM calls elsewhere in AWS-side code).
- **Time-boxing**: the Free plan ends after 6 months. Stages 2–6 (everything that provisions real AWS infrastructure) must fit inside that window. Stages 1 (journal/MCP server) and 7 (codebase brain) run entirely locally and aren't constrained by it.

### Teardown checklist (per AWS-touching stage)

| Stage | Tear down |
|---|---|
| 2 — Docker + EC2 | Stop (or terminate) the EC2 instance when idle; release any allocated Elastic IP; delete unused ECR images. |
| 3 — Watchdog | No extra resources beyond Stage 2's instance unless a separate schedule/Lambda was added — if so, disable/delete it. |
| 4 — Security scan | No persistent AWS resources beyond CI; delete any temporary S3 scan-report bucket if not needed long-term. |
| 5 — Alerts | Delete/disable CloudWatch alarms, the SNS topic + subscriptions, the Lambda function, and the SSM parameters holding secrets if the project is paused. |
| Terraform pass | Once codified, `terraform destroy` tears down Stages 2–5's resources in one command — the fastest way to fully stop AWS charges between working sessions. |
| 6 — Deploy/rollback | Remove SSM documents/associations; no persistent compute beyond Stage 2's instance. |

## 9. Open decisions (revisit when that stage starts, not now)

1. **Embeddings provider** — OpenAI vs Voyage for Stage 7 (codebase brain). Not needed until then.
2. **Auth beyond a single static token** — revisit only if multiple callers, token rotation, or real OAuth become an actual need.
3. **`recent()` pagination** — must be addressed by Stage 8 at the latest.

## 10. Verification / acceptance criteria for Stage 1

- `pytest` passes locally, fully moto-backed — no real AWS account needed — including the new `log_journal_entry` round-trip test.
- `python -m devpilot.server` refuses to start with a clear error if `DEVPILOT_MCP_TOKEN` is unset; once set, rejects requests with no/wrong bearer token (401) and accepts the correct one.
- Manual smoke test against **DynamoDB Local** (not just `moto`) via `scripts/bootstrap_local_table.py` and `AWS_ENDPOINT_URL_DYNAMODB` succeeds — proving the store works against real DynamoDB wire protocol, not only the mock.
- `log_journal_entry` writes are visible in a subsequent `get_recent_journal_entries` call, newest first.
- Both tools are confirmed reachable via MCP Inspector and via `claude mcp add --transport http ...` from Claude Code.
- `git push -u origin main` succeeds — this becomes the first commit on `https://github.com/Kashish-0931/Devpilot-mcp`.
