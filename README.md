# Hawkdive Core

A Python proof of concept for receiving Grafana webhook notifications.

## Current behavior

- Accepts authenticated POST requests at /webhooks/grafana/{source}.
- Stores notifications, alert occurrences, investigations, attempts, and structured worker outputs in SQLite.
- Commits storage before returning HTTP 202.
- Groups repeated observations by source, organization, fingerprint, and normalized start time.
- Preserves each alert in a grouped notification and retains optional evidence fields.
- Resolution closes the occurrence but keeps its investigation eligible. Delayed firing cannot reopen that occurrence.
- A different start time creates a new occurrence.
- Reports truncated alert counts without inventing the missing alerts.

The source path identifies one Grafana instance. Reuse the same source for that instance.
This is occurrence tracking, not root-cause correlation across different alerts.
Changed evidence updates the occurrence without adding another investigation.
An occurrence is one continuous firing period. Repeated notifications with the same start time create no additional investigation.
A later firing period remains a separate occurrence, even when its fingerprint matches an earlier alert.
Exact duplicate payloads do not add another notification record.
The global investigation window defaults to one hour from investigation creation.
New occurrences within that window link to the existing investigation.
Pending or running investigations also receive related occurrences after the window expires.
Repeated notifications do not extend the window. Window expiry alone does not start another investigation.
Worker launch is explicit through the API. The LangGraph agent is opt-in; no automatic dispatch loop runs yet.

## Setup

Requires Python 3.13 and uv. Docker and external accounts are not required.

From the repository directory:

```powershell
uv sync --locked
uv run alembic upgrade head
uv run pytest -q
uv run uvicorn hawkdive.app:app --host 127.0.0.1 --port 8000
```

uv manages the .venv directory and dependencies. Commit uv.lock with dependency changes.

## Local Grafana verification

See [local/README.md](local/README.md) for the minimal Docker Compose setup and test notification steps.
Grafana 13.2.3 delivered a real contact-point test notification to Hawkdive on October 12, 2026.
Hawkdive stored its payload, alert evidence, and one pending job.
The captured fixture is `tests/fixtures/grafana/contact_point_test_13_2_3.json`.
A controlled rule delivered firing and resolved notifications to Hawkdive.
Hawkdive tracked one occurrence through firing and resolution.
The current implementation retains pending investigations after resolution.
Real repeated notifications, grouping, truncation, and delivery failures remain to be verified.

## Database setup and migrations

SQLAlchemy maps notification, occurrence, investigation, attempt, and output records to Python objects.
The receiver uses async sessions with aiosqlite. The driver manages background threads for SQLite operations.
Each notification uses one transaction. A SQLite writer lock prevents concurrent deliveries from creating duplicate work.

Alembic manages schema versions. Run `uv run alembic upgrade head` before starting the receiver.
Set HAWKDIVE_DB_PATH before both commands when using a custom database path.
Startup checks the database revision and stops if migrations are missing or outdated.
The migration command runs separately and uses a synchronous SQLAlchemy engine.

The initial migration creates a new database, including its parent directory.
The initial schema uses `grafana_org_id` for the stored organization ID.
The inspection endpoints return `grafana_org_id`. Incoming Grafana payloads still use `orgId`.
This integer identifies a Grafana organization within its source instance.

Revision `0002` replaces the old jobs table with investigations and attempts.
It preserves notifications and occurrences and groups legacy jobs by alert signature.
Legacy jobs have no receipt timestamps, so their one-hour window starts at migration time.
Previously cancelled jobs become pending investigations, consistent with the current resolution policy.

To change the schema, update `hawkdive/tables.py` and generate a migration:

```powershell
uv run alembic revision --autogenerate -m "Describe the schema change"
```

Review the generated migration before running it. SQLite migrations use Alembic batch mode when tables need rebuilding.
Downgrading to `base` removes all application tables and their data.

## Replay sample alerts

In a second terminal, from the repository directory:

```powershell
uv run python scripts/send_alert.py tests/fixtures/grafana/firing.json --repeat 2
uv run python scripts/send_alert.py tests/fixtures/grafana/resolved.json
uv run python scripts/send_alert.py tests/fixtures/grafana/recurring.json
```

The sender prints the HTTP response. The second identical firing notification reports duplicate=true.
Use grouped.json to send two alerts together. Use minimal.json to omit optional evidence fields.

## Inspect state

The local API provides GET /issues, /notifications, /investigations, and /investigations/{id}.
GET /issues/{id} resolves an investigation's trigger reference.
GET /jobs remains a compatibility view of investigations with lowercase status values. Its IDs are now investigation UUIDs.
All data endpoints require an Authorization header.

```powershell
$headers = @{ Authorization = 'Bearer local-dev-token' }
Invoke-RestMethod http://127.0.0.1:8000/issues -Headers $headers
Invoke-RestMethod http://127.0.0.1:8000/investigations -Headers $headers
```

The /docs page describes the API.
Investigation responses use Pydantic models with UUID identities, typed triggers and outputs, and timezone-aware timestamps.
UUIDs are strings in JSON and text in SQLite; application records expose UUID values.

## Worker wrapper

See [local/worker-wrapper.md](local/worker-wrapper.md) for process configuration, dispatch, and the worker protocol.
For the OpenRouter/Grafana Cloud agent and Docker sandbox, see [local/agent.md](local/agent.md) and [ADR 0002](adrs/0002-langgraph-agent-and-shell-sandbox.md).
The wrapper is independent of Grafana and LangGraph. Grafana is the first intake adapter.
The adapter supplies a signature containing integration, source, organization scope, and alert fingerprint.

Each investigation can have sequential attempts, with at most one active attempt.
A database claim also prevents workers for the same alert signature from overlapping across application instances.
Worker outputs are saved as they arrive and identify their producing attempt.
The orchestrator supplies attempt ownership; worker output contains only a UUID, an output kind, and typed content.
Evidence includes a text explanation in `reasoning`. Findings and outcomes reference supporting output UUIDs.
Findings reference saved observations; outcomes reference saved findings from the same attempt.
An exit code of zero completes an investigation only when a valid outcome was saved.
Failures retain their output history. The authenticated retry endpoint creates another attempt for a failed investigation.

On graceful shutdown, the application stops its local workers before releasing their claims and records interrupted attempts as failed.
After a crash, unresolved claims require manual review. Startup reconciliation remains deferred.

## Configuration

- HAWKDIVE_DB_PATH: SQLite file path; default hawkdive.sqlite3.
- HAWKDIVE_WEBHOOK_TOKEN: bearer token; default local-dev-token.
- HAWKDIVE_INVESTIGATION_WINDOW_SECONDS: positive global investigation window; default 3600. Changes apply to new investigations.
- HAWKDIVE_WORKER_COMMAND: JSON array of executable and arguments; unset by default. Dispatch returns HTTP 409 when unset.
- HAWKDIVE_AGENT_ENABLED: set `true` to use the built-in LangGraph worker when no custom command is configured.

When neither the built-in agent nor a custom worker command is configured, the application supplies `NullBackend` to the dispatcher.
It reports disabled execution before an attempt is created. Intake and investigation storage stay available.

The default token is for local development. Set your own token before exposing the receiver.
Set the same token for the sender and receiver. An empty token is rejected.
The proof of concept uses one shared token; it does not provide tenant access control.

## Tests and scope

Run `uv run ruff check .` and `uv run pytest -q` before submitting changes.
Ruff checks import order, requires module-level imports, and rejects print statements outside tests.
Diagnostics use logging. Worker stdout contains only JSON protocol records.

Tests exercise observable application behavior through HTTP. They use a temporary database per test.
Migration tests cover initial setup, repeated upgrades, and startup checks for missing migrations.
They do not assert logs or test third-party library internals.
The initial tests failed against the empty app before implementation.

The original fixtures are synthetic and follow Grafana's documented default payload.
The contact-point test fixture was captured from local Grafana 13.2.3.
It includes null `values`, `valueString`, empty rule links, and timestamps with nanosecond precision.
The `rule_firing_13_2_3.json` and `rule_resolved_13_2_3.json` fixtures capture a real rule transition.
They preserve the rule UID, expression values, labels, timestamps, fingerprint, and Grafana links.
Authentication supports bearer tokens only. Custom payload templates and HMAC are deferred.
Duplicate notifications are safe to retry. Investigations, attempts, and outputs survive restarts.
Tests use a minimal process worker that produces fixed output. It does not investigate alerts.
The LangGraph worker implements separate Grafana Cloud MCP and Docker shell paths, plus structured record emission.
Live model/Grafana authentication and Docker behavior still require environment-specific verification.
Memory lookup and local Slack/ticket mocks are later tasks.
Automatic retries, startup reconciliation, OAuth sign-in/refresh, per-signature window overrides, and active cancellation APIs remain deferred.

Reference: https://grafana.com/docs/grafana/latest/alerting/configure-notifications/manage-contact-points/integrations/webhook-notifier/
