"""Caso de uso para importar el histórico CSV de flujosbiki."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from movilidad.core.config import Settings, get_settings
from movilidad.core.logging import configure_logging
from movilidad.domain.entities import Capture, Observation, Station
from movilidad.infrastructure.db.connection import connect, ensure_schema
from movilidad.infrastructure.db.repository import SqliteObservationRepository
from movilidad.infrastructure.history.github import GitHubHistorySource, HistorySnapshot
from movilidad.infrastructure.providers.gbfs import GbfsProvider

logger = logging.getLogger(__name__)

SOURCE_KEY = "flujosbiki"
SOURCE_NAME = "flujosbiki"
PROVIDER_ID = "biki"
LOCAL_ZONE = ZoneInfo("Europe/Madrid")
EXPECTED_COLUMNS = (
    "station_id",
    "nombre",
    "mecanicas",
    "electricas",
    "capacidad",
    "timestamp",
)


@dataclass(frozen=True, slots=True)
class HistoryImportResult:
    status: str
    accepted: int = 0
    duplicate: int = 0
    conflict: int = 0
    rejected: int = 0
    derived: int = 0
    error: str | None = None
    commit: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedRow:
    station: Station
    observation: Observation
    derived_free_docks: bool


def run_historical_import(
    settings: Settings | None = None,
    *,
    dry_run: bool = False,
    force: bool = False,
    source: GitHubHistorySource | None = None,
    initial_capacities: Mapping[str, int] | None = None,
) -> HistoryImportResult:
    current = settings or get_settings()
    started_at = datetime.now(timezone.utc)
    source_adapter = source or GitHubHistorySource(
        current.history_source_repository,
        current.history_source_ref,
        current.http_timeout_seconds,
    )
    snapshot: HistorySnapshot | None = None
    connection = None
    repository = None
    import_id = f"history-{uuid4()}"
    counts = {"accepted": 0, "duplicate": 0, "conflict": 0, "rejected": 0, "derived": 0}
    try:
        if not dry_run:
            connection = connect(current)
            ensure_schema(connection)
            repository = SqliteObservationRepository(connection)
            claim = repository.claim_historical_import(
                SOURCE_KEY,
                current.history_source_repository,
                current.history_source_ref,
                started_at,
                force=force,
            )
            if claim in {"completed", "running"}:
                return HistoryImportResult(status="skipped")
            repository.ensure_provider(PROVIDER_ID, "BIKI Valladolid", "gbfs")
            repository.save_capture(Capture(import_id, PROVIDER_ID, started_at))
            initial_capacities = _load_initial_station_capacities(
                current,
                repository,
                initial_capacities,
                fetch_current=source is None,
            )

        snapshot = source_adapter.snapshot()
        counts, manifest_json = _process_snapshot(
            source_adapter,
            snapshot,
            repository,
            import_id,
            started_at,
            dry_run=dry_run,
            initial_capacities=initial_capacities,
        )
        if dry_run:
            return HistoryImportResult(status="simulated", commit=snapshot.commit, **counts)

        assert repository is not None
        repository.finish_capture(import_id, "success", counts["accepted"], counts["rejected"])
        repository.finish_historical_import(
            SOURCE_KEY,
            "completed",
            datetime.now(timezone.utc),
            source_commit=snapshot.commit,
            manifest_json=manifest_json,
            **counts,
        )
        logger.info(
            "Importación histórica completada",
            extra={"source_commit": snapshot.commit, "source_key": SOURCE_KEY, **counts},
        )
        return HistoryImportResult(status="completed", commit=snapshot.commit, **counts)
    except Exception as exc:
        message = str(exc)
        if repository is not None:
            repository.finish_capture(
                import_id,
                "failed",
                counts["accepted"],
                counts["rejected"],
                message,
            )
            if snapshot is not None:
                repository.finish_historical_import(
                    SOURCE_KEY,
                    "failed",
                    datetime.now(timezone.utc),
                    source_commit=snapshot.commit,
                    manifest_json=snapshot.manifest_json,
                    error_message=message,
                )
            else:
                repository.finish_historical_import(
                    SOURCE_KEY, "failed", datetime.now(timezone.utc), error_message=message
                )
        logger.exception("Importación histórica fallida", extra={"source_key": SOURCE_KEY})
        return HistoryImportResult(status="failed", error=message)
    finally:
        if connection is not None:
            connection.close()


def _process_snapshot(
    source: GitHubHistorySource,
    snapshot: HistorySnapshot,
    repository: SqliteObservationRepository | None,
    import_id: str,
    collected_at: datetime,
    *,
    dry_run: bool,
    initial_capacities: Mapping[str, int] | None = None,
) -> tuple[dict[str, int], str]:
    counts = {"accepted": 0, "duplicate": 0, "conflict": 0, "rejected": 0, "derived": 0}
    file_stats: list[dict[str, object]] = []
    pending_writes = 0
    known_capacities = repository.station_capacities(PROVIDER_ID) if repository else {}
    if initial_capacities:
        known_capacities.update(initial_capacities)
    authoritative_capacities = set(known_capacities)

    def record_parsed(parsed: ParsedRow, stats: dict[str, object]) -> None:
        nonlocal pending_writes
        if parsed.observation.capacity is not None:
            known_capacities.setdefault(parsed.observation.station_id, parsed.observation.capacity)
        if parsed.derived_free_docks:
            counts["derived"] += 1
            stats["derived"] = int(stats["derived"]) + 1
        if dry_run:
            counts["accepted"] += 1
            stats["accepted"] = int(stats["accepted"]) + 1
        else:
            assert repository is not None
            station = parsed.station
            if parsed.station.station_id in authoritative_capacities:
                station = replace(
                    station,
                    capacity=known_capacities[parsed.station.station_id],
                )
            repository.save_historical_station(station, collected_at)
            result = repository.save_historical_observation(parsed.observation)
            counts[result] += 1
            stats[result] = int(stats[result]) + 1
            pending_writes += 1
            if pending_writes >= 1000:
                repository.connection.commit()
                pending_writes = 0

    for history_file in snapshot.files:
        stats: dict[str, object] = {
            "path": history_file.path,
            "blob_sha": history_file.blob_sha,
            "size": history_file.size,
            "rows": 0,
            "accepted": 0,
            "duplicate": 0,
            "conflict": 0,
            "rejected": 0,
            "derived": 0,
            "repaired": 0,
            "capacity_overrides": 0,
            "stations": set(),
            "min_observed_at": None,
            "max_observed_at": None,
        }
        pending_repaired: list[tuple[dict[str, str | None], int]] = []
        reader = csv.DictReader(source.stream_csv(snapshot, history_file))
        if tuple(reader.fieldnames or ()) != EXPECTED_COLUMNS:
            raise ValueError(f"cabecera inválida en {history_file.path}: {reader.fieldnames!r}")
        for row_number, row in enumerate(reader, start=2):
            stats["rows"] = int(stats["rows"]) + 1
            normalised_row = row
            station_capacity: int | None = None
            try:
                normalised_row, repaired = _normalise_misaligned_row(row)
                station_id = _required(normalised_row.get("station_id"), "station_id")
                station_capacity = known_capacities.get(station_id)
                parsed = _parse_values(
                    normalised_row,
                    collected_at,
                    import_id,
                    capacity_override=station_capacity if repaired else None,
                )
                if repaired:
                    stats["repaired"] = int(stats["repaired"]) + 1
                stations = stats["stations"]
                assert isinstance(stations, set)
                stations.add(parsed.observation.station_id)
                observed = parsed.observation.observed_at.isoformat()
                if stats["min_observed_at"] is None or observed < stats["min_observed_at"]:
                    stats["min_observed_at"] = observed
                if stats["max_observed_at"] is None or observed > stats["max_observed_at"]:
                    stats["max_observed_at"] = observed
                if repaired and parsed.observation.capacity is None:
                    pending_repaired.append((normalised_row, row_number))
                else:
                    record_parsed(parsed, stats)
            except Exception as exc:
                if (
                    str(exc) == "bicicletas superiores a la capacidad"
                    and station_capacity is not None
                ):
                    try:
                        parsed = _parse_values(
                            normalised_row,
                            collected_at,
                            import_id,
                            capacity_override=station_capacity,
                        )
                        stats["capacity_overrides"] = int(stats["capacity_overrides"]) + 1
                        record_parsed(parsed, stats)
                        continue
                    except Exception as override_exc:
                        exc = override_exc
                counts["rejected"] += 1
                stats["rejected"] = int(stats["rejected"]) + 1
                if int(stats["rejected"]) <= 5:
                    logger.warning(
                        "Fila histórica rechazada",
                        extra={
                            "file": history_file.path,
                            "row": row_number,
                            "error": str(exc),
                        },
                    )
        for normalised_row, row_number in pending_repaired:
            try:
                station_id = _required(normalised_row.get("station_id"), "station_id")
                parsed = _parse_values(
                    normalised_row,
                    collected_at,
                    import_id,
                    capacity_override=known_capacities.get(station_id),
                )
                record_parsed(parsed, stats)
            except Exception as exc:
                counts["rejected"] += 1
                stats["rejected"] = int(stats["rejected"]) + 1
                if int(stats["rejected"]) <= 5:
                    logger.warning(
                        "Fila histórica reparada rechazada",
                        extra={
                            "file": history_file.path,
                            "row": row_number,
                            "error": str(exc),
                        },
                    )
        if repository is not None:
            repository.connection.commit()
        stats["stations"] = sorted(stats["stations"])
        file_stats.append(stats)
        logger.info("Archivo histórico procesado", extra={"file": history_file.path, **counts})
    return counts, json.dumps(file_stats, ensure_ascii=False, separators=(",", ":"))


def _load_initial_station_capacities(
    settings: Settings,
    repository: SqliteObservationRepository,
    supplied: Mapping[str, int] | None,
    *,
    fetch_current: bool,
) -> dict[str, int]:
    """Obtiene capacidades actuales antes de validar el histórico.

    En una primera importación la tabla de estaciones puede estar vacía. En ese
    caso, el feed actual es la fuente autoritativa para resolver filas cuyo
    histórico conserva una capacidad antigua. La consulta es solo de lectura;
    la captura normal sigue ejecutándose mediante su endpoint HTTP.
    """
    capacities = repository.station_capacities(PROVIDER_ID)
    if supplied:
        capacities.update(
            {str(station_id): int(capacity) for station_id, capacity in supplied.items()}
        )
    if not fetch_current:
        return capacities

    try:
        current_stations = GbfsProvider(
            settings.gbfs_url,
            settings.http_timeout_seconds,
        ).fetch()
    except Exception:
        logger.warning(
            "No se pudieron precargar las capacidades actuales desde GBFS; "
            "se usarán las capacidades disponibles en SQLite",
            exc_info=True,
        )
        return capacities

    capacities.update(
        {
            station.station_id: station.capacity
            for station, _ in current_stations
            if station.capacity is not None
        }
    )
    return capacities


def _normalise_misaligned_row(
    row: dict[str | None, str | None],
) -> tuple[dict[str | None, str | None], bool]:
    """Corrige en memoria el CSV antiguo con timestamp desplazado a capacidad."""
    timestamp = row.get("timestamp")
    candidate = row.get("capacidad")
    if timestamp is not None and timestamp.strip():
        return row, False
    if candidate is None or not candidate.strip():
        return row, False
    try:
        _parse_local_timestamp(candidate)
    except ValueError:
        return row, False
    normalised = dict(row)
    normalised["capacidad"] = None
    normalised["timestamp"] = candidate
    return normalised, True


def _parse_values(
    row: dict[str | None, str | None],
    collected_at: datetime,
    import_id: str,
    *,
    capacity_override: int | None = None,
) -> ParsedRow:
    if None in row:
        raise ValueError("columnas adicionales en la fila")
    station_id = _required(row.get("station_id"), "station_id")
    raw_name = _required(row.get("nombre"), "nombre")
    name = re.sub(r"^\s*\d+\s+", "", raw_name).strip() or station_id
    mechanical = _non_negative_int(row.get("mecanicas"), "mecanicas")
    electric = _non_negative_int(row.get("electricas"), "electricas")
    capacity = _non_negative_int(row.get("capacidad"), "capacidad")
    if capacity_override is not None:
        capacity = capacity_override
    observed_at, ambiguous = _parse_local_timestamp(_required(row.get("timestamp"), "timestamp"))
    free_docks = None
    derived = False
    if capacity is not None and mechanical is not None and electric is not None:
        free_docks = capacity - mechanical - electric
        if free_docks < 0:
            raise ValueError("bicicletas superiores a la capacidad")
        derived = True
    station = Station(PROVIDER_ID, station_id, name, capacity=capacity)
    observation = Observation(
        provider_id=PROVIDER_ID,
        station_id=station_id,
        observed_at=observed_at,
        collected_at=collected_at,
        source=SOURCE_NAME,
        capture_id=import_id,
        mechanical_bikes=mechanical,
        electric_bikes=electric,
        free_docks=free_docks,
        capacity=capacity,
        timestamp_ambiguous=ambiguous,
    )
    return ParsedRow(station, observation, derived)


def _required(value: str | None, field: str) -> str:
    if value is None or not value.strip():
        raise ValueError(f"{field} vacío")
    return value.strip()


def _non_negative_int(value: str | None, field: str) -> int | None:
    if value is None or not value.strip():
        return None
    parsed = int(value.strip())
    if parsed < 0:
        raise ValueError(f"{field} negativo")
    return parsed


def _parse_local_timestamp(value: str) -> tuple[datetime, bool]:
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            naive = datetime.strptime(value.strip(), pattern)
            break
        except ValueError:
            continue
    else:
        raise ValueError(f"timestamp no válido: {value}")
    first = naive.replace(tzinfo=LOCAL_ZONE, fold=0)
    second = naive.replace(tzinfo=LOCAL_ZONE, fold=1)
    first_roundtrip = first.astimezone(timezone.utc).astimezone(LOCAL_ZONE).replace(tzinfo=None)
    second_roundtrip = second.astimezone(timezone.utc).astimezone(LOCAL_ZONE).replace(tzinfo=None)
    if first_roundtrip != naive and second_roundtrip != naive:
        raise ValueError("timestamp inexistente por cambio horario")
    ambiguous = first.utcoffset() != second.utcoffset()
    return first.astimezone(timezone.utc), ambiguous


def history_import_status(settings: Settings | None = None) -> dict[str, object] | None:
    current = settings or get_settings()
    connection = connect(current)
    ensure_schema(connection)
    try:
        return SqliteObservationRepository(connection).historical_import_status(SOURCE_KEY)
    finally:
        connection.close()


async def history_import_worker(settings: Settings) -> None:
    """Reintenta la importación en segundo plano hasta completarla o apagar la API."""
    while True:
        result = await asyncio.to_thread(run_historical_import, settings)
        if result.status in {"completed", "skipped"}:
            return
        await asyncio.sleep(settings.history_import_retry_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Importa el histórico CSV de flujosbiki")
    parser.add_argument("--dry-run", action="store_true", help="valida sin modificar SQLite")
    parser.add_argument("--force", action="store_true", help="reprocesa una importación completada")
    args = parser.parse_args()
    configure_logging(get_settings().log_level)
    result = run_historical_import(dry_run=args.dry_run, force=args.force)
    print(result)
    if result.status == "failed":
        raise SystemExit(1)
