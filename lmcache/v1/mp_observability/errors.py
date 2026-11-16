# SPDX-License-Identifier: Apache-2.0

"""Publishes events for errors reported through ``common.observable_error``.

``init_event_bus`` registers :func:`publish_error` as the error observer. A new
``LMCacheTimeoutError`` becomes ``TIMEOUT_RAISED``; any other new
``ObservableError``, and any exception passed to ``report_error``, becomes
``ERROR_RAISED``.
"""

# Future
from __future__ import annotations

# Standard
from types import FrameType
from typing import Any
import inspect
import traceback

# First Party
from lmcache.logging import init_logger
from lmcache.v1.common.timeouts import LMCacheTimeoutError
from lmcache.v1.mp_observability.event import Event, EventType
from lmcache.v1.mp_observability.event_bus import (
    get_event_bus,
    is_observability_enabled,
)

logger = init_logger(__name__)

_REPORTED_ATTR = "_lmcache_error_reported"


def publish_error(error: BaseException, session_id: str, caught: bool) -> None:
    """Publish one event for ``error``, at most once per exception object.

    Skipped (no event, no stack capture) when observability is disabled. A
    failure to build or publish the event is logged and swallowed; a failure
    to capture the construction stack propagates.

    Args:
        error: The exception being constructed, or the one that was caught.
        session_id: Request id of the error; empty when unavailable.
        caught: Whether ``error`` comes from ``report_error`` rather than
            ``ObservableError.__init__``.
    """
    if not is_observability_enabled() or getattr(error, _REPORTED_ATTR, False):
        return
    if caught:
        stacktrace = "".join(traceback.format_exception(error))
        message: Any = str(error)
    else:
        stacktrace = "".join(traceback.format_stack(_construction_frame(error)))
        # The constructor argument; a subclass may override __str__.
        message = error.args[0] if error.args else ""
    is_timeout = not caught and isinstance(error, LMCacheTimeoutError)
    metadata: dict[str, Any] = {
        "message": message,
        "exception_type": type(error).__name__,
        "stacktrace": stacktrace,
    }
    if not is_timeout:
        metadata["source"] = "caught" if caught else "constructed"
    event_type = EventType.TIMEOUT_RAISED if is_timeout else EventType.ERROR_RAISED
    try:
        setattr(error, _REPORTED_ATTR, True)
        get_event_bus().publish(
            Event(event_type=event_type, metadata=metadata, session_id=session_id)
        )
    except Exception:
        logger.debug("Failed to publish %s event", event_type.name, exc_info=True)


def _construction_frame(error: BaseException) -> FrameType | None:
    """Return the frame that constructed ``error``, outside its ``__init__`` chain."""
    frame = inspect.currentframe()
    while frame is not None and not _is_init_of(frame, error):
        frame = frame.f_back
    while frame is not None and _is_init_of(frame, error):
        frame = frame.f_back
    return frame


def _is_init_of(frame: FrameType, error: BaseException) -> bool:
    return frame.f_code.co_name == "__init__" and frame.f_locals.get("self") is error
