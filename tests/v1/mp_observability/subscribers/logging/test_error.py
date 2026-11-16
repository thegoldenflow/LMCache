# SPDX-License-Identifier: Apache-2.0

"""Tests for ErrorLoggingSubscriber."""

# Standard
import logging
import time

# Third Party
import pytest

# First Party
from lmcache.v1.mp_observability.event import Event, EventType
from lmcache.v1.mp_observability.event_bus import EventBus, EventBusConfig
from lmcache.v1.mp_observability.subscribers.logging.error import (
    ErrorLoggingSubscriber,
)

# Time for the drain thread to process queued events.
_DRAIN_WAIT = 0.15
_LOGGER_NAME = "lmcache.v1.mp_observability.subscribers.logging.error"


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _error_event(source: str) -> Event:
    return Event(
        event_type=EventType.ERROR_RAISED,
        metadata={
            "message": f"{source}-message",
            "exception_type": "CorruptEncodedKVError",
            "stacktrace": "the-stacktrace",
            "source": source,
        },
    )


@pytest.mark.parametrize(
    ("source", "logged"), [("constructed", True), ("caught", False)]
)
def test_logs_constructed_errors_only(source: str, logged: bool) -> None:
    bus = EventBus(EventBusConfig(enabled=True, max_queue_size=100))
    bus.register_subscriber(ErrorLoggingSubscriber())
    handler = _CaptureHandler()
    lg = logging.getLogger(_LOGGER_NAME)
    lg.addHandler(handler)
    try:
        bus.start()
        bus.publish(_error_event(source))
        time.sleep(_DRAIN_WAIT)
        bus.stop()
    finally:
        lg.removeHandler(handler)

    messages = [r.getMessage() for r in handler.records if r.levelno == logging.WARNING]
    if logged:
        assert len(messages) == 1
        assert "constructed-message" in messages[0]
        assert "CorruptEncodedKVError" in messages[0]
        assert "the-stacktrace" in messages[0]
    else:
        assert messages == []
