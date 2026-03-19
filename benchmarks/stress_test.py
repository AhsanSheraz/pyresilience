"""Stress test: pyresilience vs tenacity vs pybreaker vs backoff vs stamina.

Measures:
1. Decorator overhead (no-op function, no failures)
2. Retry performance (function fails N-1 times then succeeds)
3. Throughput under load (concurrent calls)
4. Memory usage
"""

from __future__ import annotations

import asyncio
import gc
import statistics
import sys
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor

# ─── pyresilience ───────────────────────────────────────────────────────────
from pyresilience import resilient, RetryConfig, TimeoutConfig, CircuitBreakerConfig

# ─── tenacity ───────────────────────────────────────────────────────────────
from tenacity import retry, stop_after_attempt, wait_fixed

# ─── backoff ────────────────────────────────────────────────────────────────
import backoff

# ─── stamina ────────────────────────────────────────────────────────────────
import stamina

# ─── pybreaker ──────────────────────────────────────────────────────────────
import pybreaker


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def timeit(func, iterations=100_000):
    """Time a function over N iterations, return per-call stats in microseconds."""
    times = []
    # Warmup
    for _ in range(1000):
        func()
    gc.disable()
    for _ in range(iterations):
        start = time.perf_counter_ns()
        func()
        elapsed = time.perf_counter_ns() - start
        times.append(elapsed / 1000)  # convert to microseconds
    gc.enable()
    return {
        "mean_us": round(statistics.mean(times), 2),
        "median_us": round(statistics.median(times), 2),
        "p95_us": round(sorted(times)[int(len(times) * 0.95)], 2),
        "p99_us": round(sorted(times)[int(len(times) * 0.99)], 2),
        "min_us": round(min(times), 2),
        "max_us": round(max(times), 2),
    }


def measure_memory(setup_func, n=1000):
    """Measure memory usage for creating N decorated functions."""
    tracemalloc.start()
    items = [setup_func(i) for i in range(n)]
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    _ = items  # keep reference
    return {"current_kb": round(current / 1024, 1), "peak_kb": round(peak / 1024, 1)}


def print_result(name, result):
    print(f"  {name:<20} mean={result['mean_us']:>8.2f}us  "
          f"median={result['median_us']:>8.2f}us  "
          f"p95={result['p95_us']:>8.2f}us  "
          f"p99={result['p99_us']:>8.2f}us")


# ═══════════════════════════════════════════════════════════════════════════
# 1. Decorator overhead (no-op, no failures)
# ═══════════════════════════════════════════════════════════════════════════

def bench_overhead():
    print("\n" + "=" * 70)
    print("1. DECORATOR OVERHEAD (no-op function, no failures)")
    print("   100,000 calls each")
    print("=" * 70)

    # Baseline: no decorator
    def bare_func():
        return 42

    # pyresilience
    @resilient(retry=RetryConfig(max_attempts=3, delay=0.01))
    def pyr_func():
        return 42

    # tenacity
    @retry(stop=stop_after_attempt(3), wait=wait_fixed(0.01))
    def ten_func():
        return 42

    # backoff
    @backoff.on_exception(backoff.expo, Exception, max_tries=3)
    def bof_func():
        return 42

    # stamina
    @stamina.retry(on=Exception, attempts=3, wait_initial=0.01)
    def sta_func():
        return 42

    # pybreaker
    breaker = pybreaker.CircuitBreaker(fail_max=5)

    @breaker
    def pbr_func():
        return 42

    results = {
        "bare (no decorator)": timeit(bare_func),
        "pyresilience": timeit(pyr_func),
        "tenacity": timeit(ten_func),
        "backoff": timeit(bof_func),
        "stamina": timeit(sta_func),
        "pybreaker": timeit(pbr_func),
    }

    for name, result in results.items():
        print_result(name, result)

    return results


# ═══════════════════════════════════════════════════════════════════════════
# 2. Retry performance (fail twice, succeed on 3rd)
# ═══════════════════════════════════════════════════════════════════════════

def bench_retry():
    print("\n" + "=" * 70)
    print("2. RETRY PERFORMANCE (fail 2x, succeed on 3rd attempt)")
    print("   10,000 calls each")
    print("=" * 70)

    # pyresilience
    @resilient(retry=RetryConfig(max_attempts=3, delay=0.001, jitter=False))
    def pyr_retry():
        pyr_retry._count += 1
        if pyr_retry._count % 3 != 0:
            raise ValueError("fail")
        return 42
    pyr_retry._count = 0

    # tenacity
    @retry(stop=stop_after_attempt(3), wait=wait_fixed(0.001))
    def ten_retry():
        ten_retry._count += 1
        if ten_retry._count % 3 != 0:
            raise ValueError("fail")
        return 42
    ten_retry._count = 0

    # backoff
    @backoff.on_exception(backoff.constant, ValueError, max_tries=3, interval=0.001)
    def bof_retry():
        bof_retry._count += 1
        if bof_retry._count % 3 != 0:
            raise ValueError("fail")
        return 42
    bof_retry._count = 0

    # stamina
    @stamina.retry(on=ValueError, attempts=3, wait_initial=0.001, wait_max=0.001)
    def sta_retry():
        sta_retry._count += 1
        if sta_retry._count % 3 != 0:
            raise ValueError("fail")
        return 42
    sta_retry._count = 0

    results = {
        "pyresilience": timeit(pyr_retry, iterations=10_000),
        "tenacity": timeit(ten_retry, iterations=10_000),
        "backoff": timeit(bof_retry, iterations=10_000),
        "stamina": timeit(sta_retry, iterations=10_000),
    }

    for name, result in results.items():
        print_result(name, result)

    return results


# ═══════════════════════════════════════════════════════════════════════════
# 3. Circuit breaker overhead
# ═══════════════════════════════════════════════════════════════════════════

def bench_circuit_breaker():
    print("\n" + "=" * 70)
    print("3. CIRCUIT BREAKER OVERHEAD (always succeeds, closed state)")
    print("   100,000 calls each")
    print("=" * 70)

    # pyresilience
    @resilient(circuit_breaker=CircuitBreakerConfig(failure_threshold=5))
    def pyr_cb():
        return 42

    # pybreaker
    breaker = pybreaker.CircuitBreaker(fail_max=5)

    @breaker
    def pbr_cb():
        return 42

    results = {
        "pyresilience": timeit(pyr_cb),
        "pybreaker": timeit(pbr_cb),
    }

    for name, result in results.items():
        print_result(name, result)

    return results


# ═══════════════════════════════════════════════════════════════════════════
# 4. Combined patterns overhead
# ═══════════════════════════════════════════════════════════════════════════

def bench_combined():
    print("\n" + "=" * 70)
    print("4. COMBINED PATTERNS (retry + timeout + circuit breaker)")
    print("   pyresilience vs stacked decorators, 100,000 calls")
    print("=" * 70)

    # pyresilience: one decorator
    @resilient(
        retry=RetryConfig(max_attempts=3, delay=0.01),
        timeout=TimeoutConfig(seconds=10),
        circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
    )
    def pyr_combined():
        return 42

    # stacked: tenacity + pybreaker (no stdlib timeout decorator equivalent)
    breaker2 = pybreaker.CircuitBreaker(fail_max=5)

    @breaker2
    @retry(stop=stop_after_attempt(3), wait=wait_fixed(0.01))
    def stacked_combined():
        return 42

    results = {
        "pyresilience (1 decorator)": timeit(pyr_combined),
        "tenacity + pybreaker (stacked)": timeit(stacked_combined),
    }

    for name, result in results.items():
        print_result(name, result)

    return results


# ═══════════════════════════════════════════════════════════════════════════
# 5. Throughput under concurrent load
# ═══════════════════════════════════════════════════════════════════════════

def bench_throughput():
    print("\n" + "=" * 70)
    print("5. THROUGHPUT (10,000 calls across 10 threads)")
    print("=" * 70)

    n_calls = 10_000
    n_threads = 10

    @resilient(retry=RetryConfig(max_attempts=3, delay=0.001))
    def pyr_func():
        return 42

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(0.001))
    def ten_func():
        return 42

    def measure_throughput(func, name):
        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=n_threads) as pool:
            list(pool.map(lambda _: func(), range(n_calls)))
        elapsed = time.perf_counter() - start
        ops_per_sec = int(n_calls / elapsed)
        print(f"  {name:<20} {elapsed:.3f}s  ({ops_per_sec:,} ops/sec)")
        return ops_per_sec

    results = {}
    results["pyresilience"] = measure_throughput(pyr_func, "pyresilience")
    results["tenacity"] = measure_throughput(ten_func, "tenacity")

    return results


# ═══════════════════════════════════════════════════════════════════════════
# 6. Memory usage
# ═══════════════════════════════════════════════════════════════════════════

def bench_memory():
    print("\n" + "=" * 70)
    print("6. MEMORY USAGE (1,000 decorated functions)")
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

    pyr_mem = measure_memory(pyr_setup)
    ten_mem = measure_memory(ten_setup)

    print(f"  {'pyresilience':<20} current={pyr_mem['current_kb']:>8.1f}KB  peak={pyr_mem['peak_kb']:>8.1f}KB")
    print(f"  {'tenacity':<20} current={ten_mem['current_kb']:>8.1f}KB  peak={ten_mem['peak_kb']:>8.1f}KB")

    return {"pyresilience": pyr_mem, "tenacity": ten_mem}


# ═══════════════════════════════════════════════════════════════════════════
# 7. Async overhead
# ═══════════════════════════════════════════════════════════════════════════

def bench_async():
    print("\n" + "=" * 70)
    print("7. ASYNC OVERHEAD (no-op async function, 50,000 calls)")
    print("=" * 70)

    @resilient(retry=RetryConfig(max_attempts=3, delay=0.01))
    async def pyr_async():
        return 42

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(0.01))
    async def ten_async():
        return 42

    async def measure_async(func, iterations=50_000):
        # Warmup
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
        pyr_result = await measure_async(pyr_async)
        ten_result = await measure_async(ten_async)
        return {"pyresilience": pyr_result, "tenacity": ten_result}

    results = asyncio.run(run())
    for name, result in results.items():
        print_result(name, result)

    return results


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(f"Python {sys.version}")
    print(f"pyresilience installed from PyPI (v0.1.2)")

    all_results = {}
    all_results["overhead"] = bench_overhead()
    all_results["retry"] = bench_retry()
    all_results["circuit_breaker"] = bench_circuit_breaker()
    all_results["combined"] = bench_combined()
    all_results["throughput"] = bench_throughput()
    all_results["memory"] = bench_memory()
    all_results["async"] = bench_async()

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    overhead = all_results["overhead"]
    bare = overhead["bare (no decorator)"]["mean_us"]
    pyr = overhead["pyresilience"]["mean_us"]
    ten = overhead["tenacity"]["mean_us"]
    print(f"\nDecorator overhead vs bare function:")
    print(f"  pyresilience: +{pyr - bare:.2f}us per call")
    print(f"  tenacity:     +{ten - bare:.2f}us per call")

    combined = all_results["combined"]
    pyr_c = combined["pyresilience (1 decorator)"]["mean_us"]
    stk_c = combined["tenacity + pybreaker (stacked)"]["mean_us"]
    if stk_c > pyr_c:
        print(f"\nCombined patterns: pyresilience is {stk_c/pyr_c:.1f}x faster than stacked decorators")
    else:
        print(f"\nCombined patterns: stacked decorators are {pyr_c/stk_c:.1f}x faster than pyresilience")

    print("\nDone.")
