#!/usr/bin/env python3
"""Mide la latencia de `/history` y `/summary` con clientes concurrentes (issue #20).

Genera una base SQLite sintética con la forma de la de producción (una semana y media de
observaciones cada ~35 s y después cada 300 s), levanta uvicorn con un worker y lanza N clientes
que piden `history` y `summary` a la vez, como el frontend. No forma parte del CI: los tiempos
dependen de la máquina. Para comparar antes y después, apunte `--src` al `src/` de cada versión:

    python scripts/bench_history.py --src ../biki-stats-core/src
    python scripts/bench_history.py --src src
"""

import argparse
import os
import random
import socket
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_database(path: str, stations: int, now: datetime, src: str) -> int:
    """Crea el esquema con el propio código bajo prueba y rellena las observaciones."""
    sys.path.insert(0, src)
    from movilidad.core.config import Settings
    from movilidad.infrastructure.db.connection import connect, ensure_schema

    connection = connect(Settings(BIKI_DATABASE_PATH=path))
    connection.execute("PRAGMA journal_mode=WAL")
    ensure_schema(connection)
    connection.execute("INSERT INTO providers VALUES ('biki', 'BIKI', 'gbfs', ?)", (iso(now),))
    rng = random.Random(7)
    total = 0
    sparse_from = now - timedelta(days=4)
    dense_from = now - timedelta(days=31)
    for number in range(1, stations + 1):
        capacity = rng.choice([12, 16, 20, 24])
        connection.execute(
            "INSERT INTO stations VALUES ('biki', ?, ?, 41.65, -4.72, ?, 1, ?)",
            (str(number), f"Estación {number}", capacity, iso(now)),
        )
        rows = []
        moment = dense_from
        while moment < now:
            step = 300 if moment >= sparse_from else 36
            mechanical = rng.randint(0, capacity // 2)
            electric = rng.randint(0, capacity // 2)
            free = max(capacity - mechanical - electric, 0)
            rows.append(
                ("biki", str(number), iso(moment), iso(moment), "bench", "bench")
                + (mechanical, electric, free, capacity, 0, None)
            )
            moment += timedelta(seconds=step + rng.randint(0, 3))
        connection.executemany(
            "INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows
        )
        total += len(rows)
    connection.commit()
    connection.close()
    return total


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def run_clients(base: str, days: int, granularity: str, clients: int, stations: int, now: datetime):
    window = {"from": iso(now - timedelta(days=days)), "to": iso(now + timedelta(minutes=5))}
    results: list[tuple[float, int]] = []
    lock = threading.Lock()

    def one(path: str, extra: dict[str, str]) -> None:
        started = time.perf_counter()
        try:
            code = httpx.get(base + path, params={**window, **extra}, timeout=120).status_code
        except httpx.HTTPError:
            code = 0
        with lock:
            results.append((time.perf_counter() - started, code))

    threads = []
    for client in range(clients):
        station = 1 + client % stations
        threads.append(
            threading.Thread(
                target=one, args=(f"/stations/{station}/history", {"granularity": granularity})
            )
        )
        threads.append(threading.Thread(target=one, args=(f"/stations/{station}/summary", {})))
    started = time.perf_counter()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    wall = time.perf_counter() - started
    good = sorted(seconds for seconds, code in results if code == 200)
    failed = len(results) - len(good)
    if not good:
        return f"{days:>3} d {granularity:<4} clientes={clients:>2}  todas las peticiones fallaron"
    return (
        f"{days:>3} d {granularity:<4} clientes={clients:>2} fallos={failed} "
        f"mín={good[0]:.2f}s mediana={statistics.median(good):.2f}s máx={good[-1]:.2f}s "
        f"total={wall:.2f}s"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--src", default=str(ROOT / "src"), help="directorio src a medir")
    parser.add_argument("--stations", type=int, default=10)
    parser.add_argument("--clients", type=int, nargs="+", default=[1, 4, 10])
    parser.add_argument("--database", help="base a reutilizar; si no existe se genera ahí")
    args = parser.parse_args()
    src = str(Path(args.src).resolve())
    now = datetime.now(timezone.utc).replace(microsecond=0)
    with tempfile.TemporaryDirectory() as directory:
        path = args.database or os.path.join(directory, "bench.sqlite3")
        if not os.path.exists(path):
            print(f"Generando {args.stations} estaciones…", flush=True)
            total = build_database(path, args.stations, now, src)
            print(f"{total} observaciones, {os.path.getsize(path) // 1_000_000} MB")
        port = free_port()
        env = {**os.environ, "PYTHONPATH": src, "BIKI_DATABASE_PATH": path, "BIKI_ENV": "bench"}
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "movilidad.api.main:app", "--port", str(port)]
            + ["--log-level", "warning"],
            env=env,
            stdout=subprocess.DEVNULL,
        )
        base = f"http://127.0.0.1:{port}/api/v1"
        try:
            for _ in range(100):
                try:
                    if httpx.get(base + "/health", timeout=2).status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(0.2)
            print(f"Servidor de {src}")
            for days, granularity in [(7, "hour"), (30, "hour"), (30, "day"), (90, "day")]:
                for clients in args.clients:
                    print(run_clients(base, days, granularity, clients, args.stations, now))
        finally:
            server.terminate()
            server.wait(timeout=10)
        sqlite3.connect(path).close()


if __name__ == "__main__":
    main()
