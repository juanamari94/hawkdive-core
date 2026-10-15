"""Replace occurrence jobs with investigations, attempts, and structured outputs."""

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('investigations',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('signature', sa.Text, nullable=False),
        sa.Column('trigger', sa.Text, nullable=False),
        sa.Column('status', sa.Text, nullable=False),
        sa.Column('created_at', sa.Text, nullable=False),
        sa.Column('window_ends_at', sa.Text, nullable=False),
        sa.CheckConstraint("status IN ('PENDING', 'RUNNING', 'FAILED', 'COMPLETED')"),
    )
    op.create_index('ix_investigations_signature', 'investigations', ['signature'])
    op.create_table('investigation_occurrences',
        sa.Column('issue_id', sa.Integer, sa.ForeignKey('issues.id'), primary_key=True),
        sa.Column('investigation_id', sa.Text, sa.ForeignKey('investigations.id'), nullable=False),
    )
    op.create_table('attempts',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('investigation_id', sa.Text, sa.ForeignKey('investigations.id'), nullable=False),
        sa.Column('number', sa.Integer, nullable=False),
        sa.Column('active_signature', sa.Text, unique=True),
        sa.Column('status', sa.Text, nullable=False),
        sa.Column('created_at', sa.Text, nullable=False),
        sa.Column('started_at', sa.Text),
        sa.Column('finished_at', sa.Text),
        sa.Column('execution_reference', sa.Text),
        sa.Column('exit_code', sa.Integer),
        sa.Column('error', sa.Text),
        sa.UniqueConstraint('investigation_id', 'number'),
        sa.CheckConstraint("status IN ('PENDING', 'RUNNING', 'FAILED', 'COMPLETED')"),
    )
    op.create_index('one_active_attempt_per_investigation', 'attempts', ['investigation_id'],
                    unique=True, sqlite_where=sa.text("status IN ('PENDING', 'RUNNING')"))
    op.create_table('investigation_outputs',
        sa.Column('attempt_id', sa.Text, sa.ForeignKey('attempts.id'), primary_key=True),
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('kind', sa.Text, nullable=False),
        sa.Column('content', sa.Text, nullable=False),
        sa.Column('created_at', sa.Text, nullable=False),
        sa.Column('sequence', sa.Integer, nullable=False),
        sa.UniqueConstraint('attempt_id', 'sequence'),
    )
    connection = op.get_bind()
    metadata = sa.MetaData()
    issues = sa.Table('issues', metadata, autoload_with=connection)
    jobs = sa.Table('jobs', metadata, autoload_with=connection)
    investigations = sa.Table('investigations', metadata, autoload_with=connection)
    links = sa.Table('investigation_occurrences', metadata, autoload_with=connection)
    # Legacy jobs have no receipt timestamps. Start their window at migration time.
    now = datetime.now(timezone.utc)
    groups = {}
    for row in connection.execute(sa.select(issues).join(jobs, jobs.c.issue_id == issues.c.id).order_by(issues.c.id)).mappings():
        signature = json.dumps(['grafana', row['source'], str(row['grafana_org_id']), row['fingerprint']])
        if signature not in groups:
            identifier = str(uuid4())
            groups[signature] = identifier
            connection.execute(investigations.insert().values(
                id=identifier, signature=signature, status='PENDING', created_at=now.isoformat(),
                window_ends_at=(now + timedelta(hours=1)).isoformat(),
                trigger=json.dumps({'integration': 'grafana', 'occurrence_id': row['id'],
                                    'reference': f"/issues/{row['id']}", 'alert': json.loads(row['alert'])}),
            ))
        connection.execute(links.insert().values(issue_id=row['id'], investigation_id=groups[signature]))
    op.drop_table('jobs')


def downgrade() -> None:
    op.create_table('jobs',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('issue_id', sa.Integer, sa.ForeignKey('issues.id'), nullable=False, unique=True),
        sa.Column('status', sa.Text, nullable=False),
    )
    connection = op.get_bind()
    connection.execute(sa.text("INSERT INTO jobs (issue_id, status) SELECT issue_id, 'pending' FROM investigation_occurrences"))
    for name in ('investigation_outputs', 'attempts', 'investigation_occurrences', 'investigations'):
        op.drop_table(name)
