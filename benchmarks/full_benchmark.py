"""Comprehensive benchmark: pyresilience vs competitors across all features.

Tests all 7 resilience patterns + async + throughput + memory.
Outputs results as JSON for cross-version comparison.
"""

from __future__ import annotations

import asyncio
import gc
import json
import statistics
import sys
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor

# ─── pyresilience ───────────────────────────────────────────────────────────
from pyresilience import (
    resilient,
    RetryConfig,
    TimeoutConfig,
    CircuitBreakerConfig,
    FallbackConfig,
    BulkheadConfig,
    RateLimiterConfig,
    CacheConfig,
)

# ─── competitors ────────────────────────────────────────────────────────────
from tenacity import retry, stop_after_attempt, wait_fixed
import backoff
import logging
import stamina
import pybreaker

# Suppress stamina's noisy retry logging
logging.getLogger("stamina").setLevel(logging.WARNING)


def timeit(func, iterations=100_000):
    """Time a function, return stats in microseconds."""
    for _ in range(min(1000, iterations // 10)):
        func()
    gc.disable()
    times = []
    for _ in range(iterations):
        start = time.perf_counter_ns()
        func()
        elapsed = time.perf_counter_ns() - start
        times.append(elapsed / 1000)
    gc.enable()
    return {
        "mean_us": round(statistics.mean(times), 2),
        "median_us": round(statistics.median(times), 2),
        "p95_us": round(sorted(times)[int(len(times) * 0.95)], 2),
        "p99_us": round(sorted(times)[int(len(times) * 0.99)], 2),
    }


def measure_memory(setup_func, n=1000):
    tracemalloc.start()
    items = [setup_func(i) for i in range(n)]
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    _ = items
    return {"current_kb": round(current / 1024, 1), "peak_kb": round(peak / 1024, 1)}


def fmt(result):
    return f"mean={result['mean_us']:>8.2f}us  median={result['median_us']:>8.2f}us  p95={result['p95_us']:>8.2f}us  p99={result['p99_us']:>8.2f}us"


# ═══════════════════════════════════════════════════════════════════════════
# 1. Decorator overhead (no-op, no failures)
# ═══════════════════════════════════════════════════════════════════════════

def bench_overhead():
    print("\n" + "=" * 70)
    print("1. DECORATOR OVERHEAD (no-op function, no failures, 100k calls)")
    print("=" * 70)

    def bare_func():
        return 42

    @resilient(retry=RetryConfig(max_attempts=3, delay=0.01))
    def pyr_func():
        return 42

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(0.01))
    def ten_func():
        return 42

    @backoff.on_exception(backoff.expo, Exception, max_tries=3)
    def bof_func():
        return 42

    @stamina.retry(on=Exception, attempts=3, wait_initial=0.01)
    def sta_func():
        return 42

    breaker = pybreaker.CircuitBreaker(fail_max=5)

    @breaker
    def pbr_func():
        return 42

    results = {}
    for name, func in [
        ("bare (no decorator)", bare_func),
        ("pyresilience", pyr_func),
        ("tenacity", ten_func),
        ("backoff", bof_func),
        ("stamina", sta_func),
        ("pybreaker", pbr_func),
    ]:
        r = timeit(func)
        results[name] = r
        print(f"  {name:<25} {fmt(r)}")

    return results


# ═══════════════════════════════════════════════════════════════════════════
# 2. Retry performance (fail 2x, succeed on 3rd)
# ═══════════════════════════════════════════════════════════════════════════

def bench_retry():
    print("\n" + "=" * 70)
    print("2. RETRY PERFORMANCE (fail 2x, succeed on 3rd, 10k calls)")
    print("=" * 70)

    @resilient(retry=RetryConfig(max_attempts=3, delay=0.001, jitter=False))
    def pyr_retry():
        pyr_retry._count += 1
        if pyr_retry._count % 3 != 0:
            raise ValueError("fail")
        return 42
    pyr_retry._count = 0

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(0.001))
    def ten_retry():
        ten_retry._count += 1
        if ten_retry._count % 3 != 0:
            raise ValueError("fail")
        return 42
    ten_retry._count = 0

    @backoff.on_exception(backoff.constant, ValueError, max_tries=3, interval=0.001)
    def bof_retry():
        bof_retry._count += 1
        if bof_retry._count % 3 != 0:
            raise ValueError("fail")
        return 42
    bof_retry._count = 0

    @stamina.retry(on=ValueError, attempts=3, wait_initial=0.001, wait_max=0.001)
    def sta_retry():
        sta_retry._count += 1
        if sta_retry._count % 3 != 0:
            raise ValueError("fail")
        return 42
    sta_retry._count = 0

    results = {}
    for name, func in [
        ("pyresilience", pyr_retry),
        ("tenacity", ten_retry),
        ("backoff", bof_retry),
        ("stamina", sta_retry),
    ]:
        r = timeit(func, iterations=10_000)
        results[name] = r
        print(f"  {name:<25} {fmt(r)}")

    return results


# ═══════════════════════════════════════════════════════════════════════════
# 3. Circuit breaker overhead
# ═══════════════════════════════════════════════════════════════════════════

def bench_circuit_breaker():
    print("\n" + "=" * 70)
    print("3. CIRCUIT BREAKER (always succeeds, closed state, 100k calls)")
    print("=" * 70)

    @resilient(circuit_breaker=CircuitBreakerConfig(failure_threshold=5))
    def pyr_cb():
        return 42

    breaker = pybreaker.CircuitBreaker(fail_max=5)

    @breaker
    def pbr_cb():
        return 42

    results = {}
    for name, func in [("pyresilience", pyr_cb), ("pybreaker", pbr_cb)]:
        r = timeit(func)
        results[name] = r
        print(f"  {name:<25} {fmt(r)}")

    return results


# ═══════════════════════════════════════════════════════════════════════════
# 4. Fallback
# ═══════════════════════════════════════════════════════════════════════════

def bench_fallback():
    print("\n" + "=" * 70)
    print("4. FALLBACK (always fails, triggers fallback, 100k calls)")
    print("=" * 70)

    @resilient(fallback=FallbackConfig(handler=lambda e: "fallback_value", fallback_on=[ValueError]))
    def pyr_fallback():
        raise ValueError("fail")

    results = {}
    r = timeit(pyr_fallback)
    results["pyresilience"] = r
    print(f"  {'pyresilience':<25} {fmt(r)}")
    print(f"  (No direct competitor equivalent — pyresilience-only feature)")

    return results


# ═══════════════════════════════════════════════════════════════════════════
# 5. Bulkhead
# ═══════════════════════════════════════════════════════════════════════════

def bench_bulkhead():
    print("\n" + "=" * 70)
    print("5. BULKHEAD (concurrency limiter, 100k calls)")
    print("=" * 70)

    @resilient(bulkhead=BulkheadConfig(max_concurrent=10))
    def pyr_bh():
        return 42

    results = {}
    r = timeit(pyr_bh)
    results["pyresilience"] = r
    print(f"  {'pyresilience':<25} {fmt(r)}")
    print(f"  (No direct competitor equivalent — pyresilience-only feature)")

    return results


# ═══════════════════════════════════════════════════════════════════════════
# 6. Rate limiter
# ═══════════════════════════════════════════════════════════════════════════

def bench_rate_limiter():
    print("\n" + "=" * 70)
    print("6. RATE LIMITER (token bucket, 50k calls)")
    print("=" * 70)

    @resilient(rate_limiter=RateLimiterConfig(max_calls=1_000_000, period=1.0))
    def pyr_rl():
        return 42

    results = {}
    r = timeit(pyr_rl, iterations=50_000)
    results["pyresilience"] = r
    print(f"  {'pyresilience':<25} {fmt(r)}")
    print(f"  (No direct competitor equivalent — pyresilience-only feature)")

    return results


# ═══════════════════════════════════════════════════════════════════════════
# 7. Cache
# ═══════════════════════════════════════════════════════════════════════════

def bench_cache():
    print("\n" + "=" * 70)
    print("7. CACHE (LRU with TTL, 100k calls, same args)")
    print("=" * 70)

    @resilient(cache=CacheConfig(ttl=60.0, max_size=100))
    def pyr_cache(x):
        return x * 2

    # Warm up cache
    pyr_cache(42)

    results = {}
    r = timeit(lambda: pyr_cache(42))
    results["pyresilience"] = r
    print(f"  {'pyresilience':<25} {fmt(r)}")
    print(f"  (No direct competitor equivalent — pyresilience-only feature)")

    return results


# ═══════════════════════════════════════════════════════════════════════════
# 8. Combined patterns
# ═══════════════════════════════════════════════════════════════════════════

def bench_combined():
    print("\n" + "=" * 70)
    print("8. COMBINED (retry + timeout + circuit breaker, 100k calls)")
    print("=" * 70)

    @resilient(
        retry=RetryConfig(max_attempts=3, delay=0.01),
        timeout=TimeoutConfig(seconds=10),
        circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
    )
    def pyr_combined():
        return 42

    breaker2 = pybreaker.CircuitBreaker(fail_max=5)

    @breaker2
    @retry(stop=stop_after_attempt(3), wait=wait_fixed(0.01))
    def stacked_combined():
        return 42

    results = {}
    for name, func in [
        ("pyresilience (1 decorator)", pyr_combined),
        ("tenacity+pybreaker (2 stacked)", stacked_combined),
    ]:
        r = timeit(func)
        results[name] = r
        print(f"  {name:<35} {fmt(r)}")

    return results


# ═══════════════════════════════════════════════════════════════════════════
# 9. All 7 patterns combined
# ═══════════════════════════════════════════════════════════════════════════

def bench_all_patterns():
    print("\n" + "=" * 70)
    print("9. ALL 7 PATTERNS (retry+timeout+cb+fallback+bulkhead+rl+cache, 50k)")
    print("=" * 70)

    @resilient(
        retry=RetryConfig(max_attempts=3, delay=0.01),
        timeout=TimeoutConfig(seconds=10),
        circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
        fallback=FallbackConfig(handler=lambda e: "fallback", fallback_on=[ValueError]),
        bulkhead=BulkheadConfig(max_concurrent=10),
        rate_limiter=RateLimiterConfig(max_calls=1_000_000, period=1.0),
        cache=CacheConfig(ttl=60.0, max_size=100),
    )
    def pyr_all(x):
        return x * 2

    # Warm cache
    pyr_all(42)

    results = {}
    r = timeit(lambda: pyr_all(42), iterations=50_000)
    results["pyresilience (all 7 patterns)"] = r
    print(f"  {'pyresilience (all 7 patterns)':<35} {fmt(r)}")

    return results


# ═══════════════════════════════════════════════════════════════════════════
# 10. Throughput under concurrent load
# ═══════════════════════════════════════════════════════════════════════════

def bench_throughput():
    print("\n" + "=" * 70)
    print("10. THROUGHPUT (10k calls across 10 threads)")
    print("=" * 70)

    n_calls = 10_000
    n_threads = 10

    @resilient(retry=RetryConfig(max_attempts=3, delay=0.001))
    def pyr_func():
        return 42

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(0.001))
    def ten_func():
        return 42

    results = {}
    for name, func in [("pyresilience", pyr_func), ("tenacity", ten_func)]:
        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=n_threads) as pool:
            list(pool.map(lambda _: func(), range(n_calls)))
        elapsed = time.perf_counter() - start
        ops = int(n_calls / elapsed)
        results[name] = {"elapsed_s": round(elapsed, 3), "ops_per_sec": ops}
        print(f"  {name:<25} {elapsed:.3f}s  ({ops:,} ops/sec)")

    return results


# ═══════════════════════════════════════════════════════════════════════════
# 11. Memory usage
# ═══════════════════════════════════════════════════════════════════════════

def bench_memory():
    print("\n" + "=" * 70)
    print("11. MEMORY (1,000 decorated functions)")
    print("=" * 70)

    def pyr_setup(i):
        @resilient(retry=RetryConfig(max_attempts=3, delay=0.01))
        def f():
            return i
        return f

    def ten_setup(i):
        @retry(stop=stop_after_attempt(3), wait=wait_fixed(0.01))
        def f():
            return i
        return f

    results = {}
    for name, setup in [("pyresilience", pyr_setup), ("tenacity", ten_setup)]:
        mem = measure_memory(setup)
        results[name] = mem
        print(f"  {name:<25} current={mem['current_kb']:>8.1f}KB  peak={mem['peak_kb']:>8.1f}KB")

    return results


# ═══════════════════════════════════════════════════════════════════════════
# 12. Async overhead
# ═══════════════════════════════════════════════════════════════════════════

def bench_async():
    print("\n" + "=" * 70)
    print("12. ASYNC OVERHEAD (no-op async, 50k calls)")
    print("=" * 70)

    @resilient(retry=RetryConfig(max_attempts=3, delay=0.01))
    async def pyr_async():
        return 42

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(0.01))
    async def ten_async():
        return 42

    async def measure_async(func, iterations=50_000):
        for _ in range(500):
            await func()
        times = []
        for _ in range(iterations):
            start = time.perf_counter_ns()
            await func()
            elapsed = time.perf_counter_ns() - start
            times.append(elapsed / 1000)
        return {
            "mean_us": round(statistics.mean(times), 2),
            "median_us": round(statistics.median(times), 2),
            "p95_us": round(sorted(times)[int(len(times) * 0.95)], 2),
            "p99_us": round(sorted(times)[int(len(times) * 0.99)], 2),
        }

    async def run():
        results = {}
        for name, func in [("pyresilience", pyr_async), ("tenacity", ten_async)]:
            r = await measure_async(func)
            results[name] = r
            print(f"  {name:<25} {fmt(r)}")
        return results

    return asyncio.run(run())


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    print(f"Python {python_version}")
    print(f"Platform: {sys.platform}")

    all_results = {
        "python_version": python_version,
        "platform": sys.platform,
    }

    all_results["overhead"] = bench_overhead()
    all_results["retry"] = bench_retry()
    all_results["circuit_breaker"] = bench_circuit_breaker()
    all_results["fallback"] = bench_fallback()
    all_results["bulkhead"] = bench_bulkhead()
    all_results["rate_limiter"] = bench_rate_limiter()
    all_results["cache"] = bench_cache()
    all_results["combined"] = bench_combined()
    all_results["all_patterns"] = bench_all_patterns()
    all_results["throughput"] = bench_throughput()
    all_results["memory"] = bench_memory()
    all_results["async"] = bench_async()

    # Save results as JSON
    output_file = f"benchmarks/results_{python_version}.json"
    with open(output_file, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nResults saved to {output_file}")

    # Print summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    overhead = all_results["overhead"]
    bare = overhead["bare (no decorator)"]["mean_us"]
    pyr = overhead["pyresilience"]["mean_us"]
    ten = overhead["tenacity"]["mean_us"]
    bof = overhead["backoff"]["mean_us"]
    sta = overhead["stamina"]["mean_us"]
    pbr = overhead["pybreaker"]["mean_us"]

    print(f"\nDecorator overhead vs bare function ({bare:.2f}us):")
    print(f"  pyresilience: +{pyr - bare:.2f}us ({pyr:.2f}us total)")
    print(f"  tenacity:     +{ten - bare:.2f}us ({ten:.2f}us total)")
    print(f"  backoff:      +{bof - bare:.2f}us ({bof:.2f}us total)")
    print(f"  stamina:      +{sta - bare:.2f}us ({sta:.2f}us total)")
    print(f"  pybreaker:    +{pbr - bare:.2f}us ({pbr:.2f}us total)")

    combined = all_results["combined"]
    pyr_c = combined["pyresilience (1 decorator)"]["mean_us"]
    stk_c = combined["tenacity+pybreaker (2 stacked)"]["mean_us"]
    if stk_c > pyr_c:
        print(f"\nCombined patterns: pyresilience is {stk_c/pyr_c:.1f}x faster")
    else:
        print(f"\nCombined patterns: stacked is {pyr_c/stk_c:.1f}x faster")

    tp = all_results["throughput"]
    print(f"\nThroughput:")
    print(f"  pyresilience: {tp['pyresilience']['ops_per_sec']:,} ops/sec")
    print(f"  tenacity:     {tp['tenacity']['ops_per_sec']:,} ops/sec")

    mem = all_results["memory"]
    print(f"\nMemory (1k decorated functions):")
    print(f"  pyresilience: {mem['pyresilience']['current_kb']:.1f}KB")
    print(f"  tenacity:     {mem['tenacity']['current_kb']:.1f}KB")

    print("\nDone.")
