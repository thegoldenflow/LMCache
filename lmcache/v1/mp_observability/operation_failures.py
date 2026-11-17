# SPDX-License-Identifier: Apache-2.0

"""Publishes an ``OPERATION_FAILED`` event for each failure passed to ``report_error``.

The entry point is :func:`lmcache.v1.common.error_reporting.report_error`;
``init_event_bus`` registers :func:`publish_operation_failure` as its reporter.
"""

# Future
from __future__ import annotations

# First Party
from lmcache.v1.mp_observability.event import Event, EventType
from lmcache.v1.mp_observability.event_bus import (
    get_event_bus,
    is_observability_enabled,
)


def publish_operation_failure(
    error: BaseException, operation: str, session_id: str
) -> None:
    """Publish an ``OPERATION_FAILED`` event for ``error``.

    Skipped when observability is disabled. Failures propagate to
    ``report_error``, which swallows them.

    Args:
        error: The exception the operation failed with.
        operation: Name of the failed operation.
        session_id: Request id of the failed operation; empty when unknown.
    """
    if not is_observability_enabled():
        return
    get_event_bus().publish(
        Event(
            event_type=EventType.OPERATION_FAILED,
            # No traceback: the boundaries already log it, and formatting one
            # holds the GIL for milliseconds.
            metadata={
                "operation": operation,
                "exception_type": type(error).__name__,
                "message": str(error),
            },
            session_id=session_id,
        )
    )
