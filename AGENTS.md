# Hawkdive Core working context

## Scope

- This is a Python proof of concept.
- The first milestone is Grafana webhook intake and persistent occurrence tracking.
- Use FastAPI with asynchronous I/O boundaries and SQLite for local storage.
- Investigation records, sequential attempts, structured outputs, and a local process wrapper are implemented.
- Worker launch is explicit through authenticated API operations. The LangGraph agent is not implemented.
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
- Startup reconciliation and the agent implementation remain deferred.
- New evidence does not automatically queue another investigation.
- See README.md for setup, replay commands, and current limitations.
