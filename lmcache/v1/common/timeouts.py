# SPDX-License-Identifier: Apache-2.0

"""Timeout error raised by client and server code.

Raise :class:`LMCacheTimeoutError` instead of the builtin ``TimeoutError``. The
``ban-raw-timeout-error`` pre-commit hook enforces this across ``lmcache/``.
"""

# First Party
from lmcache.v1.common.observable_error import ObservableError


class LMCacheTimeoutError(ObservableError, TimeoutError):
    """``TimeoutError`` that is passed to the error observer on construction.

    Subclasses the builtin, so existing ``except TimeoutError`` handlers still
    catch it.

    Args:
        message: Timeout description.
        session_id: Request id for correlating the timeout with its originating
            request; empty when unavailable.
    """

    def __init__(self, message: str, *, session_id: str = "") -> None:
        super().__init__(message, session_id=session_id)
