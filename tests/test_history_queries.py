import json
import logging
import random
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from movilidad.api import dependencies
from movilidad.api.main import app
from movilidad.application.services import CurrentStationsService
from movilidad.core.config import Settings, get_settings
from movilidad.core.logging import JsonFormatter
from movilidad.domain.entities import Observation, Station
from movilidad.infrastructure.db.connection import connect, init_database
from movilidad.infrastructure.db.repository import SqliteObservationRepository, iso
from tests.reference_history import reference_history, reference_summary

START = datetime(2026, 10, 1, 0, 7, 30, tzinfo=timezone.utc)
END = START + timedelta(days=6, hours=5, minutes=13)


def _observation(moment: datetime, rng: random.Random, capacity: int | None) -> Observation:
    free = rng.choice([None, rng.randint(0, 30), rng.randint(0, 24)])
    return Observation(
        "biki",
        "1",
        moment,
        moment,
        "test",
        "test",
        rng.choice([None, rng.randint(0, 12)]),
        rng.choice([None, rng.randint(0, 12)]),
        free,
        capacity,
    )


def _seed(connection, seed: int, count: int = 1500) -> SqliteObservationRepository:
    """Datos con nulos, sin capacidad, anclajes fuera de rango, huecos y segundos con fracción."""
    rng = random.Random(seed)
    repository = SqliteObservationRepository(connection)
    repository.ensure_provider("biki", "BIKI Valladolid", "gbfs")
    repository.save_station(Station("biki", "1", "Fuente Dorada", 41.65, -4.72, 20), START)
    moments = sorted(
        START + timedelta(seconds=rng.randint(0, int((END - START).total_seconds())))
        for _ in range(count)
    )
    rows = []
    for index, moment in enumerate(moments):
        if 300 < index < 420:  # hueco de varias horas sin observaciones
            continue
        if rng.random() < 0.3:
            moment = moment.replace(microsecond=rng.randint(1, 999_999))
        observation = _observation(moment, rng, rng.choice([None, 8, 16, 20, 24]))
        rows.append(
            (
                "biki",
                "1",
                iso(moment),
                iso(moment),
                "test",
                "test",
                observation.mechanical_bikes,
                observation.electric_bikes,
                observation.free_docks,
                observation.capacity,
            )
        )
    # Una sola transacción: `save_observation` hace commit por fila y tardaría minutos.
    connection.executemany(
        """INSERT OR IGNORE INTO observations(provider_id, station_id, observed_at, collected_at,
        source, capture_id, mechanical_bikes, electric_bikes, free_docks, capacity)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    connection.commit()
    return repository


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("granularity", ["hour", "day"])
def test_history_matches_reference_implementation(connection, seed, granularity) -> None:
    repository = _seed(connection, seed)
    service = CurrentStationsService(repository)
    for start, end in [
        (START, END),
        (START + timedelta(hours=3, minutes=1), END - timedelta(hours=2)),
        (START - timedelta(days=2), END + timedelta(days=2)),
    ]:
        observations = repository.station_history("biki", "1", start, end)
        expected = reference_history(observations, start, end, granularity)
        actual = service.history("biki", "1", start, end, granularity, 10_000)
        assert actual is not None
        assert actual["points"] == expected


@pytest.mark.parametrize("seed", range(6))
def test_summary_matches_reference_implementation(connection, seed) -> None:
    repository = _seed(connection, seed)
    service = CurrentStationsService(repository)
    for start, end in [
        (START, END),
        (START + timedelta(hours=3, minutes=1), END - timedelta(hours=2)),
        (START - timedelta(days=2), END + timedelta(days=2)),
        (START + timedelta(days=30), START + timedelta(days=31)),
    ]:
        observations = repository.station_history("biki", "1", start, end)
        assert service.summary("biki", "1", start, end) == reference_summary(
            observations, "1", start, end
        )


def test_occupancy_tie_keeps_exact_rounding(connection) -> None:
    """95 filas al 50 % y 5 al 37,5 %: media exacta 49,375, que redondea a 49,38."""
    repository = SqliteObservationRepository(connection)
    repository.ensure_provider("biki", "BIKI Valladolid", "gbfs")
    repository.save_station(Station("biki", "1", "Fuente Dorada", None, None, 8), START)
    hour = START.replace(minute=0, second=0)
    for index in range(100):
        moment = hour + timedelta(seconds=index * 30)
        free = 4 if index % 20 else 5
        repository.save_observation(
            Observation("biki", "1", moment, moment, "test", "test", 1, 1, free, 8)
        )
    end = hour + timedelta(hours=1)
    observations = repository.station_history("biki", "1", hour, end)
    expected = reference_history(observations, hour, end, "hour")
    actual = CurrentStationsService(repository).history("biki", "1", hour, end, "hour", 10)
    assert actual is not None
    assert expected[0]["occupancy_percent"] == 49.38
    assert actual["points"] == expected


def test_history_queries_use_the_station_time_index(connection) -> None:
    repository = _seed(connection, 1, count=300)
    statements: list[str] = []
    connection.set_trace_callback(statements.append)
    repository.history_groups("biki", "1", START, END, "hour")
    repository.summary_groups("biki", "1", START, END)
    connection.set_trace_callback(None)
    selects = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 3
    for sql in selects:
        plan = [row["detail"] for row in connection.execute(f"EXPLAIN QUERY PLAN {sql}")]
        # El índice debe acotar por estación y por rango de fechas, no solo por proveedor.
        assert any(
            "SEARCH observations USING" in detail
            and "station_id=?" in detail
            and "observed_at>?" in detail
            and "observed_at<?" in detail
            for detail in plan
        ), plan
        assert not any(detail.startswith("SCAN observations") for detail in plan), plan


def test_requests_do_not_create_schema_or_set_wal(tmp_path, monkeypatch) -> None:
    database = tmp_path / "request.sqlite3"
    monkeypatch.setenv("BIKI_DATABASE_PATH", str(database))
    get_settings.cache_clear()
    statements: list[str] = []
    real_connect = dependencies.connect

    def traced_connect(settings=None):
        connection = real_connect(settings)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(dependencies, "connect", traced_connect)
    with TestClient(app) as client:  # el arranque inicializa la base una vez
        statements.clear()
        assert client.get("/api/v1/stations?limit=1").status_code == 200
        assert client.get("/api/v1/health").status_code == 200
    get_settings.cache_clear()
    assert statements, "la petición debería haber ejecutado alguna sentencia"
    assert not [s for s in statements if "CREATE" in s.upper() or "journal_mode" in s]


def test_init_database_sets_wal_once_and_connect_does_not(settings: Settings) -> None:
    plain = connect(settings)
    assert plain.execute("PRAGMA journal_mode").fetchone()[0] != "wal"
    init_database(plain)
    plain.close()
    assert connect(settings).execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_queries_log_time_and_volume(connection, caplog) -> None:
    repository = _seed(connection, 2, count=200)
    service = CurrentStationsService(repository)
    with caplog.at_level(logging.INFO, logger="movilidad.history"):
        service.history("biki", "1", START, END, "hour", 10_000)
        service.history("biki", "1", START, END, "raw", 10_000)
        service.summary("biki", "1", START, END)
    records = [r for r in caplog.records if r.name == "movilidad.history"]
    assert [r.kind for r in records] == ["history", "history", "summary"]
    for record in records:
        assert record.sql_ms >= 0 and record.duration_ms >= record.sql_ms
        assert record.rows > 0 and 0 < record.groups <= record.rows
    payload = json.loads(JsonFormatter().format(records[0]))
    assert {"kind", "station_id", "granularity", "duration_ms", "sql_ms", "rows", "groups"} <= set(
        payload
    )
