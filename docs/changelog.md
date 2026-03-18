# Changelog

## v0.1.0 (2026-03-19)

Initial release with full Resilience4j feature parity.

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
