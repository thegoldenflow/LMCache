# Observability-aware errors (`errors.py`)

`lmcache/v1/common/timeouts.py` defines `LMCacheTimeoutError`, a plain
timeout exception; `errors.py` defines `publish_timeout`, which server code
calls to report one to the MP observability EventBus. The class is the single
place timeouts in `lmcache/` should be raised
from; the `ban-raw-timeout-error` pre-commit hook enforces this by rejecting
any bare `raise TimeoutError(...)` / `raise asyncio.TimeoutError(...)` under
`lmcache/`.

## Why

Timeouts are the most common "something is stuck" failure in MP mode (MQ
round-trips, GPU transfer waits, adapter drains, NIXL handshakes). Before this,
each site raised the built-in `TimeoutError`, which left no trace in the
observability stack — operators only learned of a timeout if the surrounding
code happened to log it. Routing every timeout through one class, reported by
one publisher, makes them uniformly observable (counter + log + trace).

## Contract

`LMCacheTimeoutError(message: str, *, session_id: str = "")`

- **Subclass of the built-in `TimeoutError`.** Every existing
  `except TimeoutError` handler continues to catch it unchanged, so swapping a
  raw `raise TimeoutError(...)` for `raise LMCacheTimeoutError(...)` is
  behaviour-preserving. (On Python 3.11+ `asyncio.TimeoutError` is the same
  type, so `except asyncio.TimeoutError` catches it too; on 3.10 it does not —
  do not rely on the async alias for catching these raises.)
- **Reports nothing itself.** Constructing or raising it publishes no event and
  imports no MP observability module. Server code calls
  `publish_timeout(error)` right before raising it, or in the handler that
  catches one from a messaging future; that publishes one
  `EventType.TIMEOUT_RAISED` event (see [EVENTS.md](EVENTS.md)) to the global
  EventBus via `get_event_bus()`.
- **Zero-cost when observability is off.** `publish_timeout` is guarded by
  `is_observability_enabled()`, which is only `True` inside the MP server
  process; otherwise it returns before capturing the stack.
- **A publish failure does not escape.** A failure to build or publish the
  event is swallowed and logged at debug level: observability must never break
  error handling.
- **`session_id`** is kept on the error and forwarded onto the event so the
  timeout span can nest under the originating request's root span. Pass it
  where the raise site has a request/`IPCCacheServerKey.request_id` in scope
  (e.g. `shm.prepare_store`); leave it empty otherwise.

## What gets recorded

The emitted `TIMEOUT_RAISED` event carries `message`, `exception_type`, and a
captured `stacktrace` (the stack at the `publish_timeout` call minus its own
frame, following the OTel `exception.*` semantic conventions). Three subscribers
consume it, registered by `init_observability` under the usual
metrics/logging/tracing toggles:

| Subscriber | Output | Default |
|---|---|---|
| `TimeoutMetricsSubscriber` | `lmcache_mp.timeouts` counter, tagged `exception_type` | on (`metrics_enabled`) |
| `TimeoutLoggingSubscriber` | `WARNING` log with message + stack trace | on (`logging_enabled`) |
| `TimeoutTracingSubscriber` | zero-duration `timeout` span with an `exception` event + ERROR status | on when tracing enabled |

The tracing subscriber records the exception the same way OTel's
`Span.record_exception` would (an `exception` span event with `exception.type`
/ `exception.message` / `exception.stacktrace` plus ERROR status), driven from
the EventBus drain thread where the original exception object is no longer
available.

## Extending

To make another server-side timeout observable, raise `LMCacheTimeoutError`
instead of the built-in and call `publish_timeout` on it first. To add a new
observable error family, define a sibling subclass of
the relevant built-in here, add a matching `EventType`, and add subscriber(s)
that consume it — mirroring the timeout wiring.
