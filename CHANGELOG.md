# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-03-18

### Added
- `@resilient()` decorator combining retry, timeout, circuit breaker, fallback, and bulkhead
- Full sync and async support
- `RetryConfig` with exponential backoff and jitter
- `TimeoutConfig` for per-call timeouts
- `CircuitBreakerConfig` with half-open recovery
- `FallbackConfig` with static values or callable fallbacks
- `BulkheadConfig` for concurrency limiting
- Structured event system via `ResilienceEvent` and `ResilienceListener`
- Type-safe configuration dataclasses
- Zero runtime dependencies
