# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `ignore_on` on `RetryConfig` and `CircuitBreakerConfig` — exception types that are never retried and never counted as circuit-breaker failures; takes precedence over `retry_on` / `error_types`, enabling fail-fast behaviour on terminal client errors such as authentication failures and quota exhaustion.
- `delay_func` on `RetryConfig` — optional callable that receives the triggering exception (or result) and the current attempt number and returns a delay in seconds; return `None` to fall back to the configured exponential backoff. Designed to honour HTTP `Retry-After` headers without requiring custom retry logic outside the decorator.
- `pyresilience.contrib.http` — stdlib-only contrib module providing `retry_on_status()` (duck-typed predicate compatible with requests, httpx, and aiohttp response objects) and `retry_after_delay()` (parses `Retry-After` headers for use as a `delay_func`); also ships the `llm_policy()` preset for LLM / HTTP API calls with 429-aware, `Retry-After`-honoring exponential backoff out of the box.

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

[0.1.2]: https://github.com/AhsanSheraz/pyresilience/releases/tag/v0.1.2
[0.1.1]: https://github.com/AhsanSheraz/pyresilience/releases/tag/v0.1.1
[0.1.0]: https://github.com/AhsanSheraz/pyresilience/releases/tag/v0.1.0
