# Local investigation agent

The worker uses LangGraph, OpenRouter GLM 5.3, Grafana Cloud MCP, and one Docker shell sandbox per attempt.
It remains opt-in. Alert intake does not automatically dispatch investigations.
The architecture is recorded in [ADR 0002](../adrs/0002-langgraph-agent-and-shell-sandbox.md).

## Prepare

Start Docker Desktop and confirm its Linux engine is running:

```powershell
docker info
uv sync --locked
docker build -t hawkdive-sandbox:local local/agent-sandbox
```

The sandbox image contains Bash, Python, and Git. It does not contain model or Grafana credentials.
Its root filesystem is read-only during execution. The attempt's workspace remains writable.

## Configure

Set these application environment variables through your local secret-management mechanism:

| Variable | Value |
| --- | --- |
| `HAWKDIVE_AGENT_ENABLED` | `true` |
| `OPENROUTER_API_KEY` | OpenRouter API key. |
| `HAWKDIVE_GRAFANA_URL` | HTTPS root URL of the Grafana Cloud stack, such as `https://example.grafana.net`. |
| `HAWKDIVE_GRAFANA_ACCESS_TOKEN` | Existing Grafana Cloud MCP OAuth access token. |

The MCP token is an OAuth access token, not a Grafana service-account token.
Authorize read access for the intended Cloud stack before configuring it.
OAuth sign-in and refresh are not implemented here. Replace expired tokens in application configuration and restart the application.
Do not paste credentials into alert payloads or commit them to the repository.

Remove `HAWKDIVE_WORKER_COMMAND` when using the built-in agent entry point.
A custom command takes precedence when configured; it is primarily useful for wrapper tests.

Optional settings:

| Variable | Default |
| --- | --- |
| `HAWKDIVE_AGENT_MODEL` | `z-ai/glm-5.3` |
| `HAWKDIVE_AGENT_REASONING_EFFORT` | `max`; GLM 5.3 also supports `low` and `high`. |
| `HAWKDIVE_SANDBOX_IMAGE` | `hawkdive-sandbox:local` |
| `HAWKDIVE_AGENT_MAX_MODEL_CALLS` | `20` |
| `HAWKDIVE_AGENT_TIMEOUT_SECONDS` | `300` |
| `HAWKDIVE_SHELL_TIMEOUT_SECONDS` | `30` |

These settings apply to newly launched worker processes.
The global investigation window remains independently configured through `HAWKDIVE_INVESTIGATION_WINDOW_SECONDS`.

## Run and dispatch

Use a separate database for agent verification:

```powershell
$env:HAWKDIVE_DB_PATH = 'local/agent.sqlite3'
uv run alembic upgrade head
uv run uvicorn hawkdive.app:app --host 127.0.0.1 --port 8000
```

Send an alert from the intended Grafana Cloud stack or replay a fixture with real service labels and timestamps.
Synthetic sample alerts can exercise intake but may have no matching telemetry in your stack.

Use an authenticated request to dispatch the investigation:

```powershell
$headers = @{ Authorization = 'Bearer local-dev-token' }
$records = @(Invoke-RestMethod http://127.0.0.1:8000/investigations -Headers $headers)
$investigationId = $records[0].id
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/investigations/$investigationId/dispatch" -Headers $headers
Invoke-RestMethod "http://127.0.0.1:8000/investigations/$investigationId" -Headers $headers
```

Use your configured webhook token if it differs from the local default.
The response exposes intermediate records and attempt state.
`COMPLETED` requires a valid outcome with supporting findings and observations.
Credential failure, missing outcome, execution limits, or nonzero exit can fail an attempt.

## Scratchpads and source code

Shell calls use `/workspace`. Files survive later calls in the same attempt.
A new call starts a new Bash shell; use files to preserve state instead of shell variables.
The sandbox can clone public repositories and inspect an exact commit.
It does not receive private repository credentials.

Container names use `hawkdive-agent-<attempt UUID without hyphens>`.
Workspace volumes use `hawkdive-work-<attempt UUID without hyphens>`.
The container is removed after execution, but the volume is retained for inspection.
Volume retention and selected artifact export are not automated.
Remove a specific retained volume only after confirming it is no longer needed.

If the supervisor cannot confirm container removal, the active claim remains for manual review.
Do not clear a claim while its worker or sandbox may still be running.

## Verify

The normal test suite uses a scripted model and MCP test server. It makes no paid model calls or Grafana Cloud requests.

```powershell
uv run pytest -q
```

After building the image, run the real sandbox check explicitly:

```powershell
$env:HAWKDIVE_TEST_DOCKER = '1'
uv run pytest -q tests/test_agent_shell.py
Remove-Item Env:HAWKDIVE_TEST_DOCKER
```

That test checks persistent files, separate attempt workspaces, and absence of application credentials inside the sandbox.
Successful Docker tests still do not establish working OpenRouter or Grafana Cloud authentication.
