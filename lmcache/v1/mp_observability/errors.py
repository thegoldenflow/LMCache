# SPDX-License-Identifier: Apache-2.0

"""Publishes a ``TIMEOUT_RAISED`` event for an ``LMCacheTimeoutError``.

The error is defined in :mod:`lmcache.v1.common.timeouts` and reports nothing
itself; server code calls :func:`publish_timeout` where it raises or catches one.
"""

# Future
from __future__ import annotations

# Standard
from typing import TYPE_CHECKING
import traceback

# First Party
from lmcache.logging import init_logger
from lmcache.v1.mp_observability.event import Event, EventType
from lmcache.v1.mp_observability.event_bus import (
    get_event_bus,
    is_observability_enabled,
)

if TYPE_CHECKING:
    # First Party
    from lmcache.v1.common.timeouts import LMCacheTimeoutError

logger = init_logger(__name__)


def publish_timeout(error: LMCacheTimeoutError) -> None:
    """Publish a ``TIMEOUT_RAISED`` event for ``error``.

    Skipped (no event, no stack capture) when observability is disabled. A
    failure to build or publish the event is logged and swallowed; a failure
    to capture the stack propagates.

    Args:
        error: The timeout about to be raised, or just caught.
    """
    if not is_observability_enabled():
        return
    # Stack at the caller, minus this frame.
    stacktrace = "".join(traceback.format_stack()[:-1])
    try:
        get_event_bus().publish(
            Event(
                event_type=EventType.TIMEOUT_RAISED,
                metadata={
                    # The constructor argument; a subclass may override __str__.
                    "message": error.args[0],
                    "exception_type": type(error).__name__,
                    "stacktrace": stacktrace,
                },
                session_id=error.session_id,
            )
        )
    except Exception:
        logger.debug("Failed to publish TIMEOUT_RAISED event", exc_info=True)
