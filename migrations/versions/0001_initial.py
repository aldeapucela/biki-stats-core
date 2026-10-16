"""Create the provider, station, observation and capture tables."""

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE providers (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        kind TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)
    op.execute("""
    CREATE TABLE stations (
        provider_id TEXT NOT NULL,
        station_id TEXT NOT NULL,
        name TEXT NOT NULL,
        latitude REAL,
        longitude REAL,
        capacity INTEGER,
        is_active INTEGER NOT NULL DEFAULT 1,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (provider_id, station_id),
        FOREIGN KEY (provider_id) REFERENCES providers(id)
    )
    """)
    op.execute("""
    CREATE TABLE observations (
        provider_id TEXT NOT NULL,
        station_id TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        collected_at TEXT NOT NULL,
        source TEXT NOT NULL,
        capture_id TEXT NOT NULL,
        mechanical_bikes INTEGER,
        electric_bikes INTEGER,
        free_docks INTEGER,
        capacity INTEGER,
        timestamp_ambiguous INTEGER NOT NULL DEFAULT 0,
        content_hash TEXT,
        PRIMARY KEY (provider_id, station_id, observed_at),
        FOREIGN KEY (provider_id, station_id) REFERENCES stations(provider_id, station_id)
    )
    """)
    op.execute("""
    CREATE TABLE captures (
        capture_id TEXT PRIMARY KEY,
        provider_id TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        status TEXT NOT NULL,
        accepted_count INTEGER NOT NULL DEFAULT 0,
        rejected_count INTEGER NOT NULL DEFAULT 0,
        error_message TEXT
    )
    """)
    op.execute("""
    CREATE TABLE capture_locks (
        provider_id TEXT PRIMARY KEY,
        capture_id TEXT NOT NULL UNIQUE,
        acquired_at TEXT NOT NULL,
        FOREIGN KEY (provider_id) REFERENCES providers(id)
    )
    """)
    op.execute("CREATE INDEX idx_observations_station_time ON observations(provider_id, station_id, observed_at)")
    op.execute("CREATE INDEX idx_observations_collected_at ON observations(collected_at)")
    op.execute("PRAGMA journal_mode=WAL")


def downgrade() -> None:
    op.execute("DROP TABLE observations")
    op.execute("DROP TABLE capture_locks")
    op.execute("DROP TABLE stations")
    op.execute("DROP TABLE captures")
    op.execute("DROP TABLE providers")
