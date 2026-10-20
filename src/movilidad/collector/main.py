from movilidad.application.capture import run_capture
from movilidad.core.config import get_settings
from movilidad.core.logging import configure_logging


def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    run_capture(settings)


if __name__ == "__main__":
    run()
