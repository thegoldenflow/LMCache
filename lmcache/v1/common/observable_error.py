# SPDX-License-Identifier: Apache-2.0

"""Errors reported to MP observability without importing it.

:class:`ObservableError` reports itself when constructed; :func:`report_error`
reports any exception where it is caught. Both go to the single observer that
MP observability's ``init_event_bus`` registers.
"""

# Future
from __future__ import annotations

# Standard
from collections.abc import Callable
import contextlib

ErrorObserver = Callable[[BaseException, str, bool], None]

_observer: ErrorObserver | None = None


def register_error_observer(observer: ErrorObserver) -> None:
    """Set the callback that observable errors are passed to.

    The observer is called with ``(error, session_id, caught)`` and replaces any
    previously registered one. An exception it raises propagates out of
    ``ObservableError.__init__`` but not out of :func:`report_error`.

    Args:
        observer: The callback to register.
    """
    global _observer
    _observer = observer


def report_error(error: BaseException, *, session_id: str = "") -> None:
    """Report ``error`` from the place it was caught; never raises.

    Args:
        error: The caught exception, of any type.
        session_id: Request id of the failing request; empty when unavailable.
    """
    observer = _observer
    if observer is None:
        return
    with contextlib.suppress(Exception):
        observer(error, session_id, True)


class ObservableError(Exception):
    """Exception passed to the registered observer on construction.

    Combine it with a builtin base when callers catch that builtin, e.g.
    ``class MyError(ObservableError, RuntimeError)``.

    Args:
        *args: Passed to the base exception; ``args[0]`` is the message.
        session_id: Request id for correlating the error with its originating
            request; empty when unavailable.
    """

    def __init__(self, *args: object, session_id: str = "") -> None:
        super().__init__(*args)
        if _observer is not None:
            _observer(self, session_id, False)
