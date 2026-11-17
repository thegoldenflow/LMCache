# SPDX-License-Identifier: Apache-2.0

"""Report failed operations to MP observability without importing it.

A failure boundary calls :func:`report_error` once it has finished handling the
failure (error response queued, stream closed). MP observability's
``init_event_bus`` registers the reporter that publishes the event.
"""

# Future
from __future__ import annotations

# Standard
from collections.abc import Callable

# First Party
from lmcache.logging import init_logger

logger = init_logger(__name__)

ErrorReporter = Callable[[BaseException, str, str], None]

_reporter: ErrorReporter | None = None


def register_error_reporter(reporter: ErrorReporter) -> None:
    """Set the callback that :func:`report_error` passes failures to.

    Args:
        reporter: Called with the error, the operation and the session id;
            replaces any previously registered reporter.
    """
    global _reporter
    _reporter = reporter


def report_error(error: BaseException, *, operation: str, session_id: str = "") -> None:
    """Report that ``operation`` failed with ``error``.

    Does nothing until a reporter is registered. An ``Exception`` from the
    reporter is logged at debug level and swallowed, so reporting never changes
    how the caller handles the failure; ``KeyboardInterrupt``, ``SystemExit``
    and cancellation propagate.

    Args:
        error: The caught exception, of any type; it is not modified.
        operation: Name of the failed operation, e.g. the RPC name.
        session_id: Request id of the failed operation; empty when unknown.
    """
    reporter = _reporter
    if reporter is None:
        return
    try:
        reporter(error, operation, session_id)
    except Exception:
        logger.debug("Failed to report a failure of %s", operation, exc_info=True)
