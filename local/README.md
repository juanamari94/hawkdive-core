# Local Grafana verification

To connect an existing Grafana instance, use the [contact-point setup guide](../docs/grafana-contact-point.md).

This setup runs Grafana with one Hawkdive webhook integration in a contact point.
Hawkdive runs on the Windows host.
Hawkdive uses a separate verification database.
Prometheus, investigation workers, Slack, and ticket integrations are not included.

## Start

Start Docker Desktop with its Linux engine.
From the hawkdive-core directory, start the receiver:

```powershell
uv sync --locked
$env:HAWKDIVE_DB_PATH = 'local/verification.sqlite3'
$env:HAWKDIVE_WEBHOOK_TOKEN = 'local-dev-token'
uv run alembic upgrade head
uv run uvicorn hawkdive.app:app --host 0.0.0.0 --port 8000
```

The host binding allows Docker Desktop to reach the receiver through `host.docker.internal`.
In a second terminal, use the same webhook token and start Grafana:

```powershell
$env:HAWKDIVE_WEBHOOK_TOKEN = 'local-dev-token'
docker compose up -d
```

Open http://127.0.0.1:3000.
Sign in with user `admin` and password `local-grafana-password`.
These credentials are for this local setup only.
The pinned image is `grafana/grafana:13.2.3`.

## Send a test notification

Open **Alerting > Notification configuration > Contact points**.
Find the provisioned `hawkdive-local` contact point.
Select **Test** for the Hawkdive integration, then send the default test notification.
The Hawkdive integration sends the default JSON payload with bearer authentication.
Resolved notifications are enabled.

In another terminal, inspect Hawkdive:

```powershell
$headers = @{ Authorization = 'Bearer local-dev-token' }
Invoke-RestMethod http://127.0.0.1:8000/notifications -Headers $headers
Invoke-RestMethod http://127.0.0.1:8000/issues -Headers $headers
Invoke-RestMethod http://127.0.0.1:8000/investigations -Headers $headers
```

Expect a notification from source `local-grafana` and its alert evidence.
Eligible firing occurrences create pending investigations. Repeated occurrences within the window link to the existing investigation.
The test checks webhook delivery. Use the controlled rule below to verify firing and resolution.

## Verify firing and resolution

The provisioned rule uses a constant math expression. It needs no external data source.
Its label `hawkdive_verification=true` routes it to `hawkdive-local` through a local notification policy.
Other alerts retain the local default `empty` receiver. This policy file is for this test instance only.

Open `local/grafana/provisioning/alerting/verification.yaml`.
Set the rule expression to `'1 == 1'` to trigger firing.
Reload the provisioning files:

```powershell
$grafanaAuth = 'Basic ' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('admin:local-grafana-password'))
Invoke-RestMethod -Method Post http://127.0.0.1:3000/api/admin/provisioning/alerting/reload -Headers @{Authorization=$grafanaAuth}
```

Allow up to 30 seconds for evaluation and delivery.
Inspect Hawkdive:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/issues -Headers $headers
Invoke-RestMethod http://127.0.0.1:8000/investigations -Headers $headers
```

Find the alert with label `hawkdive_verification=true`.
Hawkdive should have a new firing occurrence linked to a pending investigation.
Set the rule expression back to `'1 == 0'` and reload again.
Hawkdive should receive a resolved notification with the same fingerprint and start time.
Hawkdive should mark the occurrence resolved and keep its pending investigation eligible.

The committed rule defaults to `'1 == 0'`, so startup does not deliberately trigger an alert.
Group updates wait 10 seconds. Unchanged firing notifications repeat after one hour.

On October 12, 2026, Hawkdive received firing and resolved payloads from this rule.
Hawkdive stored one occurrence through resolution. The current policy retains pending investigations after resolution.
The captured payloads are in `tests/fixtures/grafana/rule_firing_13_2_3.json` and `rule_resolved_13_2_3.json`.
Real repeats, grouping, truncation, and delivery failures still need verification.

## Stop and reset

Stop Grafana without removing its data:

```powershell
docker compose down
```

Stop Hawkdive with Ctrl+C in its terminal.
To reset this Grafana instance, run `docker compose down --volumes`.
That command deletes this Compose project's Grafana data volume.
To reset receiver data, stop the receiver and remove `local/verification.sqlite3`.
Run the migration command again before restarting it.

## References

- [Grafana Docker setup](https://grafana.com/docs/grafana/latest/setup-grafana/installation/docker/)
- [Contact-point provisioning](https://grafana.com/docs/grafana/latest/alerting/set-up/provision-alerting-resources/file-provisioning/)
- [Contact-point testing](https://grafana.com/docs/grafana/latest/alerting/configure-notifications/manage-contact-points/)
