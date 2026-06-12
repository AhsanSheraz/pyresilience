# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-06-12

### Added
- `ignore_on` on `RetryConfig` and `CircuitBreakerConfig` — exception types that are never retried and never counted as circuit-breaker failures; takes precedence over `retry_on` / `error_types`, enabling fail-fast behaviour on terminal client errors such as authentication failures and quota exhaustion.
- `delay_func` on `RetryConfig` — optional callable that receives the triggering exception (or result) and the current attempt number and returns a delay in seconds; return `None` to fall back to the configured exponential backoff. Designed to honour HTTP `Retry-After` headers without requiring custom retry logic outside the decorator.
- `pyresilience.contrib.http` — stdlib-only contrib module providing `retry_on_status()` (duck-typed predicate compatible with requests, httpx, and aiohttp response objects) and `retry_after_delay()` (parses `Retry-After` headers, both delta-seconds and HTTP-date forms, for use as a `delay_func`).
- `llm_policy()` preset — rate limiter + retry with 429-aware, `Retry-After`-honoring backoff + timeout + circuit breaker, tuned for LLM / HTTP API calls; exported from `pyresilience` and `pyresilience.presets`.

## [0.3.2] - 2026-03-21

### Changed
- Removed a dead code branch in the sync timeout thread-interruption path (`_interrupt_thread`); no functional changes.

## [0.3.1] - 2026-03-19

### Added
- Context propagation: `resilience_context` ContextVar carries request-scoped metadata (trace ID, request ID) into every `ResilienceEvent.context` field
- Per-attempt vs total-deadline timeout: `TimeoutConfig(per_attempt=False)` enforces a single deadline across all retry attempts
- Retry budget: `RetryBudget` + `RetryBudgetConfig` shared token pool preventing cascading retries across decorated functions
- `health_check(registry)` summarizing circuit breaker states, in-flight calls, and rate limiter availability
- `OpenTelemetryListener` and `PrometheusListener` under `pyresilience.contrib`
- Graceful shutdown: `shutdown()` drains in-flight calls and releases thread pool resources
- `ResilienceEvent.duration` populated on SUCCESS events

### Fixed
- `AsyncResultCache.put()` race condition; per-key cache locks evicted with their entries (memory leak)
- `PrometheusListener` now observes call duration on SUCCESS events
- Replaced deprecated `asyncio.iscoroutinefunction` usage for Python 3.14+ compatibility
- `ResilienceRegistry.get_executor(name)` exposes executors for runtime introspection

## [0.3.0] - 2026-03-19

### Added
- Circuit breaker manual control: `reset()`, `force_open()`, `force_close()`
- Async fallback handlers: `FallbackConfig.handler` may be an async function with async decorated functions
- Cache stampede prevention via per-key locking with double-check pattern
- Sync timeout best-effort thread cancellation on CPython; `AsyncBulkhead` event-loop change safety

### Changed
- Bulkhead slot released during retry backoff and reacquired before the next attempt
- `MetricsCollector` latency history bounded; default sync timeout pool enlarged to `min(32, cpu_count + 4)`
- Wrapped functions expose `_executor` for runtime introspection

### Fixed
- `FallbackConfig()` works without arguments; `handler=None` clears `fallback_on` (no silent `None` returns)
- Circuit breaker race condition in `allow_request()`; CB state re-checked between retries
- `MetricsCollector` async latency collision fixed via `contextvars`
- Jitter zero-delay floor (10% minimum) prevents retry storms; timeout errors chain via `from exc`
- Django config key `max_retries` renamed to `max_attempts` (old key works with `DeprecationWarning`)

## [0.2.1] - 2026-03-19

### Fixed
- PyPI version badge showing stale version

## [0.2.0] - 2026-03-19

### Added
- Count-based sliding-window circuit breaker (`sliding_window_size`) with `failure_rate_threshold`
- `retry_on_result` predicate — retry based on return values without exceptions
- Slow call detection (`slow_call_duration`, `slow_call_rate_threshold`) and `SLOW_CALL` event type
- Circuit breaker `.metrics` property (failure_rate, slow_call_rate, total_calls)
- Error hierarchy: `ResilienceError` base with `CircuitOpenError`, `BulkheadFullError`, `RateLimitExceededError`, `ResilienceTimeoutError`

### Changed
- Presets renamed `max_retries` to `max_attempts` for consistency with `RetryConfig`
- Bare `@resilient` is a passthrough (no auto-retry)
- Major hot-path performance work: `__slots__`, cached locals, inlined isinstance, fast path without retry/timeout

### Fixed
- Retry loops catch `Exception` instead of `BaseException` (no longer swallows KeyboardInterrupt/SystemExit)
- Full jitter for thundering-herd protection; cache key collisions for unhashable args; thread pool lifecycle with `atexit` cleanup

## [0.1.2] - 2026-03-19

### Changed
- Updated PyPI description to include all seven patterns
- Added missing imports in quickstart examples
- Added comparison table disclaimer
- Added "Why not Tenacity + PyBreaker?" side-by-side example in docs
- Added observability and FastAPI examples to top-level docs
- Added Dependabot auto-merge workflow

## [0.1.1] - 2026-03-19

### Changed
- Improved README with clearer value proposition and comparison table
- Updated project description and documentation links

## [0.1.0] - 2026-03-19

### Added

#### Core Modules (Full Resilience4j Parity)
- `@resilient()` decorator combining all resilience patterns in one call
- `RetryConfig` — exponential backoff with jitter, configurable exception types
- `TimeoutConfig` — per-call time limits (thread-based sync, asyncio async)
- `CircuitBreakerConfig` — state machine (CLOSED/OPEN/HALF_OPEN) with configurable thresholds
- `FallbackConfig` — graceful degradation with static values or callable handlers
- `BulkheadConfig` — semaphore-based concurrency limiting (sync + async)
- `RateLimiterConfig` — token bucket algorithm for call rate limiting
- `CacheConfig` — LRU result cache with TTL and hit/miss statistics
- `ResilienceRegistry` — centralized management of named resilience instances with shared state

#### Infrastructure
- Full sync and async support (auto-detects sync vs async functions)
- Opinionated presets: `http_policy()`, `db_policy()`, `queue_policy()`, `strict_policy()`
- Structured observability: `JsonEventLogger`, `MetricsCollector`, unified event system
- Optional performance backends: uvloop (C-based) + orjson (Rust-based) via `pip install pyresilience[fast]`
- Framework integrations: FastAPI, Django, Flask
- Real-world examples directory

#### Quality
- Zero runtime dependencies — pure Python stdlib
- Type-safe — strict mypy compatible, `py.typed` marker (PEP 561)
- 157+ tests, 98% code coverage
- Python 3.9 — 3.14 support
- Linux, macOS, Windows CI
- Codecov integration
- Comprehensive Resilience4j-style documentation

[0.4.0]: https://github.com/AhsanSheraz/pyresilience/releases/tag/v0.4.0
[0.3.2]: https://github.com/AhsanSheraz/pyresilience/releases/tag/v0.3.2
[0.3.1]: https://github.com/AhsanSheraz/pyresilience/releases/tag/v0.3.1
[0.3.0]: https://github.com/AhsanSheraz/pyresilience/releases/tag/v0.3.0
[0.2.1]: https://github.com/AhsanSheraz/pyresilience/releases/tag/v0.2.1
[0.2.0]: https://github.com/AhsanSheraz/pyresilience/releases/tag/v0.2.0
[0.1.2]: https://github.com/AhsanSheraz/pyresilience/releases/tag/v0.1.2
[0.1.1]: https://github.com/AhsanSheraz/pyresilience/releases/tag/v0.1.1
[0.1.0]: https://github.com/AhsanSheraz/pyresilience/releases/tag/v0.1.0
