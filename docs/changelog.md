# Changelog

## v0.2.0 (2026-03-19)

### New Features
- **Sliding window circuit breaker** — Count-based sliding window replaces fragile consecutive failure counting. Configure with `sliding_window_size` parameter.
- **Failure rate % threshold** — `failure_rate_threshold=0.5` trips at 50% failure rate within the sliding window, matching production circuit breaker behavior.
- **Retry on result predicate** — `retry_on_result=lambda r: r.get("status") == 429` retries based on return values without requiring exceptions.
- **Slow call detection** — Calls exceeding `slow_call_duration` count toward circuit opening via `slow_call_rate_threshold`. Detects slow degradation without errors.
- **Circuit breaker metrics** — `.metrics` property exposes real-time failure_rate, slow_call_rate, total_calls.
- **`SLOW_CALL` event type** — New event emitted when a call exceeds the slow call duration threshold.

### Performance
- `__slots__` on all hot-path classes (executor, circuit breaker, cache, rate limiter, logger)
- Cached module-level locals for `time.monotonic`, `random.random`, enum members
- Inlined `isinstance()` checks, guarded event emission with `has_listeners` bool
- Pre-computed rate (tokens/sec) in rate limiter
- Decorator overhead: 0.56us (13x faster than tenacity at 7.31us)
- Circuit breaker overhead: 1.25us
- Memory reduced to 1,052KB per 1,000 decorated functions (53% less than tenacity)
- Throughput: 231K ops/sec (3.0x tenacity)

### Fixes
- Replaced deprecated `asyncio.iscoroutinefunction` with `inspect.iscoroutinefunction`
- `BaseException` → `Exception` in retry loops (no longer catches KeyboardInterrupt/SystemExit)
- Full jitter (`random.random() * delay`) for better thundering-herd protection
- Configurable thread pool size for sync timeouts (`TimeoutConfig(pool_size=N)`)

### Tests
- 224 tests (up from 176), 98.5% branch coverage
- New: `test_sliding_window.py` (15 tests), `test_retry_on_result.py` (11 tests)
- Expanded `test_coverage.py` with edge case tests for executor, contrib, presets, and logging modules

---

## v0.1.0 (2026-03-19)

Initial release with all 7 resilience patterns.

### Core Modules
- **CircuitBreaker** — State machine (CLOSED/OPEN/HALF_OPEN) with configurable thresholds
- **Retry** — Exponential backoff with jitter, configurable exception types
- **Bulkhead** — Semaphore-based concurrency limiting (sync + async)
- **TimeLimiter** — Per-call timeouts (thread-based sync, asyncio.wait_for async)
- **RateLimiter** — Token bucket algorithm for call rate limiting
- **Cache** — LRU result cache with TTL and hit/miss statistics

### Infrastructure
- **Registry** — Centralized management of named resilience instances with shared state
- **Presets** — `http_policy()`, `db_policy()`, `queue_policy()`, `strict_policy()`
- **Observability** — `JsonEventLogger`, `MetricsCollector`, unified event system
- **Performance** — Optional uvloop + orjson backends via `pip install pyresilience[fast]`

### Quality
- Zero runtime dependencies
- Full async support (auto-detects sync vs async)
- Strict mypy type checking
- 157 tests, 98% coverage
- Python 3.9 — 3.14 support
- Linux, macOS, Windows CI
