# Connect an existing Grafana instance to Hawkdive

Last checked: 2026-10-17.

Add a Hawkdive webhook integration to the contact point that already receives your alerts.
Grafana sends notifications to each integration in that contact point.
Your existing Slack, email, or other integration continues to receive notifications.

## Prepare the receiver

Follow the [application setup](../README.md#setup) to install dependencies, run migrations, and start Hawkdive.
Set `HAWKDIVE_WEBHOOK_TOKEN` through your environment or secret manager before starting the application.
Use a private token instead of the local development default.
The same token protects the receiver and its inspection API.

Make the receiver reachable from the Grafana server through an HTTPS endpoint.
For example, use `https://hawkdive.example.com/webhooks/grafana/team-production`.
The hostname is a placeholder; replace it with your receiver address.
Configure the reverse proxy to forward the request body and Authorization header to Hawkdive.

The final path segment, `team-production`, identifies the Grafana instance.
Keep this source name stable and use a different name for each Grafana instance.
It is an identity label, not a credential or tenant access boundary.

Grafana Cloud cannot reach a receiver through your computer's `localhost` address.
The `host.docker.internal` address in the [local setup](../local/README.md) applies only to local Docker verification.
Grafana Cloud needs a receiver address reachable from its delivery service.

## Add the webhook integration

1. Open **Alerting > Notification configuration > Contact points** in Grafana.
2. Select **Grafana** in the Alertmanager selector, if shown.
3. Edit the contact point used by the alerts you want Hawkdive to receive.
4. Select **Add contact point integration**.
5. Select **Webhook** as the integration type.
6. Enter the receiver URL in the settings below.
7. Save the contact point.

Menu labels can differ between Grafana versions.
If the contact point is provisioned and cannot be edited, update its provisioning source instead.
Keep its other integrations when making that update.

| Setting | Value |
| --- | --- |
| URL | `https://hawkdive.example.com/webhooks/grafana/team-production` |
| HTTP Method | `POST` |
| Authentication Header Scheme | `Bearer` |
| Authentication Header Credentials | The value of `HAWKDIVE_WEBHOOK_TOKEN`, without the `Bearer ` prefix. |
| Basic Authentication | Leave unset. |
| Disable resolved message | Leave unchecked. |
| Custom Payload | Leave unset; use Grafana's default JSON payload. |
| Max Alerts | `0` to include all alerts in a notification. |

Do not put the token in the URL.
Hawkdive currently validates bearer authentication; it does not validate Grafana HMAC signatures.
The webhook token is separate from the service-account token and local MCP caller token used by the agent setup.

See Grafana's [webhook settings](https://grafana.com/docs/grafana/latest/alerting/configure-notifications/manage-contact-points/integrations/webhook-notifier/).

## Check notification routing

Adding an integration to an already selected contact point requires no new notification policy.
It receives the alerts routed to that contact point, subject to Grafana's notification settings.

For rule-level routing, confirm that the rule selects this contact point in its notification settings.
For policy routing, confirm that the matching notification policy selects this contact point.
Check this in the same Alertmanager as the contact point.

If you create a separate contact point, select it in a rule or notification policy before expecting real alerts.
Creating it alone does not route alerts to it.
Do not replace your existing routing tree with the local verification policy.

See Grafana's [contact-point and routing instructions](https://grafana.com/docs/grafana/latest/alerting/configure-notifications/manage-contact-points/).

## Verify delivery

Send the default test notification from the Hawkdive webhook integration's **Test** action.
Check which integrations the test dialog targets before sending it.
Hawkdive returns HTTP `202` after storing an accepted notification.

Use the authenticated inspection endpoints listed in [Inspect state](../README.md#inspect-state).
Check `/notifications` for the configured source and `/issues` for its alert occurrence.
Check `/investigations` for the pending investigation or the existing investigation linked to that occurrence.
Repeated tests can link to an existing investigation within the configured window.

A contact-point test verifies delivery, not rule routing.
Use a controlled rule to verify a firing notification and its later resolution through the selected contact point.
Confirm that both notifications use the same source, fingerprint, and occurrence start time.
Resolution updates the occurrence and keeps its pending investigation eligible.

Receiving an alert does not start the agent automatically.
Follow [agent setup and dispatch](../local/agent.md) to run an investigation.
Hawkdive does not yet send investigation progress notifications to users.

## Troubleshoot

| Symptom | Check |
| --- | --- |
| Connection timeout or TLS failure | Grafana can reach the receiver hostname and port; its HTTPS certificate is valid. |
| HTTP `401` | The configured bearer token matches the receiver token; the proxy forwards Authorization. |
| HTTP `404` or `405` | The full webhook path is correct and the method is POST. |
| HTTP `422` | The integration sends the default Grafana JSON payload. |
| HTTP `503` | The receiver database is available and migrations have run. |
| Test succeeds, but real alerts do not arrive | Check rule or policy routing, silences, mute timings, and notification intervals. |
| Investigation stays PENDING | Dispatch is explicit; check agent configuration and the dispatch API. |

Review Grafana's contact-point delivery status and Hawkdive's diagnostic logs when a delivery fails.
