import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from alembic import command
from fastapi.testclient import TestClient

from hawkdive.app import create_app
from hawkdive.database import migration_config

FIXTURES = Path(__file__).parent / "fixtures" / "grafana"
AUTH = {"Authorization": "Bearer test-token"}


def payload(name="firing"):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8-sig"))


def client_for(path):
    return TestClient(create_app(db_path=path, webhook_token="test-token"))


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / "alerts.sqlite3"
    monkeypatch.setenv('HAWKDIVE_DB_PATH', str(path))
    command.upgrade(migration_config(), 'head')
    with client_for(path) as client:
        yield client


def send(client, body, source="local"):
    return client.post(f"/webhooks/grafana/{source}", json=body, headers=AUTH)


def read(client, resource):
    response = client.get(f"/{resource}", headers=AUTH)
    assert response.status_code == 200
    return response.json()


def test_firing_alert_preserves_evidence_and_queues_work(client):
    body = payload()
    body["alerts"][0]["futureField"] = "keep this evidence"
    assert send(client, body).status_code == 202
    issue = read(client, "issues")[0]
    assert issue["status"] == "firing"
    assert issue["grafana_org_id"] == body["orgId"]
    assert "org_id" not in issue
    assert issue["alert"] == body["alerts"][0]
    notification = read(client, "notifications")[0]
    assert notification["grafana_org_id"] == body["orgId"]
    assert "org_id" not in notification
    assert read(client, "jobs")[0]["status"] == "pending"


def test_grouped_notification_keeps_individual_alerts(client):
    assert send(client, payload("grouped")).json()["queued"] == 2
    assert len(read(client, "issues")) == 2


def test_captured_grafana_contact_point_payload_is_preserved_and_deduplicated(client):
    body = payload('contact_point_test_13_2_3')
    assert send(client, body, source='local-grafana').status_code == 202
    assert send(client, body, source='local-grafana').json()['duplicate'] is True
    assert read(client, 'notifications')[0]['payload'] == body
    assert read(client, 'issues')[0]['alert'] == body['alerts'][0]
    assert len(read(client, 'jobs')) == 1


def test_repeated_notification_does_not_duplicate_work(client):
    send(client, payload())
    response = send(client, payload("repeated"))
    assert response.json()["duplicate"] is True
    assert len(read(client, "issues")) == len(read(client, "jobs")) == 1
    assert len(read(client, "notifications")) == 1


def test_captured_rule_resolution_updates_the_same_occurrence(client):
    firing = payload('rule_firing_13_2_3')
    resolved = payload('rule_resolved_13_2_3')
    assert send(client, firing).status_code == 202
    assert send(client, resolved).status_code == 202
    issues = read(client, 'issues')
    assert len(issues) == 1
    assert issues[0]['status'] == 'resolved'
    assert issues[0]['alert'] == resolved['alerts'][0]
    assert [item['payload'] for item in read(client, 'notifications')] == [firing, resolved]
    assert [job['status'] for job in read(client, 'jobs')] == ['pending']


def test_new_evidence_updates_an_issue_without_another_job(client):
    send(client, payload())
    body = payload()
    body["alerts"][0]["values"]["A"] = 99
    send(client, body)
    assert read(client, "issues")[0]["alert"]["values"]["A"] == 99
    assert len(read(client, "jobs")) == 1
    assert len(read(client, "notifications")) == 2


def test_resolution_preserves_pending_investigation(client):
    send(client, payload())
    send(client, payload("resolved"))
    assert read(client, "issues")[0]["status"] == "resolved"
    assert read(client, "jobs")[0]["status"] == "pending"


def test_recurrence_creates_a_new_occurrence(client):
    send(client, payload())
    send(client, payload("resolved"))
    send(client, payload("recurring"))
    assert [issue["status"] for issue in read(client, "issues")] == ["resolved", "firing"]
    assert [job["status"] for job in read(client, "jobs")] == ["pending"]
    assert len(read(client, 'investigations')[0]['occurrence_ids']) == 2


def test_delayed_firing_does_not_reopen_a_resolved_occurrence(client):
    send(client, payload("resolved"))
    send(client, payload())
    assert read(client, "issues")[0]["status"] == "resolved"
    assert read(client, "jobs") == []


def test_source_and_organization_isolate_identical_fingerprints(client):
    send(client, payload(), source="one")
    send(client, payload(), source="two")
    body = payload()
    body["orgId"] = 2
    send(client, body, source="one")
    assert len(read(client, "issues")) == len(read(client, "jobs")) == 3


def test_alerts_and_pending_work_survive_a_restart(tmp_path, monkeypatch):
    path = tmp_path / "persistent.sqlite3"
    monkeypatch.setenv('HAWKDIVE_DB_PATH', str(path))
    command.upgrade(migration_config(), 'head')
    with client_for(path) as first:
        send(first, payload())
    with client_for(path) as second:
        assert len(read(second, "issues")) == len(read(second, "jobs")) == 1
        assert read(second, "notifications")[0]["payload"] == payload()


def test_optional_fields_and_truncation_are_preserved(client):
    body = payload("minimal")
    body["truncatedAlerts"] = 3
    response = send(client, body)
    assert response.json()["truncated_alerts"] == 3
    assert len(read(client, "issues")) == 1
    assert read(client, "notifications")[0]["payload"] == body


@pytest.mark.parametrize("change", [
    lambda body: body.pop("alerts"),
    lambda body: body.update(alerts=[]),
    lambda body: body["alerts"][0].update(status="unknown"),
    lambda body: body["alerts"][0].update(startsAt="not-a-date"),
])
def test_invalid_notification_stores_nothing(client, change):
    body = payload()
    change(body)
    assert send(client, body).status_code == 422
    assert read(client, "issues") == read(client, "jobs") == read(client, "notifications") == []


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}])
def test_unauthorized_requests_store_nothing(client, headers):
    response = client.post("/webhooks/grafana/local", json=payload(), headers=headers)
    assert response.status_code == 401
    assert read(client, "notifications") == []


def test_concurrent_delivery_queues_one_job(client):
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: send(client, payload()), range(4)))
    assert all(response.status_code == 202 for response in responses)
    assert len(read(client, "jobs")) == len(read(client, "notifications")) == 1


def test_storage_failure_rolls_back_notification_and_all_alerts(client, tmp_path):
    path = tmp_path / 'alerts.sqlite3'
    with sqlite3.connect(path) as connection:
        connection.execute("""
            CREATE TRIGGER reject_second_investigation BEFORE INSERT ON investigations
            WHEN (SELECT COUNT(*) FROM investigations) = 1
            BEGIN SELECT RAISE(ABORT, 'Storage failure'); END
        """)
    assert send(client, payload('grouped')).status_code == 503
    assert read(client, 'notifications') == read(client, 'issues') == read(client, 'jobs') == []
    with sqlite3.connect(path) as connection:
        connection.execute('DROP TRIGGER reject_second_investigation')
    assert send(client, payload('grouped')).json()['queued'] == 2
