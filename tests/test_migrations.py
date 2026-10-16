import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from alembic import command
from test_webhooks import client_for, payload, read, send

from hawkdive.database import migration_config

ROOT = Path(__file__).resolve().parents[1]


def migrate(path):
    return subprocess.run(
        [sys.executable, '-m', 'alembic', 'upgrade', 'head'],
        cwd=ROOT, env={**os.environ, 'HAWKDIVE_DB_PATH': str(path)},
        capture_output=True, text=True,
    )


def test_initial_migration_creates_current_schema_and_can_repeat(tmp_path):
    path = tmp_path / 'nested' / 'alerts.sqlite3'
    result = migrate(path)
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(path) as connection:
        assert connection.execute('SELECT version_num FROM alembic_version').fetchone() == ('0002',)
        for table in ('issues', 'notifications'):
            columns = {row[1] for row in connection.execute(f'PRAGMA table_info({table})')}
            assert 'grafana_org_id' in columns
            assert 'org_id' not in columns
    assert migrate(path).returncode == 0
    with client_for(path) as client:
        assert send(client, payload()).status_code == 202
        assert len(read(client, 'jobs')) == 1


def test_upgrade_preserves_alert_history_and_groups_legacy_jobs(tmp_path, monkeypatch):

    path = tmp_path / 'legacy.sqlite3'
    monkeypatch.setenv('HAWKDIVE_DB_PATH', str(path))
    command.upgrade(migration_config(), '0001')
    with sqlite3.connect(path) as connection:
        for identifier, name in enumerate(('firing', 'recurring'), 1):
            alert = payload(name)['alerts'][0]
            connection.execute(
                'INSERT INTO issues VALUES (?, ?, ?, ?, ?, ?, ?)',
                (identifier, 'local', 1, alert['fingerprint'], alert['startsAt'], 'resolved', json.dumps(alert)),
            )
            connection.execute('INSERT INTO jobs VALUES (?, ?, ?)', (identifier, identifier, 'cancelled'))
        connection.execute('INSERT INTO notifications VALUES (?, ?, ?, ?, ?)', (1, 'local', 1, 'saved', '{}'))
    command.upgrade(migration_config(), 'head')
    with client_for(path) as client:
        assert len(read(client, 'issues')) == 2
        assert len(read(client, 'notifications')) == 1
        records = read(client, 'investigations')
        assert len(records) == 1
        assert records[0]['status'] == 'PENDING'
        assert records[0]['occurrence_ids'] == [1, 2]
        assert records[0]['attempts'] == []


@pytest.mark.parametrize('existing', [False, True])
def test_startup_requires_migrations(tmp_path, existing):
    path = tmp_path / 'empty.sqlite3'
    if existing:
        path.touch()
    with pytest.raises(RuntimeError, match='alembic upgrade head'):
        with client_for(path):
            pass
