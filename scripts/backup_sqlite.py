"""Crea una copia consistente de SQLite usando la API de backup."""

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from movilidad.core.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    source = Path(get_settings().database_path)
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as source_connection, sqlite3.connect(args.destination) as target:
        source_connection.backup(target)
    print(f"Backup creado: {args.destination} ({datetime.now(timezone.utc).isoformat()})")


if __name__ == "__main__":
    main()
