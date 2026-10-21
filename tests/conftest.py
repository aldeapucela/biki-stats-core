from pathlib import Path

import pytest

from movilidad.core.config import Settings
from movilidad.infrastructure.db.connection import connect, ensure_schema


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        BIKI_DATABASE_PATH=str(tmp_path / "test.sqlite3"),
        BIKI_CORS_ORIGINS="http://testserver",
    )


@pytest.fixture
def connection(settings: Settings):
    connection = connect(settings)
    ensure_schema(connection)
    yield connection
    connection.close()
