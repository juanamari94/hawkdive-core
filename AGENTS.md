# Hawkdive Core working context

## Scope

- This is a Python proof of concept.
- The first milestone is Grafana webhook intake and persistent occurrence tracking.
- Use FastAPI with asynchronous I/O boundaries and SQLite for local storage.
- Investigation records, sequential attempts, structured outputs, and a local process wrapper are implemented.
- Worker launch is explicit through authenticated API operations. The LangGraph agent is opt-in through HAWKDIVE_AGENT_ENABLED.
- The agent uses OpenRouter GLM 5.3, Grafana's official local MCP server, and separate GrafanaMcpToolNode and ShellNode paths.
- Use one Docker sandbox per attempt. Never pass model or MCP credentials into its environment.
- Slack, Jira, and Trello interfaces must remain local mocks when added.
- Follow TASKS.md for subsequent work. Do not add a frontend or telemetry stack before its task begins.

## Development

- Use uv for Python environments and dependency management.
- Use the karpathy-guidelines skill for code work.
- Use TDD: write a short behavior test, observe the expected failure, then implement the change.
- Test only behavior introduced or changed by the task.
- Do not assert logs or test third-party library code.
- Keep tests brief and focused. Prefer HTTP-level checks for receiver behavior.
- Run uv run pytest -q after code changes.
- Run uv run ruff check . after Python changes.
- Keep imports at module level and sorted. Do not put imports inside functions.
- Use logging for diagnostics. Reserve worker stdout for JSON protocol records.
- Print statements are permitted in tests and test helpers.
- Keep README.md and TASKS.md accurate for future sessions.

## Current implementation

- POST /webhooks/grafana/{source} accepts Grafana's default payload with bearer authentication.
- The same bearer token protects state inspection endpoints.
- Alert identity is source + orgId + fingerprint + startsAt, normalized to UTC.
- Preserve original notification payloads and alert evidence.
- Commit notifications, occurrence updates, investigation eligibility, and occurrence links in one transaction before acknowledgement.
- Resolution is terminal for an occurrence. Pending investigations stay eligible after resolution.
- Use a global one-hour investigation window, configurable with HAWKDIVE_INVESTIGATION_WINDOW_SECONDS.
- New occurrences link to an existing investigation while its window is open or it is PENDING/RUNNING.
- Allow at most one active attempt per investigation and one active worker per mapped alert signature.
- A failed investigation can be explicitly re-triggered. Never overwrite prior attempt outputs.
- An outcome references saved findings, which reference saved observations from the same attempt.
- Startup reconciliation, OAuth sign-in/refresh, automatic dispatch, and memory lookup remain deferred.
- Run the local MCP server with a Grafana service-account token. Authenticate workers with a separate MCP caller token.
- Expose all advertised MCP tools. Use Grafana permissions to control access; configure read-only access for investigation.
- Keep execution configuration separate from investigation records and worker command-line arguments.
- Live provider/Docker checks need credentials and a running engine. Standard tests use a scripted model and MCP test server.
- New evidence does not automatically queue another investigation.
- See README.md for setup, replay commands, and current limitations.
