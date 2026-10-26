import sqlite3
from pathlib import Path

from movilidad.core.config import Settings, get_settings


def connect(settings: Settings | None = None) -> sqlite3.Connection:
    """Abre una conexión con los pragmas que SQLite exige por conexión.

    `journal_mode=WAL` se guarda en el fichero: se fija una vez en `init_database`, no aquí.
    """
    current = settings or get_settings()
    path = Path(current.database_path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(current.database_path, timeout=30, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=30000")
    return connection


def init_database(connection: sqlite3.Connection) -> None:
    """Configuración de arranque: WAL (persistente) y creación defensiva del esquema.

    Se ejecuta una vez al arrancar la API y en los puntos de entrada del collector y de la
    importación, nunca por petición HTTP.
    """
    connection.execute("PRAGMA journal_mode=WAL")
    ensure_schema(connection)


def initialize_database(settings: Settings | None = None) -> None:
    """Inicializa SQLite una vez por proceso, fuera del camino de cada petición."""
    connection = connect(settings)
    try:
        init_database(connection)
    finally:
        connection.close()


def ensure_schema(connection: sqlite3.Connection) -> None:
    """Arranque seguro para desarrollo; producción debe ejecutar Alembic explícitamente."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS providers (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS stations (
            provider_id TEXT NOT NULL, station_id TEXT NOT NULL, name TEXT NOT NULL,
            latitude REAL, longitude REAL, capacity INTEGER, is_active INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL, PRIMARY KEY(provider_id, station_id),
            FOREIGN KEY(provider_id) REFERENCES providers(id)
        );
        CREATE TABLE IF NOT EXISTS observations (
            provider_id TEXT NOT NULL, station_id TEXT NOT NULL, observed_at TEXT NOT NULL,
            collected_at TEXT NOT NULL, source TEXT NOT NULL, capture_id TEXT NOT NULL,
            mechanical_bikes INTEGER, electric_bikes INTEGER, free_docks INTEGER, capacity INTEGER,
            timestamp_ambiguous INTEGER NOT NULL DEFAULT 0, content_hash TEXT,
            PRIMARY KEY(provider_id, station_id, observed_at),
            FOREIGN KEY(provider_id, station_id) REFERENCES stations(provider_id, station_id)
        );
        CREATE TABLE IF NOT EXISTS captures (
            capture_id TEXT PRIMARY KEY, provider_id TEXT NOT NULL, started_at TEXT NOT NULL,
            finished_at TEXT, status TEXT NOT NULL, accepted_count INTEGER NOT NULL DEFAULT 0,
            rejected_count INTEGER NOT NULL DEFAULT 0, error_message TEXT
        );
        CREATE TABLE IF NOT EXISTS capture_locks (
            provider_id TEXT PRIMARY KEY,
            capture_id TEXT NOT NULL UNIQUE,
            acquired_at TEXT NOT NULL,
            FOREIGN KEY(provider_id) REFERENCES providers(id)
        );
        CREATE INDEX IF NOT EXISTS idx_observations_station_time
            ON observations(provider_id, station_id, observed_at);
        CREATE INDEX IF NOT EXISTS idx_observations_station_history_covering
            ON observations(
                provider_id, station_id, observed_at,
                mechanical_bikes, electric_bikes, free_docks, capacity
            );
        CREATE INDEX IF NOT EXISTS idx_observations_collected_at ON observations(collected_at);
        CREATE TABLE IF NOT EXISTS historical_imports (
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
        );
        """
    )
    connection.commit()
