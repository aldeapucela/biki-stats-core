import signal
import sys
from threading import Event, Thread

import pytest

from movilidad.collector import main
from movilidad.core.config import Settings


def test_immediate_capture_interval_and_recovery(monkeypatch, caplog):
    events = []

    class Stop:
        def is_set(self):
            return False

        def wait(self, seconds):
            events.append(("wait", seconds))
            return len(events) >= 4

    def capture(settings):
        events.append("capture")
        if len(events) == 1:
            raise RuntimeError("proveedor caído")

    monkeypatch.setattr(main, "run_capture", capture)
    main.run_loop(Settings(capture_interval_seconds=17), Stop())
    assert events == ["capture", ("wait", 17), "capture", ("wait", 17)]
    assert "se reintentará" in caplog.text


def test_stop_before_start_does_not_capture(monkeypatch):
    stop = Event()
    stop.set()
    monkeypatch.setattr(main, "run_capture", lambda _: pytest.fail("No debe capturar"))
    main.run_loop(Settings(), stop)


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
@pytest.mark.parametrize("during_capture", [True, False])
def test_signal_stops_cleanly_and_restores_handlers(monkeypatch, sig, during_capture):
    events = []
    waiting = Event()
    previous = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    real_event = Event

    class ObservedEvent:
        def __init__(self):
            self.event = real_event()

        def set(self):
            self.event.set()

        def is_set(self):
            return self.event.is_set()

        def wait(self, seconds):
            waiting.set()
            return self.event.wait(seconds)

    def capture(settings):
        events.append("start")
        if during_capture:
            signal.raise_signal(sig)
        events.append("finished")

    def stop_when_waiting():
        waiting.wait(2)
        # También detiene el bucle si falla la entrada en espera: evita colgar el test.
        signal.getsignal(sig)(sig, None)

    monkeypatch.setattr(main, "Event", ObservedEvent)
    monkeypatch.setattr(main, "configure_logging", lambda _: None)
    monkeypatch.setattr(main, "run_capture", capture)
    monkeypatch.setattr(sys, "argv", ["movilidad-collector", "--loop"])
    worker = Thread(target=stop_when_waiting, daemon=True) if not during_capture else None
    if worker:
        worker.start()
    main.run()
    if worker:
        worker.join(2)
        assert not worker.is_alive()
    assert events == ["start", "finished"]
    assert {s: signal.getsignal(s) for s in previous} == previous


def test_one_shot_preserves_error(monkeypatch):
    calls = []

    def capture(settings):
        calls.append(settings)
        raise RuntimeError("fallo puntual")

    monkeypatch.setattr(main, "configure_logging", lambda _: None)
    monkeypatch.setattr(main, "run_capture", capture)
    monkeypatch.setattr(sys, "argv", ["movilidad-collector"])
    with pytest.raises(RuntimeError, match="fallo puntual"):
        main.run()
    assert len(calls) == 1
