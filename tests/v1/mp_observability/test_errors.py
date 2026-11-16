# SPDX-License-Identifier: Apache-2.0

"""Tests for observable errors and their MP observability events.

``LMCacheTimeoutError`` stays a drop-in ``TimeoutError`` that publishes
``TIMEOUT_RAISED``; other ``ObservableError`` subclasses and exceptions passed
to ``report_error`` publish ``ERROR_RAISED``.
"""

# Standard
from unittest.mock import Mock
import subprocess
import sys
import time

# Third Party
import pytest

# First Party
from lmcache.v1.common import observable_error
from lmcache.v1.common.observable_error import ObservableError, report_error
from lmcache.v1.common.timeouts import LMCacheTimeoutError
from lmcache.v1.mp_observability.event import Event, EventType
from lmcache.v1.mp_observability.event_bus import (
    EventBusConfig,
    init_event_bus,
)

# Time for the drain thread to process queued events.
_DRAIN_WAIT = 0.15


@pytest.fixture(autouse=True)
def _restore_global_bus():
    """Reset the global EventBus to the disabled default after each test."""
    yield
    init_event_bus(EventBusConfig(enabled=False))


class TestLMCacheTimeoutErrorType:
    def test_is_timeout_error_subclass(self) -> None:
        assert issubclass(LMCacheTimeoutError, TimeoutError)

    def test_caught_by_except_timeout_error(self) -> None:
        init_event_bus(EventBusConfig(enabled=False))
        with pytest.raises(TimeoutError):
            raise LMCacheTimeoutError("boom")

    def test_message_preserved(self) -> None:
        init_event_bus(EventBusConfig(enabled=False))
        err = LMCacheTimeoutError("the message")
        assert str(err) == "the message"


class TestLMCacheTimeoutErrorEmission:
    def test_no_event_when_observability_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bus = init_event_bus(EventBusConfig(enabled=False))
        captured: list[Event] = []
        bus.subscribe(EventType.TIMEOUT_RAISED, captured.append)
        format_stack = Mock(return_value=[])
        monkeypatch.setattr("traceback.format_stack", format_stack)
        bus.start()  # no-op when disabled
        LMCacheTimeoutError("nope")
        time.sleep(_DRAIN_WAIT)
        bus.stop()
        assert captured == []
        format_stack.assert_not_called()

    def test_publishes_event_when_enabled(self) -> None:
        bus = init_event_bus(EventBusConfig(enabled=True, max_queue_size=100))
        captured: list[Event] = []
        bus.subscribe(EventType.TIMEOUT_RAISED, captured.append)
        bus.start()
        LMCacheTimeoutError("timed out!", session_id="req-7")
        time.sleep(_DRAIN_WAIT)
        bus.stop()

        assert len(captured) == 1
        event = captured[0]
        assert event.event_type == EventType.TIMEOUT_RAISED
        assert event.session_id == "req-7"
        assert event.metadata["message"] == "timed out!"
        assert event.metadata["exception_type"] == "LMCacheTimeoutError"
        # The construction stack should be captured and end at the caller.
        assert "test_publishes_event_when_enabled" in event.metadata["stacktrace"]
        assert "timeouts.py" not in event.metadata["stacktrace"]

    def test_subclass_reports_its_own_type(self) -> None:
        class MyTimeout(LMCacheTimeoutError):
            pass

        bus = init_event_bus(EventBusConfig(enabled=True, max_queue_size=100))
        captured: list[Event] = []
        bus.subscribe(EventType.TIMEOUT_RAISED, captured.append)
        bus.start()
        MyTimeout("sub")
        time.sleep(_DRAIN_WAIT)
        bus.stop()

        assert len(captured) == 1
        assert captured[0].metadata["exception_type"] == "MyTimeout"

    def test_publish_failure_still_raises_the_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bus = init_event_bus(EventBusConfig(enabled=True, max_queue_size=100))

        def broken_publish(event: Event) -> None:
            raise RuntimeError("bus is broken")

        monkeypatch.setattr(bus, "publish", broken_publish)
        with pytest.raises(LMCacheTimeoutError, match="still a timeout"):
            raise LMCacheTimeoutError("still a timeout")


class _PlainError(ObservableError):
    pass


class _ErrorWithInit(ObservableError, RuntimeError):
    def __init__(self, key: str) -> None:
        super().__init__(f"bad {key}")
        self.key = key


def _fail_lookup() -> None:
    {}["missing"]


def _collect(action, *event_types: EventType) -> list[Event]:
    bus = init_event_bus(EventBusConfig(enabled=True, max_queue_size=100))
    captured: list[Event] = []
    for event_type in event_types:
        bus.subscribe(event_type, captured.append)
    bus.start()
    action()
    time.sleep(_DRAIN_WAIT)
    bus.stop()
    return captured


def _last_frame(stacktrace: str) -> str:
    return [ln for ln in stacktrace.splitlines() if ln.lstrip().startswith("File ")][
        -1
    ]


class TestObservableErrorEmission:
    def test_non_timeout_error_publishes_error_raised(self) -> None:
        events = _collect(
            lambda: _PlainError("bad", session_id="req-1"),
            EventType.ERROR_RAISED,
            EventType.TIMEOUT_RAISED,
        )

        assert len(events) == 1
        event = events[0]
        assert event.event_type == EventType.ERROR_RAISED
        assert event.session_id == "req-1"
        assert event.metadata["message"] == "bad"
        assert event.metadata["exception_type"] == "_PlainError"
        assert event.metadata["source"] == "constructed"

    def test_stack_ends_where_the_error_is_constructed(self) -> None:
        def construct_here() -> None:
            _ErrorWithInit("k")

        events = _collect(construct_here, EventType.ERROR_RAISED)

        assert "in construct_here" in _last_frame(events[0].metadata["stacktrace"])

    def test_timeout_keeps_its_own_event_and_metadata(self) -> None:
        events = _collect(
            lambda: LMCacheTimeoutError("t"),
            EventType.ERROR_RAISED,
            EventType.TIMEOUT_RAISED,
        )

        assert [event.event_type for event in events] == [EventType.TIMEOUT_RAISED]
        assert set(events[0].metadata) == {"message", "exception_type", "stacktrace"}


class TestReportError:
    def test_caught_error_publishes_its_traceback(self) -> None:
        def catch() -> None:
            try:
                _fail_lookup()
            except KeyError as exc:
                report_error(exc, session_id="req-2")

        events = _collect(catch, EventType.ERROR_RAISED)

        assert len(events) == 1
        event = events[0]
        assert event.session_id == "req-2"
        assert event.metadata["exception_type"] == "KeyError"
        assert event.metadata["source"] == "caught"
        assert "in _fail_lookup" in _last_frame(event.metadata["stacktrace"])

    def test_each_error_is_reported_once(self) -> None:
        def construct_then_catch_twice() -> None:
            error = _PlainError("once")
            report_error(error)
            report_error(error)

        events = _collect(construct_then_catch_twice, EventType.ERROR_RAISED)

        assert [event.metadata["source"] for event in events] == ["constructed"]

    def test_never_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            observable_error, "_observer", Mock(side_effect=RuntimeError("broken"))
        )
        report_error(ValueError("x"))


def test_common_errors_do_not_load_mp_observability() -> None:
    script = r"""
import sys

from lmcache.v1.common.observable_error import report_error
from lmcache.v1.common.timeouts import LMCacheTimeoutError

LMCacheTimeoutError("t")
report_error(ValueError("v"))
loaded = [m for m in sys.modules if m.startswith("lmcache.v1.mp_observability")]
assert loaded == [], loaded
"""
    subprocess.run([sys.executable, "-c", script], check=True)
