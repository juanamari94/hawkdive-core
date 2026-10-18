# Local investigation agent

The worker uses LangGraph, OpenRouter GLM 5.3, Grafana's official local MCP server, and one Docker shell sandbox per attempt.
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
| `HAWKDIVE_GRAFANA_ACCESS_TOKEN` | Grafana service-account token for the stack. |
| `HAWKDIVE_GRAFANA_MCP_TOKEN` | A separate random secret shared by Hawkdive and the local MCP server. |
| `HAWKDIVE_WEBHOOK_TOKEN` | A separate secret shared by Hawkdive and the Grafana webhook integration. |

Store these values in an untracked `.env` file in the repository root.
Run application commands with `uv run --env-file .env` to load that file.
Docker Compose reads `.env` for its variable substitutions.

The service-account token authenticates the MCP server to Grafana.
The separate MCP token authenticates Hawkdive to the local server.
Authorize read access for the intended Cloud stack before configuring it.
The agent receives all tools advertised by the MCP server, including Loki tools.
Hawkdive does not filter tool names. Grafana permissions determine which operations succeed.
Use read-only permissions for the initial investigation agent.
Hosted Cloud MCP and its OAuth flow are not used by this setup.
Do not paste credentials into alert payloads or commit them to the repository.

Remove `HAWKDIVE_WORKER_COMMAND` when using the built-in agent entry point.
A custom command takes precedence when configured; it is primarily useful for wrapper tests.

Optional settings:

| Variable | Default |
| --- | --- |
| `HAWKDIVE_GRAFANA_MCP_URL` | `http://127.0.0.1:8001/mcp` |
| `HAWKDIVE_AGENT_MODEL` | `z-ai/glm-5.3` |
| `HAWKDIVE_AGENT_REASONING_EFFORT` | `max`; GLM 5.3 also supports `low` and `high`. |
| `HAWKDIVE_SANDBOX_IMAGE` | `hawkdive-sandbox:local` |
| `HAWKDIVE_AGENT_MAX_MODEL_CALLS` | `20` |
| `HAWKDIVE_AGENT_TIMEOUT_SECONDS` | `300` |
| `HAWKDIVE_SHELL_TIMEOUT_SECONDS` | `30` |

These settings apply to newly launched worker processes.
The global investigation window remains independently configured through `HAWKDIVE_INVESTIGATION_WINDOW_SECONDS`.

## Run and dispatch

Start the MCP server from the repository root:

```powershell
docker compose --env-file .env -f compose.mcp.yaml up -d
docker compose -f compose.mcp.yaml ps
```

This separate Compose project runs `grafana/mcp-grafana:2.0.2` against your Cloud stack.
It does not start the local Grafana verification instance.
Only localhost port 8001 is published. Hawkdive remains on port 8000.
All tools advertised by the server are available; the service-account permissions determine which operations succeed.
The server uses its default tool categories, including Loki and Prometheus.
Changing credentials requires recreating the server with the same `up -d` command and restarting Hawkdive.
Do not print `docker compose config` output: its resolved environment contains credentials.

Use a separate database for agent verification:

```powershell
$env:HAWKDIVE_DB_PATH = 'local/agent.sqlite3'
uv run --env-file .env alembic upgrade head
uv run --env-file .env uvicorn hawkdive.app:app --host 127.0.0.1 --port 8000
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

Stop the local MCP server with `docker compose -f compose.mcp.yaml down`.

## References

- [Official MCP Docker setup](https://grafana.com/docs/grafana/latest/developer-resources/mcp/set-up/install-with-docker/)
- [Service-account authentication](https://grafana.com/docs/grafana/latest/developer-resources/mcp/configure/authentication/)
- [MCP caller authentication and transport settings](https://grafana.com/docs/grafana/latest/developer-resources/mcp/configure/command-line-flags/)
