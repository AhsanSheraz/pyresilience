"""Benchmark: measure pyresilience decorator overhead.

Run: python benchmarks/bench_overhead.py

This measures the overhead added by pyresilience's decorator compared to
a bare function call. The overhead should be negligible compared to actual
I/O operations (network calls, database queries).
"""

from __future__ import annotations

import time
from typing import Any

from pyresilience import (
    BulkheadConfig,
    CacheConfig,
    CircuitBreakerConfig,
    RateLimiterConfig,
    RetryConfig,
    TimeoutConfig,
    resilient,
)


def bare_function() -> int:
    return 42


@resilient
def with_default_retry() -> int:
    return 42


@resilient(retry=RetryConfig(max_attempts=3))
def with_retry_only() -> int:
    return 42


@resilient(
    retry=RetryConfig(max_attempts=3),
    timeout=TimeoutConfig(seconds=30),
)
def with_retry_timeout() -> int:
    return 42


@resilient(
    retry=RetryConfig(max_attempts=3),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
)
def with_retry_circuit() -> int:
    return 42


@resilient(
    retry=RetryConfig(max_attempts=3),
    timeout=TimeoutConfig(seconds=30),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
    bulkhead=BulkheadConfig(max_concurrent=100),
    rate_limiter=RateLimiterConfig(max_calls=1000000, period=1.0),
)
def with_all_patterns() -> int:
    return 42


@resilient(cache=CacheConfig(max_size=100, ttl=60.0))
def with_cache(x: int) -> int:
    return x * 2


def benchmark(func: Any, iterations: int = 10000, **kwargs: Any) -> tuple[float, float]:
    """Run a function N times and return (total_seconds, per_call_microseconds)."""
    # Warmup
    for _ in range(100):
        func(**kwargs)

    start = time.perf_counter()
    for _ in range(iterations):
        func(**kwargs)
    elapsed = time.perf_counter() - start

    per_call_us = (elapsed / iterations) * 1_000_000
    return elapsed, per_call_us


def main() -> None:
    iterations = 50000
    print(f"pyresilience Overhead Benchmark ({iterations} iterations each)\n")
    print(f"{'Configuration':<35} {'Total (s)':>10} {'Per call (us)':>14}")
    print("-" * 62)

    configs = [
        ("bare function (baseline)", bare_function, {}),
        ("@resilient (default retry)", with_default_retry, {}),
        ("retry only", with_retry_only, {}),
        ("retry + timeout", with_retry_timeout, {}),
        ("retry + circuit breaker", with_retry_circuit, {}),
        ("all patterns (no cache)", with_all_patterns, {}),
        ("cache (first call)", with_cache, {"x": 1}),
    ]

    baseline_us = 0.0
    for name, func, kwargs in configs:
        total, per_call = benchmark(func, iterations, **kwargs)
        if name.startswith("bare"):
            baseline_us = per_call
        overhead = f" (+{per_call - baseline_us:.2f}us)" if baseline_us and not name.startswith("bare") else ""
        print(f"{name:<35} {total:>10.4f} {per_call:>11.2f} us{overhead}")

    # Cache hit benchmark (separate because we want to measure hits)
    with_cache(99)  # Prime the cache
    total, per_call = benchmark(with_cache, iterations, x=99)
    overhead = f" (+{per_call - baseline_us:.2f}us)"
    print(f"{'cache (hit)':<35} {total:>10.4f} {per_call:>11.2f} us{overhead}")

    print(f"\nBaseline: {baseline_us:.2f} us per call")
    print("Note: Actual I/O operations (HTTP, DB) take 1-1000ms, dwarfing any decorator overhead.")


if __name__ == "__main__":
    main()
