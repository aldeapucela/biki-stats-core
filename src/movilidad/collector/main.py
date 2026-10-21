import argparse
import logging
import signal
from threading import Event

from movilidad.application.capture import run_capture
from movilidad.core.config import Settings, get_settings
from movilidad.core.logging import configure_logging

logger = logging.getLogger(__name__)


def run_loop(settings: Settings, stop: Event) -> None:
    """Captura inmediatamente y espera el intervalo después de cada intento."""
    while not stop.is_set():
        try:
            run_capture(settings)
        except Exception:
            logger.exception("Error en collector; se reintentará tras el intervalo")
        if stop.wait(settings.capture_interval_seconds):
            break


def run() -> None:
    parser = argparse.ArgumentParser(description="Captura de datos GBFS de BIKI")
    parser.add_argument("--loop", action="store_true", help="Ejecutar capturas periódicamente")
    args = parser.parse_args()
    settings = get_settings()
    configure_logging(settings.log_level)
    if not args.loop:
        run_capture(settings)
        return

    stop = Event()

    def request_stop(signum, frame) -> None:
        # No interrumpir la transacción/captura activa: terminarla antes de salir.
        stop.set()

    previous = {sig: signal.signal(sig, request_stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        logger.info("Collector periódico iniciado")
        run_loop(settings, stop)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        logger.info("Collector periódico detenido")


if __name__ == "__main__":
    run()
