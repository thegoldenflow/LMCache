# SPDX-License-Identifier: Apache-2.0

"""Tests for ErrorMetricsSubscriber."""

# Standard
import time

# First Party
from lmcache.v1.mp_observability.event import Event, EventType
from lmcache.v1.mp_observability.event_bus import EventBus, EventBusConfig
from lmcache.v1.mp_observability.subscribers.metrics.error import (
    ErrorMetricsSubscriber,
)
from tests.v1.mp_observability.subscribers.metrics.counter_helpers import (
    counter_delta,
    counter_value,
    read_tagged_counters,
)

# Time for the drain thread to process queued events.
_DRAIN_WAIT = 0.15


def _publish(bus: EventBus, exception_type: str, source: str) -> None:
    bus.publish(
        Event(
            event_type=EventType.ERROR_RAISED,
            metadata={
                "message": "boom",
                "exception_type": exception_type,
                "stacktrace": "trace",
                "source": source,
            },
        )
    )


def test_counts_by_exception_type_and_source() -> None:
    bus = EventBus(EventBusConfig(enabled=True, max_queue_size=100))
    bus.register_subscriber(ErrorMetricsSubscriber())
    before = read_tagged_counters()
    bus.start()
    _publish(bus, "KeyError", "caught")
    _publish(bus, "KeyError", "caught")
    _publish(bus, "CorruptEncodedKVError", "constructed")
    time.sleep(_DRAIN_WAIT)
    bus.stop()

    delta = counter_delta(before, read_tagged_counters())
    assert (
        counter_value(
            delta, "lmcache_mp.errors", exception_type="KeyError", source="caught"
        )
        == 2
    )
    assert (
        counter_value(
            delta,
            "lmcache_mp.errors",
            exception_type="CorruptEncodedKVError",
            source="constructed",
        )
        == 1
    )
