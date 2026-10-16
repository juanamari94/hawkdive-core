# Local worker wrapper

The application dispatches a separate process and stores its structured outputs.
The opt-in LangGraph agent is documented in [agent.md](agent.md).
This guide uses the deterministic test process to verify the wrapper without model or Grafana credentials.
The worker under `tests/fixtures/worker.py` exists only to verify the wrapper contract.
Its results are fixed test data, not real investigation findings.

## Configure and start

Run these commands from hawkdive-core in PowerShell:

```powershell
uv sync --locked
$env:HAWKDIVE_DB_PATH = 'local/wrapper.sqlite3'
$env:HAWKDIVE_WEBHOOK_TOKEN = 'local-dev-token'
$env:HAWKDIVE_INVESTIGATION_WINDOW_SECONDS = '3600'
$workerPython = (Resolve-Path .venv/Scripts/python.exe).Path
$env:HAWKDIVE_WORKER_COMMAND = ConvertTo-Json -InputObject @($workerPython, 'tests/fixtures/worker.py', 'success') -Compress
uv run alembic upgrade head
uv run uvicorn hawkdive.app:app --host 127.0.0.1 --port 8000
```

Use a free port or stop another local Hawkdive process first.
Migrations must finish before application startup.
The command is an argument array. The wrapper does not use a shell.
No worker starts until an authenticated dispatch request is accepted.
Without a configured command, `NullBackend` reports disabled execution and dispatch returns HTTP 409 without creating an attempt.

## Dispatch and inspect

In another terminal, send an alert and select its investigation:

```powershell
uv run python scripts/send_alert.py tests/fixtures/grafana/firing.json
$headers = @{ Authorization = 'Bearer local-dev-token' }
$records = @(Invoke-RestMethod http://127.0.0.1:8000/investigations -Headers $headers)
$investigationId = $records[0].id
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/investigations/$investigationId/dispatch" -Headers $headers
Invoke-RestMethod "http://127.0.0.1:8000/investigations/$investigationId" -Headers $headers
```

Dispatch returns HTTP 202 with the new attempt ID. Its initial state is `PENDING`.
Inspect again after the process finishes to see `COMPLETED`, the attempt, and the evidence chain.
While a process runs, its saved intermediate outputs are visible through the same endpoint.
Normal logs belong on standard error, not standard output.

The investigation states are `PENDING`, `RUNNING`, `COMPLETED`, and `FAILED`.
Each attempt retains its own state and execution reference.
`COMPLETED` and `FAILED` are terminal for an attempt.
An inconclusive but valid outcome can still be `COMPLETED`.

To test failure, restart the application with worker mode `failure`, `missing`, or `invalid` instead of `success`.
These modes exercise a nonzero exit, missing outcome, and invalid evidence reference.
After a failed investigation, configure mode `success` and restart the application.
Then explicitly re-trigger it:

```powershell
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/investigations/$investigationId/retry" -Headers $headers
```

Retry returns HTTP 202 with a new attempt ID. Earlier attempts and outputs remain saved.
Completed or active investigations cannot be retried. Conflicting dispatch requests return HTTP 409.
The API does not queue a conflicting dispatch request; the caller can submit it again later.
Unknown investigation IDs return HTTP 404 when a worker backend is configured.

## Worker input

The process reads one UTF-8 JSON object from standard input, followed by a newline and end of input.
It contains `investigation_id`, `attempt_id`, and `trigger`.
The trigger includes the integration, original occurrence ID, reference, and original alert evidence.
It is an `AlertTrigger` record. Only its `alert` field keeps the original integration payload as a dictionary.
Investigation and attempt IDs are parsed as UUIDs.
The reference identifies the stored occurrence. Worker inputs are independent of LangGraph.

## Worker output

The process writes one UTF-8 JSON object per line to standard output.
Each object contains:

| Field | Meaning |
| --- | --- |
| id | Output UUID, unique within the attempt. |
| kind | `EVIDENCE`, `OBSERVATION`, `FINDING`, or `OUTCOME`. |
| content | An `Evidence`, `Observation`, `Finding`, or `Outcome` record matching the kind. |

The output kind uses `OutputKind`, a Python `StrEnum`.
The process output does not include investigation or attempt IDs.
The orchestrator associates each record with the execution context that owns the process stream.
The stored record still includes its attempt ID for history and reference validation.

| Kind | Content |
| --- | --- |
| EVIDENCE | `source`, `query`, timezone-aware `starts_at` and `ends_at`, text `reasoning`, and `source_url`. |
| OBSERVATION | `summary`, optional `evidence_ids`, and optional `memory_references`. |
| FINDING | `summary` and at least one supporting `observation_id` in `observation_ids`. |
| OUTCOME | `conclusion`, at least one supporting `finding_id` in `finding_ids`, optional `uncertainty`, and optional `next_steps`. |

`reasoning` is a concise explanation of the evidence, tied to its query, time range, and source.
It is explicit report text, not a request to store private model reasoning.
`uncertainty` records evidence gaps and limits of the conclusion.
`next_steps` lists suggested follow-up checks or actions. The wrapper does not execute them.

Reference IDs are UUIDs. UUIDs remain stored as text in SQLite.
The generated output schemas omit length constraints. Application validators still reject blank required text and unsupported conclusions.

Evidence references must identify saved evidence from the current attempt.
Finding references must identify saved observations from the current attempt.
Outcome references must identify saved findings from the current attempt.
Emit supporting records before records that reference them.
Output IDs can repeat across attempts. They cannot repeat within an attempt.
Only one outcome is accepted per attempt.
Unknown fields, including worker-supplied execution IDs, are rejected.
The orchestrator rejects output from inactive or finished execution contexts.
Memory references remain context; memory lookup and reference resolution are not implemented yet.

Each output line must fit the local backend's 64 KiB stream limit.
Malformed or invalid output stops the worker and fails the attempt.
Exit code zero without a valid saved outcome also fails the attempt.
A nonzero exit fails the attempt even when the worker saved an outcome.

## Investigation window

The default window is one hour from investigation creation, measured using application time.
Configure `HAWKDIVE_INVESTIGATION_WINDOW_SECONDS` before starting the application.
Each investigation saves its window end time. Changing configuration does not alter existing windows.
New firing periods remain separate occurrences but reference the same investigation within its window.
Pending or running investigations receive new related occurrences even after the window expires.
Linking another occurrence does not change a completed outcome or automatically retry a failed attempt.
Repeated notifications do not extend the window or start investigations when the window expires.
A new occurrence after window expiry can create a new investigation when no pending or running investigation exists.
Resolution closes the occurrence and keeps its investigation eligible.

## Limits

The application supervises local workers only while it runs.
Graceful shutdown stops its workers, confirms exit, and records interrupted attempts as failed.
A crash can leave an active claim. Inspect the worker before manually repairing that state.
Do not clear a claim while its worker may still be running.
Startup reconciliation, automatic retries, automatic dispatch scheduling, and other execution backends remain deferred.
