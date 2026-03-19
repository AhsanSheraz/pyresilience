# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.1.1]: https://github.com/AhsanSheraz/pyresilience/releases/tag/v0.1.1
[0.1.0]: https://github.com/AhsanSheraz/pyresilience/releases/tag/v0.1.0
