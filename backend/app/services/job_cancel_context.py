"""Thread-local cancel event for propagating job cancellation into subprocess calls."""
import threading

_thread_local = threading.local()


def get_cancel_event() -> threading.Event | None:
    return getattr(_thread_local, "cancel_event", None)


def set_cancel_event(event: threading.Event) -> None:
    _thread_local.cancel_event = event


def clear_cancel_event() -> None:
    _thread_local.cancel_event = None
