"""Create the initial schema."""
import sqlalchemy as sa
from alembic import op

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def definitions() -> dict[str, tuple[sa.Column | sa.UniqueConstraint, ...]]:
    return {
        'notifications': (
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('source', sa.Text, nullable=False),
            sa.Column('grafana_org_id', sa.Integer, nullable=False),
            sa.Column('digest', sa.Text, nullable=False),
            sa.Column('payload', sa.Text, nullable=False),
            sa.UniqueConstraint('source', 'grafana_org_id', 'digest'),
        ),
        'issues': (
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('source', sa.Text, nullable=False),
            sa.Column('grafana_org_id', sa.Integer, nullable=False),
            sa.Column('fingerprint', sa.Text, nullable=False),
            sa.Column('starts_at', sa.Text, nullable=False),
            sa.Column('status', sa.Text, nullable=False),
            sa.Column('alert', sa.Text, nullable=False),
            sa.UniqueConstraint('source', 'grafana_org_id', 'fingerprint', 'starts_at'),
        ),
        'jobs': (
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('issue_id', sa.Integer, sa.ForeignKey('issues.id'), nullable=False),
            sa.Column('status', sa.Text, nullable=False),
            sa.UniqueConstraint('issue_id'),
        ),
    }


def upgrade() -> None:
    for name, columns in definitions().items():
        op.create_table(name, *columns)


def downgrade() -> None:
    for name in ('jobs', 'issues', 'notifications'):
        op.drop_table(name)
