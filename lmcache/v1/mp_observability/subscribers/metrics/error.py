# SPDX-License-Identifier: Apache-2.0

"""OTel counter for reported errors: ``lmcache_mp.errors`` by type and source."""

# Future
from __future__ import annotations

# Third Party
from opentelemetry import metrics

# First Party
from lmcache.v1.mp_observability.event import Event, EventType
from lmcache.v1.mp_observability.event_bus import EventCallback, EventSubscriber


class ErrorMetricsSubscriber(EventSubscriber):
    """Maintains an OTel counter for ``ERROR_RAISED`` events."""

    def __init__(self) -> None:
        meter = metrics.get_meter("lmcache_mp.health")
        self._error_counter = meter.create_counter(
            "lmcache_mp.errors",
            description="Errors reported, tagged by exception_type and source.",
        )

    def get_subscriptions(self) -> dict[EventType, EventCallback]:
        return {EventType.ERROR_RAISED: self._on_error}

    def _on_error(self, event: Event) -> None:
        self._error_counter.add(
            1,
            {
                "exception_type": event.metadata["exception_type"],
                "source": event.metadata["source"],
            },
        )
