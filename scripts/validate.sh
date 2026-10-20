#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
ALEMBIC_BIN="${ALEMBIC_BIN:-$ROOT_DIR/.venv/bin/alembic}"
RUFF_BIN="${RUFF_BIN:-$ROOT_DIR/.venv/bin/ruff}"
DOCKER_BUILD=0
LIVE_FEED=0

usage() {
  cat <<'EOF'
Uso: scripts/validate.sh [opciones]

Valida la arquitectura local sin modificar la base de datos del proyecto.

Opciones:
  --docker-build  Construye las imágenes Docker además de validar compose.
  --live-feed     Ejecuta una captura contra el feed GBFS configurado.
  -h, --help      Muestra esta ayuda.
EOF
}

for arg in "$@"; do
  case "$arg" in
    --docker-build) DOCKER_BUILD=1 ;;
    --live-feed) LIVE_FEED=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Opción desconocida: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

cd "$ROOT_DIR"

resolve_command() {
  local requested="$1"
  if [[ "$requested" == */* ]]; then
    [[ -x "$requested" ]] || return 1
    printf '%s\n' "$requested"
    return 0
  fi
  command -v "$requested"
}

if ! PYTHON_BIN="$(resolve_command "$PYTHON_BIN")"; then
  echo "No se encuentra Python: ${PYTHON_BIN:-python}" >&2
  echo "Crea el entorno con: python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2
  exit 1
fi

if ! ALEMBIC_BIN="$(resolve_command "$ALEMBIC_BIN")" || ! RUFF_BIN="$(resolve_command "$RUFF_BIN")"; then
  echo "Faltan Alembic o Ruff; instala las dependencias de desarrollo." >&2
  exit 1
fi

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/movilidad-validate.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT
export MOVILIDAD_DATABASE_PATH="$TMP_DIR/movilidad.sqlite3"
export MOVILIDAD_CORS_ORIGINS="http://testserver"

step() {
  printf '\n==> %s\n' "$1"
}

step "Comprobar archivos esenciales"
required_files=(
  pyproject.toml
  Dockerfile
  docker-compose.yml
  alembic.ini
  migrations/env.py
  migrations/versions/0001_initial.py
  migrations/versions/0002_historical_import.py
  src/movilidad/api/main.py
  src/movilidad/application/history_import.py
  src/movilidad/collector/main.py
  src/movilidad/infrastructure/db/repository.py
  src/movilidad/infrastructure/history/github.py
)
for file in "${required_files[@]}"; do
  [[ -f "$file" ]] || { echo "Falta: $file" >&2; exit 1; }
done
echo "Archivos esenciales: OK"

step "Compilación Python"
"$PYTHON_BIN" -m compileall -q src tests scripts

step "Pruebas automatizadas"
"$PYTHON_BIN" -m pytest -q

step "Lint"
"$RUFF_BIN" check src tests scripts

step "Formato"
"$RUFF_BIN" format --check src tests scripts

step "Migración Alembic en SQLite temporal"
"$ALEMBIC_BIN" upgrade head
"$PYTHON_BIN" - <<'PY'
import os
import sqlite3

expected = {
    "alembic_version", "providers", "stations", "observations", "captures",
    "capture_locks", "historical_imports",
}
with sqlite3.connect(os.environ["MOVILIDAD_DATABASE_PATH"]) as connection:
    tables = {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
missing = expected - tables
if missing:
    raise SystemExit(f"Faltan tablas tras Alembic: {sorted(missing)}")
print("Migración y tablas: OK")
PY

step "Backup SQLite"
"$PYTHON_BIN" scripts/backup_sqlite.py "$TMP_DIR/backup.sqlite3"
"$PYTHON_BIN" - <<'PY'
import os
import sqlite3

backup_path = os.path.join(os.path.dirname(os.environ["MOVILIDAD_DATABASE_PATH"]), "backup.sqlite3")
with sqlite3.connect(backup_path) as connection:
    count = connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0]
if count < 5:
    raise SystemExit("El backup no contiene las tablas esperadas")
print("Backup: OK")
PY

step "Healthcheck FastAPI"
"$PYTHON_BIN" - <<'PY'
from fastapi.testclient import TestClient

from movilidad.api.main import app

with TestClient(app) as client:
    response = client.get("/api/v1/health")
if response.status_code != 200:
    raise SystemExit(f"Healthcheck HTTP inesperado: {response.status_code}")
body = response.json()
if body.get("status") != "success" or body.get("code") != 200:
    raise SystemExit(f"Healthcheck inválido: {response.text}")
if body.get("data", {}).get("database") != "ok":
    raise SystemExit(f"Base de datos no disponible: {response.text}")
if not response.headers.get("x-request-id"):
    raise SystemExit("Falta X-Request-ID en la respuesta")
print("API health y request ID: OK")
PY

if command -v docker >/dev/null 2>&1; then
  step "Configuración Docker Compose"
  docker compose config -q
  if [[ "$DOCKER_BUILD" == "1" ]]; then
    step "Construcción de imágenes Docker"
    docker compose build api collector
  fi
else
  echo "Docker no está instalado; se omiten las comprobaciones Docker." >&2
fi

if [[ "$LIVE_FEED" == "1" ]]; then
  step "Captura GBFS real"
  "$PYTHON_BIN" -m movilidad.collector.main
fi

cat <<'EOF'

Validación completada correctamente.
EOF
