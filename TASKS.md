# Hawkdive Core: initial tasks

## First milestone: receive and process Grafana webhooks

Send documentation-derived Grafana payloads to the real Hawkdive receiver. Validate input, preserve individual alerts, store issue state, and handle repeated notifications and resolution. No Grafana instance, telemetry backend, model, Slack account, or ticket integration is required.

## Later milestone: investigate and simulate output

Verify the webhook contract against a minimal local Grafana instance. Add telemetry collection, investigation, and local simulations of Slack output and ticket actions in separate steps.

## HD-000: define webhook fixtures and an alert sender

Status: implemented; covered by local behavior tests. Local Grafana test and rule-transition fixtures are also captured.

Model Grafana's default webhook payload from the official documentation. Prepare JSON fixtures and a simple sender that replays them against the real receiver.

Acceptance:
- Cover firing, repeated, grouped, resolved, and recurring alerts, plus malformed input.
- Include optional or missing fields and payloads reporting truncated alerts.
- Keep request authentication configurable for local testing.
- Mark fixtures as documentation-derived until verified against local Grafana.
- Do not build telemetry, Slack, ticket, or model mocks in this task. Add small mocks when their respective features begin.

## Proposed scope

- Grafana-managed alerts are the first input.
- Prometheus metrics are the first investigation source. Add Loki logs after the initial metrics workflow works.
- Use the open-source Grafana MCP server for evidence access. Hawkdive manages the investigation and output.
- Keep existing alert delivery active. Hawkdive receives a copy.
- Mimic Slack messages, threads, and updates with a local mock. Do not connect to a real workspace.
- Simulate automatic ticket creation and updates with a local mock. Live Slack, Jira, and Trello integrations are deferred.
- No production changes, forecasting, or full system mapping in this milestone.

## HD-001: prepare minimal local Grafana for contract verification

Status: implemented. Contact-point delivery and controlled firing and resolution were verified on October 12, 2026.

Dependency: HD-003. This is later verification, not a prerequisite for receiver development.

Compose pins Grafana 13.2.3 and provisions a bearer-authenticated webhook contact point.
Grafana runs in Docker. Hawkdive runs on the host with `local/verification.sqlite3`.
The contact-point test stored a notification, alert evidence, and one pending job.
The local contact point contains only the Hawkdive webhook.
A controlled math rule delivered firing and resolved notifications to Hawkdive.
The current resolution policy keeps its investigation eligible after resolution.
See local/README.md for start, test, stop, and reset steps.

Use the official Grafana Docker Compose example as the base, with a pinned image version. Run Grafana and connect its webhook contact point to Hawkdive. Use contact-point test notifications first. Add a controlled alert source only when testing real firing and resolution transitions. Add Prometheus, a sample service, and MCP later for telemetry investigation.

Acceptance:
- Document setup and reset steps.
- A Grafana contact-point test notification reaches Hawkdive.
- A later controlled alert verifies firing and resolution transitions.
- Local checks need no external accounts. Model access is a separate optional integration check; Slack and ticket outputs remain mocked.

## HD-002: verify the Grafana notification contract

Status: real contact-point test, firing, and resolved payloads captured from Grafana 13.2.3.
Rule UID, values, occurrence identity, and delivery to Hawkdive were verified.
Real repeats, grouping, truncation, and delivery failure behavior remain planned.
Dependency: HD-001

Configure a webhook contact point and notification routing. Capture real firing, repeated, grouped, and resolved payloads. Confirm authentication, delivery failure behavior, repeat settings, and payload truncation for the selected version.

Acceptance:
- Save sanitized payload fixtures.
- Document labels, annotations, timestamps, fingerprints, values, and available links.
- Confirm that resolved notifications are enabled.
- Document how Grafana reaches the receiver in the local environment.

## HD-003: receive alerts and preserve issue state

Status: implemented; covered by local behavior tests. Investigations replace the per-occurrence job queue.
Dependency: HD-000. Local integration verification follows in HD-001 and HD-002.

Validate requests, persist accepted events, and acknowledge receipt before investigation. Handle each alert in a grouped notification. Track alert identity, occurrence, and status. Scope identity to the configured source; distinguish a repeated notification from a later recurrence.

Acceptance:
- Repeated delivery does not create duplicate work.
- A grouped notification preserves its individual alerts.
- Resolved events update the correct occurrence and retain pending investigations.
- Restarting Hawkdive preserves accepted work and issue state.
- Invalid authentication and malformed payloads receive appropriate errors.

## Database foundation: SQLAlchemy and Alembic

Status: implemented. SQLAlchemy async sessions replace direct sqlite3 queries.
Alembic manages initial setup and schema versions. Run migrations before receiver startup.
The initial migration creates the schema with `grafana_org_id` for the stored organization ID.
Local tests cover migrations and the existing receiver behavior.

## Investigation wrapper: records and local process dispatch

Status: implemented on October 14, 2026. See [ADR 0001](adrs/0001-investigation-worker-wrapper.md).

- Store investigations, related occurrences, sequential attempts, and structured outputs.
- Use a global one-hour investigation window. Per-signature overrides are deferred.
- Keep pending investigations eligible after alert resolution.
- Dispatch a configured process through authenticated API operations.
- Prevent overlapping attempts and workers for the same alert signature through atomic database claims.
- Save intermediate outputs and validate outcome, finding, and observation references.
- Use typed worker content and UUID references. The orchestrator assigns execution ownership to saved outputs.
- Allow explicit re-triggering of failed investigations while preserving attempt history.
- Verify the wrapper with a minimal test process. No agent or model is included.

Startup reconciliation, automatic dispatch scheduling, automatic retries, and distributed execution backends remain deferred.

## HD-004: investigate through Grafana MCP

Status: planned
Dependencies: HD-001, HD-003

Implemented worker wrapper and investigation contracts: [ADR 0001](adrs/0001-investigation-worker-wrapper.md).
Reconciliation and the agent implementation remain deferred.

Keep investigation records separate from alert occurrences.
One occurrence covers a continuous firing period. Repeated notifications for that period do not create another job.
A new start time creates a new occurrence; do not discard it as a duplicate.
Investigation creation is separate from occurrence storage.
Use a configurable window per alert signature to prevent repeated investigations for a flaky alert.
Support sequential attempts for an investigation, with at most one active attempt and worker.
Use earlier investigations as history for recurring alerts.
Grafana is the first integration; the wrapper uses mapped alert signatures for other sources too.

Connect the open-source MCP server with read permissions and an explicit tool allowlist. First prove a relevant metric query without a model. Then add a bounded agent that collects evidence and tests hypotheses.

Acceptance:
- Retrieve relevant metrics for the alert time window.
- Record evidence queries, timestamps, and source links.
- Separate observations, hypotheses, and next steps.
- Limit investigation time, tool calls, query ranges, and model usage.
- Missing evidence produces an inconclusive result.
- Telemetry content cannot authorize extra tools or actions.
- Sample failures have expected evidence and useful next steps.

## HD-005: mimic Slack results and useful updates

Status: planned
Dependencies: HD-003, HD-004

Keep a persistent investigation record in Hawkdive. Send summaries and updates to a local mock that mimics message creation, thread replies, and message updates. Record requests and return simulated message and thread identifiers. Do not implement live Slack delivery or authentication.

Acceptance:
- Each issue has one simulated active investigation thread.
- Repeated alerts do not create repeated messages.
- Final results show evidence, uncertainty, and next steps.
- Resolution updates the simulated thread without claiming that the underlying defect is fixed.
- Simulated delivery failures can be retried without losing the investigation.
- All output remains local. No workspace, credentials, or real messages are required.

## HD-006: mimic ticket creation and updates

Status: planned
Dependency: HD-005

Add team-configured rules for automatic ticket creation and a simulated explicit request from Slack. Use a local mock for ticket creation, lookup, and updates. Record requests and return simulated ticket identifiers. Keep ticket actions separate from the investigation agent's telemetry tools. Do not implement live Jira or Trello delivery or authentication.

Acceptance:
- A qualifying issue creates one simulated ticket.
- Repeated events update or link to the existing simulated ticket.
- Tickets contain evidence, impact when known, uncertainty, and next steps.
- Simulate creation requests whose outcome is unknown and verify duplicate prevention.
- All output remains local. No external project, board, or credentials are required.

## Sources

- Grafana webhook notifier: https://grafana.com/docs/grafana/latest/alerting/configure-notifications/manage-contact-points/integrations/webhook-notifier/
- Grafana MCP server: https://grafana.com/docs/grafana/latest/developer-resources/mcp/
- Minimal Grafana Compose setup: https://grafana.com/docs/grafana/latest/setup-grafana/installation/docker/#run-grafana-via-docker-compose
