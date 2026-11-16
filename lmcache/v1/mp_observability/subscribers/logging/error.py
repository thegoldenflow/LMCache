# SPDX-License-Identifier: Apache-2.0

"""Warning log for errors reported on construction (message + stack trace)."""

# Future
from __future__ import annotations

# First Party
from lmcache.logging import init_logger
from lmcache.v1.mp_observability.event import Event, EventType
from lmcache.v1.mp_observability.event_bus import EventCallback, EventSubscriber

logger = init_logger(__name__)


class ErrorLoggingSubscriber(EventSubscriber):
    """Logs ``ERROR_RAISED`` events at warning level with their stack trace."""

    def get_subscriptions(self) -> dict[EventType, EventCallback]:
        return {EventType.ERROR_RAISED: self._on_error}

    def _on_error(self, event: Event) -> None:
        # Catch sites already log what they catch.
        if event.metadata["source"] == "caught":
            return
        logger.warning(
            "Error raised (%s): %s\n%s",
            event.metadata["exception_type"],
            event.metadata["message"],
            event.metadata["stacktrace"],
        )
