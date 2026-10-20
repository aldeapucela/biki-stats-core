"""Add persistent state for the historical import."""

from alembic import op

revision = "0002_historical_import"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE historical_imports (
        source_key TEXT PRIMARY KEY,
        source_repository TEXT NOT NULL,
        source_ref TEXT NOT NULL,
        source_commit TEXT,
        manifest_json TEXT,
        status TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        updated_at TEXT NOT NULL,
        accepted_count INTEGER NOT NULL DEFAULT 0,
        duplicate_count INTEGER NOT NULL DEFAULT 0,
        conflict_count INTEGER NOT NULL DEFAULT 0,
        rejected_count INTEGER NOT NULL DEFAULT 0,
        derived_count INTEGER NOT NULL DEFAULT 0,
        error_message TEXT
    )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE historical_imports")
