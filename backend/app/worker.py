"""Entry point: `python -m app.worker` runs one queue worker until Ctrl+C / SIGTERM."""
import logging
import signal
import threading

from app.core.logging import setup_logging
from app.jobs.worker import Worker


def main() -> None:
    setup_logging()
    stop = threading.Event()

    def _stop(signum, _frame):
        logging.getLogger(__name__).info("Signal %s received; finishing the current job", signum)
        stop.set()

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)
    Worker().run_forever(stop)


if __name__ == "__main__":
    main()
