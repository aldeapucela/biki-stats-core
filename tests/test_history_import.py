import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from movilidad.application.history_import import (
    _parse_local_timestamp,
    run_historical_import,
)
from movilidad.core.config import Settings
from movilidad.domain.entities import Station
from movilidad.infrastructure.db.connection import connect, ensure_schema
from movilidad.infrastructure.db.repository import SqliteObservationRepository
from movilidad.infrastructure.history.github import HistoryFile, HistorySnapshot


@dataclass
class FakeHistorySource:
    files_content: dict[str, str]

    def snapshot(self) -> HistorySnapshot:
        files = tuple(
            HistoryFile(path=path, blob_sha=f"sha-{index}", size=len(content))
            for index, (path, content) in enumerate(sorted(self.files_content.items()))
        )
        return HistorySnapshot(
            repository="fixture/source",
            requested_ref="fixture",
            commit="commit-fixture",
            files=files,
            manifest_json="[]",
        )

    def stream_csv(self, snapshot: HistorySnapshot, file: HistoryFile):
        yield from self.files_content[file.path].splitlines(keepends=True)


def test_history_import_normalises_is_idempotent_and_preserves_current_station(tmp_path) -> None:
    settings = Settings(BIKI_DATABASE_PATH=str(tmp_path / "history.sqlite3"))
    source = FakeHistorySource(
        {
            "data/archivo/historico.csv": (
                "station_id,nombre,mecanicas,electricas,capacidad,timestamp\n"
                "2,001 Fuente Dorada,3,2,10,2026-10-01 00:00:00\n"
            ),
            "data/historico.csv": (
                "station_id,nombre,mecanicas,electricas,capacidad,timestamp\n"
                "2,001 Fuente Dorada,3,2,10,2026-10-01 00:00:00\n"
                "2,001 Fuente Dorada,4,2,10,2026-10-01 00:00:00\n"
            ),
        }
    )

    connection = connect(settings)
    ensure_schema(connection)
    repository = SqliteObservationRepository(connection)
    repository.ensure_provider("biki", "BIKI Valladolid", "gbfs")
    repository.save_station(
        Station("biki", "2", "Fuente actual", latitude=41.65, longitude=-4.72, capacity=27),
        datetime.now(timezone.utc),
    )
    connection.commit()
    connection.close()

    first = run_historical_import(settings, source=source)
    assert first.status == "completed"
    assert first.accepted == 1
    assert first.duplicate == 1
    assert first.conflict == 1
    assert first.derived == 3

    second = run_historical_import(settings, source=source)
    assert second.status == "skipped"

    forced = run_historical_import(settings, source=source, force=True)
    assert forced.status == "completed"
    assert forced.accepted == 0
    assert forced.duplicate == 2
    assert forced.conflict == 1

    with sqlite3.connect(settings.database_path) as connection:
        station = connection.execute(
            "SELECT name, latitude, free_docks FROM stations "
            "JOIN observations USING(provider_id, station_id) WHERE station_id = '2'"
        ).fetchone()
        assert station == ("Fuente Dorada", 41.65, 5)
        assert connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
        assert (
            connection.execute(
                "SELECT status FROM historical_imports WHERE source_key = 'flujosbiki'"
            ).fetchone()[0]
            == "completed"
        )


def test_history_import_dry_run_does_not_write_data(tmp_path) -> None:
    settings = Settings(BIKI_DATABASE_PATH=str(tmp_path / "history.sqlite3"))
    source = FakeHistorySource(
        {
            "data/historico.csv": (
                "station_id,nombre,mecanicas,electricas,capacidad,timestamp\n"
                "2,001 Fuente Dorada,3,2,10,2026-10-01 00:00:00\n"
            )
        }
    )

    result = run_historical_import(settings, source=source, dry_run=True)
    assert result.status == "simulated"
    assert result.accepted == 1

    with sqlite3.connect(settings.database_path) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name = 'observations'"
            ).fetchone()[0]
            == 0
        )


def test_history_import_repairs_shifted_timestamp_and_recovers_capacity(tmp_path) -> None:
    settings = Settings(BIKI_DATABASE_PATH=str(tmp_path / "history.sqlite3"))
    source = FakeHistorySource(
        {
            "data/archivo/historico.csv": (
                "station_id,nombre,mecanicas,electricas,capacidad,timestamp\n"
                "2,001 Fuente Dorada,3,2,2026-10-01 00:00:00\n"
                "2,001 Fuente Dorada,4,2,27,2026-10-01 00:01:00\n"
            )
        }
    )

    result = run_historical_import(settings, source=source)

    assert result.status == "completed"
    assert result.accepted == 2
    assert result.rejected == 0
    assert result.derived == 2
    with sqlite3.connect(settings.database_path) as connection:
        repaired = connection.execute(
            "SELECT mechanical_bikes, free_docks, capacity FROM observations "
            "WHERE observed_at LIKE '2026-09-30T22:00:00%'"
        ).fetchone()
        assert repaired == (3, 22, 27)


def test_history_import_uses_station_capacity_when_historical_capacity_is_stale(tmp_path) -> None:
    settings = Settings(BIKI_DATABASE_PATH=str(tmp_path / "history.sqlite3"))
    source = FakeHistorySource(
        {
            "data/historico.csv": (
                "station_id,nombre,mecanicas,electricas,capacidad,timestamp\n"
                "33,209 Paseo del Cauce,5,14,18,2026-10-15 03:55:28\n"
            )
        }
    )

    connection = connect(settings)
    ensure_schema(connection)
    repository = SqliteObservationRepository(connection)
    repository.ensure_provider("biki", "BIKI Valladolid", "gbfs")
    repository.save_station(
        Station("biki", "33", "Paseo del Cauce", capacity=19),
        datetime.now(timezone.utc),
    )
    connection.commit()
    connection.close()

    result = run_historical_import(settings, source=source)

    assert result.status == "completed"
    assert result.accepted == 1
    assert result.rejected == 0
    assert result.derived == 1
    with sqlite3.connect(settings.database_path) as connection:
        observation = connection.execute(
            "SELECT mechanical_bikes, electric_bikes, free_docks, capacity FROM observations"
        ).fetchone()
        assert observation == (5, 14, 0, 19)


def test_history_import_uses_initial_capacity_when_database_is_empty(tmp_path) -> None:
    settings = Settings(BIKI_DATABASE_PATH=str(tmp_path / "history.sqlite3"))
    source = FakeHistorySource(
        {
            "data/historico.csv": (
                "station_id,nombre,mecanicas,electricas,capacidad,timestamp\n"
                "33,209 Paseo del Cauce,5,14,18,2026-10-15 03:55:28\n"
            )
        }
    )

    result = run_historical_import(
        settings,
        source=source,
        initial_capacities={"33": 19},
    )

    assert result.status == "completed"
    assert result.accepted == 1
    assert result.rejected == 0
    with sqlite3.connect(settings.database_path) as connection:
        observation = connection.execute("SELECT free_docks, capacity FROM observations").fetchone()
        station = connection.execute(
            "SELECT capacity FROM stations WHERE station_id = '33'"
        ).fetchone()
        assert observation == (0, 19)
        assert station == (19,)


def test_history_import_handles_ambiguous_and_nonexistent_local_time() -> None:
    ambiguous, is_ambiguous = _parse_local_timestamp("2026-10-25 02:30:00")
    assert is_ambiguous is True
    assert ambiguous.tzinfo == timezone.utc

    try:
        _parse_local_timestamp("2026-03-29 02:30:00")
    except ValueError as error:
        assert "inexistente" in str(error)
    else:
        raise AssertionError("La hora inexistente debe rechazarse")
