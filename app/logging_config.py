import asyncio
import logging
import sys

_listeners: list[asyncio.Queue] = []


class _BroadcastHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        entry = {
            "time": logging.Formatter().formatTime(record, "%H:%M:%S"),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        for q in list(_listeners):
            try:
                q.put_nowait(entry)
            except asyncio.QueueFull:
                pass


def add_log_listener(q: asyncio.Queue) -> None:
    _listeners.append(q)


def remove_log_listener(q: asyncio.Queue) -> None:
    try:
        _listeners.remove(q)
    except ValueError:
        pass


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )
    # Suppress uvicorn's per-request access log — our middleware handles that
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    broadcast = _BroadcastHandler()
    broadcast.setLevel(logging.INFO)
    logging.getLogger().addHandler(broadcast)
