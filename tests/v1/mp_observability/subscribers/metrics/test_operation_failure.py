# SPDX-License-Identifier: Apache-2.0

"""Tests for OperationFailureMetricsSubscriber."""

# Standard
import time

# First Party
from lmcache.v1.mp_observability.event import Event, EventType
from lmcache.v1.mp_observability.event_bus import EventBus, EventBusConfig
from lmcache.v1.mp_observability.subscribers.metrics.operation_failure import (
    OperationFailureMetricsSubscriber,
)
from tests.v1.mp_observability.subscribers.metrics.counter_helpers import (
    counter_delta,
    counter_value,
    read_tagged_counters,
)

# Time for the drain thread to process queued events.
_DRAIN_WAIT = 0.15


def test_counts_failures_by_operation_and_exception_type() -> None:
    bus = EventBus(EventBusConfig(enabled=True, max_queue_size=100))
    bus.register_subscriber(OperationFailureMetricsSubscriber())
    before = read_tagged_counters()
    bus.start()
    for operation, exception_type in [
        ("lookup", "RuntimeError"),
        ("lookup", "RuntimeError"),
        ("store", "ValueError"),
    ]:
        bus.publish(
            Event(
                event_type=EventType.OPERATION_FAILED,
                metadata={
                    "operation": operation,
                    "exception_type": exception_type,
                    "message": "boom",
                },
            )
        )
    time.sleep(_DRAIN_WAIT)
    bus.stop()

    delta = counter_delta(before, read_tagged_counters())
    name = "lmcache_mp.operation_failures"
    assert (
        counter_value(delta, name, operation="lookup", exception_type="RuntimeError")
        == 2
    )
    assert (
        counter_value(delta, name, operation="store", exception_type="ValueError") == 1
    )
