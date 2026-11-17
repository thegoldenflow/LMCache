# SPDX-License-Identifier: Apache-2.0

"""Tests for ``report_error`` and the ``OPERATION_FAILED`` publisher."""

# Standard
from unittest.mock import Mock
import time

# Third Party
import pytest

# First Party
from lmcache.v1.common.error_reporting import report_error
from lmcache.v1.common.timeouts import LMCacheTimeoutError
from lmcache.v1.mp_observability.event import Event, EventType
from lmcache.v1.mp_observability.event_bus import (
    EventBus,
    EventBusConfig,
    init_event_bus,
)

# Time for the drain thread to process queued events.
_DRAIN_WAIT = 0.15


@pytest.fixture(autouse=True)
def _restore_global_bus():
    yield
    init_event_bus(EventBusConfig(enabled=False))


def _started_bus(*event_types: EventType) -> tuple[EventBus, list[Event]]:
    bus = init_event_bus(EventBusConfig(enabled=True, max_queue_size=100))
    captured: list[Event] = []
    for event_type in event_types:
        bus.subscribe(event_type, captured.append)
    bus.start()
    return bus, captured


class _ReadOnlyError(Exception):
    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(name)


class _UnprintableError(Exception):
    def __str__(self) -> str:
        raise RuntimeError("no message")


def test_reports_an_unmodifiable_exception() -> None:
    bus, captured = _started_bus(EventType.OPERATION_FAILED)
    try:
        raise _ReadOnlyError("disk gone")
    except _ReadOnlyError as exc:
        report_error(exc, operation="lookup", session_id="req-1")
    time.sleep(_DRAIN_WAIT)
    bus.stop()

    [event] = captured
    assert event.session_id == "req-1"
    assert event.metadata == {
        "operation": "lookup",
        "exception_type": "_ReadOnlyError",
        "message": "disk gone",
    }


def test_a_reported_timeout_also_keeps_its_timeout_event() -> None:
    bus, captured = _started_bus(EventType.TIMEOUT_RAISED, EventType.OPERATION_FAILED)
    try:
        raise LMCacheTimeoutError("lookup timed out")
    except LMCacheTimeoutError as exc:
        report_error(exc, operation="lookup")
    time.sleep(_DRAIN_WAIT)
    bus.stop()

    assert [event.event_type for event in captured] == [
        EventType.TIMEOUT_RAISED,
        EventType.OPERATION_FAILED,
    ]


def test_formatting_and_publish_failures_are_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = init_event_bus(EventBusConfig(enabled=True, max_queue_size=100))
    report_error(_UnprintableError(), operation="lookup")

    publish = Mock(side_effect=RuntimeError("bus is broken"))
    monkeypatch.setattr(bus, "publish", publish)
    report_error(ValueError("bad key"), operation="lookup")
    publish.assert_called_once()
