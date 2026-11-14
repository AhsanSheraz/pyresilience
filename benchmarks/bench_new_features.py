"""Benchmark: overhead of the 0.5.0 features on the happy path.

Run: python benchmarks/bench_new_features.py

Covers weighted and multi-limit rate limiting, reconciliation and server
feedback, the overall deadline, fallback alternatives and cooldown, shared state
through a backend, and registry-shared state. Each number is the cost of one
decorated call that succeeds; compare it with the bare call on the first line.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from pyresilience import (
    CircuitBreakerConfig,
    FallbackConfig,
    InMemoryBackend,
    RateLimit,
    RateLimiterConfig,
    RateLimitFeedback,
    ResilienceConfig,
    ResilienceRegistry,
    RetryBudgetConfig,
    RetryConfig,
    SharedStateConfig,
    TimeoutConfig,
    resilient,
)

# Limits high enough that no call is ever rejected during the run
BIG = 1_000_000_000
NO_FEEDBACK = RateLimitFeedback()


def bare_function(prompt: str = "hello") -> int:
    return 42


@resilient(rate_limiter=RateLimiterConfig(max_calls=BIG, period=1.0))
def plain_limiter(prompt: str = "hello") -> int:
    return 42


@resilient(rate_limiter=RateLimiterConfig(max_calls=BIG, period=1.0, cost=lambda prompt="": 3))
def weighted_limiter(prompt: str = "hello") -> int:
    return 42


@resilient(
    rate_limiter=RateLimiterConfig(
        max_calls=BIG,
        period=1.0,
        limits=[
            RateLimit(BIG, 60.0, name="tokens", cost=lambda prompt="": len(prompt)),
            RateLimit(BIG, 86400.0, name="daily"),
        ],
    )
)
def multi_limit(prompt: str = "hello") -> int:
    return 42


@resilient(
    rate_limiter=RateLimiterConfig(
        max_calls=BIG,
        period=1.0,
        limits=[
            RateLimit(
                BIG,
                60.0,
                name="tokens",
                cost=lambda prompt="": 100,
                actual_cost=lambda result: 60,
            )
        ],
        feedback=lambda outcome: NO_FEEDBACK,
    )
)
def reconcile_and_feedback(prompt: str = "hello") -> int:
    return 42


@resilient(
    retry=RetryConfig(max_attempts=3),
    timeout=TimeoutConfig(seconds=30.0),
)
def per_attempt_timeout(prompt: str = "hello") -> int:
    return 42


@resilient(
    retry=RetryConfig(max_attempts=3),
    timeout=TimeoutConfig(seconds=30.0, total_seconds=60.0),
)
def total_deadline(prompt: str = "hello") -> int:
    return 42


def _backup(prompt: str = "hello") -> int:
    return 7


@resilient(retry=RetryConfig(max_attempts=3), fallback=FallbackConfig(handler=0))
def plain_fallback(prompt: str = "hello") -> int:
    return 42


@resilient(
    retry=RetryConfig(max_attempts=3),
    fallback=FallbackConfig(alternatives=[_backup], cooldown=30.0),
)
def fallback_router(prompt: str = "hello") -> int:
    return 42


@resilient(fallback=FallbackConfig(alternatives=[_backup], cooldown=3600.0))
def cooling_primary(prompt: str = "hello") -> int:
    raise ConnectionError("down")


_backend = InMemoryBackend()


@resilient(
    retry=RetryConfig(max_attempts=3),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
    retry_budget=RetryBudgetConfig(),
    shared_state=SharedStateConfig(backend=_backend, key="bench-breaker", sync_interval=0),
)
def shared_breaker(prompt: str = "hello") -> int:
    return 42


@resilient(
    rate_limiter=RateLimiterConfig(max_calls=BIG, period=60.0),
    shared_state=SharedStateConfig(backend=_backend, key="bench-limiter", sync_interval=0),
)
def shared_limiter(prompt: str = "hello") -> int:
    return 42


_registry = ResilienceRegistry()
_registry.register(
    "bench",
    ResilienceConfig(
        retry=RetryConfig(max_attempts=3),
        circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
        rate_limiter=RateLimiterConfig(max_calls=BIG, period=1.0),
    ),
)


@_registry.decorator("bench")
def registry_sync(prompt: str = "hello") -> int:
    return 42


@_registry.decorator("bench")
async def registry_async(prompt: str = "hello") -> int:
    return 42


@resilient(timeout=TimeoutConfig(seconds=30.0, stream_idle_seconds=5.0))
async def idle_guarded_stream(prompt: str = "hello") -> Any:
    async def chunks() -> Any:
        for index in range(100):
            yield index

    return chunks()


async def plain_stream(prompt: str = "hello") -> Any:
    async def chunks() -> Any:
        for index in range(100):
            yield index

    return chunks()


def benchmark(func: Callable[..., Any], iterations: int) -> float:
    """Return microseconds per call."""
    for _ in range(200):
        func()
    start = time.perf_counter()
    for _ in range(iterations):
        func()
    return (time.perf_counter() - start) / iterations * 1_000_000


async def benchmark_async(func: Callable[..., Any], iterations: int) -> float:
    """Return microseconds per awaited call."""
    for _ in range(200):
        await func()
    start = time.perf_counter()
    for _ in range(iterations):
        await func()
    return (time.perf_counter() - start) / iterations * 1_000_000


async def benchmark_stream(func: Callable[..., Any], iterations: int) -> float:
    """Return microseconds per streamed item (100 items per call)."""
    start = time.perf_counter()
    for _ in range(iterations):
        async for _item in await func():
            pass
    return (time.perf_counter() - start) / (iterations * 100) * 1_000_000


def main() -> None:
    iterations = 50_000
    print(f"pyresilience 0.5.0 feature overhead ({iterations} iterations each)\n")
    print(f"{'Configuration':<44} {'Per call (us)':>14}")
    print("-" * 60)

    cooling_primary()  # one failure starts the cooldown; later calls skip the primary

    sync_cases: list[tuple[str, Callable[..., Any], int]] = [
        ("bare function (baseline)", bare_function, iterations),
        ("rate limiter: plain (one token per call)", plain_limiter, iterations),
        ("rate limiter: weighted cost", weighted_limiter, iterations),
        ("rate limiter: three limits", multi_limit, iterations),
        ("rate limiter: reconcile + feedback", reconcile_and_feedback, iterations),
        ("rate limiter: shared (in-memory backend)", shared_limiter, iterations),
        ("fallback: plain handler", plain_fallback, iterations),
        ("fallback: alternatives + cooldown", fallback_router, iterations),
        ("fallback: primary cooling, alternative used", cooling_primary, iterations),
        ("shared breaker + retry budget", shared_breaker, iterations),
        ("registry: shared sync", registry_sync, iterations),
        # Sync timeouts hop through a worker thread, so fewer iterations suffice
        ("timeout: per attempt", per_attempt_timeout, iterations // 10),
        ("timeout: per attempt + total deadline", total_deadline, iterations // 10),
    ]

    baseline = 0.0
    for name, func, count in sync_cases:
        per_call = benchmark(func, count)
        if not baseline:
            baseline = per_call
            print(f"{name:<44} {per_call:>11.2f} us")
        else:
            print(f"{name:<44} {per_call:>11.2f} us (+{per_call - baseline:.2f}us)")

    async def run_async() -> None:
        per_call = await benchmark_async(registry_async, iterations)
        print(f"{'registry: shared async':<44} {per_call:>11.2f} us")
        plain = await benchmark_stream(plain_stream, 200)
        guarded = await benchmark_stream(idle_guarded_stream, 200)
        print(f"{'stream: plain async iterator (per item)':<44} {plain:>11.2f} us")
        label = "stream: idle timeout (per item)"
        print(f"{label:<44} {guarded:>11.2f} us (+{guarded - plain:.2f}us)")

    asyncio.run(run_async())

    print(f"\nBaseline: {baseline:.2f} us per call")
    print("Note: actual I/O (HTTP, LLM calls) takes 1-10000 ms, dwarfing these numbers.")


if __name__ == "__main__":
    main()
