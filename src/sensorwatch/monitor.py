"""Standalone connectivity monitor; no browser or API polling is required."""

import json
import logging
import signal
from threading import Event

from sqlalchemy.exc import SQLAlchemyError

from sensorwatch.db import SessionLocal
from sensorwatch.incidents import monitor_once


def run_monitor(*, interval: int = 15, once: bool = False) -> int:
    stop = Event()
    previous = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.signal(signum, lambda *_: stop.set())
    logger = logging.getLogger("sensorwatch.monitor")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        while not stop.is_set():
            try:
                counts = monitor_once(SessionLocal)
                logger.info(json.dumps({"event": "connectivity_check", **counts}))
            except SQLAlchemyError as error:
                # Do not print connection strings, request data, or SQL parameters.
                logger.error(
                    json.dumps(
                        {
                            "event": "connectivity_check_failed",
                            "error_type": type(error).__name__,
                        }
                    )
                )
                if once:
                    return 1
            if once:
                return 0
            stop.wait(interval)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    return 0
