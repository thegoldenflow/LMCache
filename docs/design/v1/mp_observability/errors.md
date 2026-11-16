# Observability-aware errors (`errors.py`)

`lmcache/v1/common/timeouts.py` defines `LMCacheTimeoutError`, a
timeout exception that reports itself to the MP observability EventBus when it
is constructed. It is the single place timeouts in `lmcache/` should be raised
from; the `ban-raw-timeout-error` pre-commit hook enforces this by rejecting
any bare `raise TimeoutError(...)` / `raise asyncio.TimeoutError(...)` under
`lmcache/`.

## Why

Timeouts are the most common "something is stuck" failure in MP mode (MQ
round-trips, GPU transfer waits, adapter drains, NIXL handshakes). Before this,
each site raised the built-in `TimeoutError`, which left no trace in the
observability stack — operators only learned of a timeout if the surrounding
code happened to log it. Routing every timeout through one class makes them
uniformly observable (counter + log + trace) without touching each call site
beyond the class swap.

## Contract

`LMCacheTimeoutError(message: str, *, session_id: str = "")`

- **Subclass of the built-in `TimeoutError`.** Every existing
  `except TimeoutError` handler continues to catch it unchanged, so swapping a
  raw `raise TimeoutError(...)` for `raise LMCacheTimeoutError(...)` is
  behaviour-preserving. (On Python 3.11+ `asyncio.TimeoutError` is the same
  type, so `except asyncio.TimeoutError` catches it too; on 3.10 it does not —
  do not rely on the async alias for catching these raises.)
- **Emits on construction, not on raise.** Once `init_event_bus()` has
  registered `publish_error` from `errors.py`, `__init__` publishes one
  `EventType.TIMEOUT_RAISED` event (see [EVENTS.md](EVENTS.md)) to the global
  EventBus via `get_event_bus()`.
- **Zero-cost when observability is off.** The emit path is guarded by
  `is_observability_enabled()`, which is only `True` inside the MP server
  process. In single-process / CLI mode the constructor does nothing beyond
  `super().__init__(message)` (one boolean check) — no event, no stack-trace
  capture, no OTel dependency exercised.
- **Never raises from `__init__`.** Any failure to publish is swallowed and
  logged at debug level: observability must never break error handling.
- **`session_id`** is forwarded onto the event so the timeout span can nest
  under the originating request's root span. Pass it where the raise site has a
  request/`IPCCacheServerKey.request_id` in scope (e.g. `shm.prepare_store`);
  leave it empty otherwise.

## What gets recorded

The emitted `TIMEOUT_RAISED` event carries `message`, `exception_type`, and a
captured `stacktrace` (the construction stack, ending at the frame that
constructed the error, following the OTel `exception.*` semantic conventions). Three subscribers
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

To make another timeout observable, raise `LMCacheTimeoutError` instead of the
built-in. Other errors have two entry points in
`lmcache/v1/common/observable_error.py`, which imports nothing from MP
observability and is safe on the client:

- **`ObservableError`** — derive an LMCache error class from it (next to its
  builtin base, e.g. `class CorruptEncodedKVError(ObservableError, CodecError)`)
  and every construction publishes `ERROR_RAISED` with `source="constructed"`.
  Opt in only classes whose every construction is worth counting: the stack
  capture costs far more than constructing a plain exception.
- **`report_error(exc, session_id=...)`** — call it where an exception of any
  type, including builtin and third-party ones, is caught. It publishes
  `ERROR_RAISED` with `source="caught"` and the exception's own traceback, never
  raises, and skips exceptions that were already reported.

`ErrorMetricsSubscriber` counts both (`lmcache_mp.errors`, tagged
`exception_type` and `source`); `ErrorLoggingSubscriber` logs only constructed
errors, since catch sites already log what they catch.
