# SPDX-License-Identifier: Apache-2.0

"""OTel counter for failed operations: ``lmcache_mp.operation_failures``."""

# Future
from __future__ import annotations

# Third Party
from opentelemetry import metrics

# First Party
from lmcache.v1.mp_observability.event import Event, EventType
from lmcache.v1.mp_observability.event_bus import EventCallback, EventSubscriber


class OperationFailureMetricsSubscriber(EventSubscriber):
    """Counts ``OPERATION_FAILED`` events by ``operation`` and ``exception_type``."""

    def __init__(self) -> None:
        meter = metrics.get_meter("lmcache_mp.health")
        self._failure_counter = meter.create_counter(
            "lmcache_mp.operation_failures",
            description="Failed operations, tagged by operation and exception_type.",
        )

    def get_subscriptions(self) -> dict[EventType, EventCallback]:
        return {EventType.OPERATION_FAILED: self._on_failure}

    def _on_failure(self, event: Event) -> None:
        self._failure_counter.add(
            1,
            {
                "operation": event.metadata["operation"],
                "exception_type": event.metadata["exception_type"],
            },
        )
