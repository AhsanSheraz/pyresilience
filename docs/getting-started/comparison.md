# Comparison with Other Libraries

## Python Ecosystem

| Feature | pyresilience | tenacity | backoff | pybreaker | stamina |
|---------|-------------|----------|---------|-----------|---------|
| Retry | Yes | Yes | Yes | No | Yes |
| Circuit Breaker | Yes | No | No | Yes | No |
| Timeout | Yes | No | No | No | No |
| Fallback | Yes | No | No | No | No |
| Bulkhead | Yes | No | No | No | No |
| Rate Limiter | Yes | No | No | No | No |
| Cache | Yes | No | No | No | No |
| Retry Budget | Yes | No | No | No | No |
| Context Propagation | Yes | No | No | No | No |
| Health Check | Yes | No | No | No | No |
| Prometheus | Yes | No | No | No | No |
| OpenTelemetry | Yes | No | No | No | No |
| Registry | Yes | No | No | No | No |
| Unified API | Yes | N/A | N/A | N/A | N/A |
| Async Support | Yes | Yes | Yes | No | Yes |
| Zero Dependencies | Yes | Yes | No | No | No |
| Type-Safe | Yes | Partial | Partial | No | Yes |

*Comparison reflects built-in capabilities and unified API model, not every possible custom composition.*

## Performance Benchmarks

Benchmarked on macOS (Apple Silicon) across Python 3.10 — 3.14. Run it yourself:

```bash
pip install pyresilience tenacity backoff stamina pybreaker
python benchmarks/full_benchmark.py
```

Full benchmark code in [`benchmarks/`](https://github.com/AhsanSheraz/pyresilience/tree/main/benchmarks).

### Decorator Overhead (no-op function, 100k calls)

| Library | Mean | vs pyresilience |
|---------|-----:|-----:|
| bare (no decorator) | 0.07μs | — |
| **pyresilience** | **0.64μs** | **1.0x** |
| pybreaker | 0.64μs | 1.0x |
| backoff | 1.29μs | 2.0x slower |
| stamina | 5.33μs | 8.3x slower |
| tenacity | 6.64μs | 10.4x slower |

**pyresilience is 10.4x faster than tenacity on the happy path.**

### Retry Performance (fail 2x, succeed on 3rd, 10k calls)

| Library | Mean |
|---------|-----:|
| backoff | 1,366μs |
| tenacity | 2,655μs |
| stamina | 2,834μs |
| **pyresilience** | **3,791μs** |

!!! note
    Retry timings are dominated by `time.sleep(0.001)` which has ~1.2ms OS scheduler overhead per call. pyresilience's higher time reflects its full pipeline (circuit breaker tracking, event system) running on every attempt.

### Individual Pattern Overhead (100k calls)

| Pattern | Mean Latency |
|---------|----------:|
| Retry (happy path) | 0.64μs |
| Circuit Breaker | 1.03μs |
| Fallback (triggered) | 0.69μs |
| Bulkhead | 0.74μs |
| Rate Limiter | 0.89μs |
| Cache (hit) | 0.68μs |
| **All 7 patterns (cache hit)** | **0.67μs** |

### Throughput (10k calls, 10 threads)

| Library | ops/sec |
|---------|--------:|
| **pyresilience** | **223,934** |
| tenacity | 58,109 |

**pyresilience achieves 3.9x higher throughput under concurrent load.**

### Async Overhead (50k calls)

| Library | Mean |
|---------|-----:|
| **pyresilience** | **0.82μs** |
| tenacity | 11.83μs |

**pyresilience is 14.4x faster than tenacity for async functions.**

### Memory (1,000 decorated functions)

| Library | Memory |
|---------|-------:|
| **pyresilience** | **1,224 KB** |
| tenacity | 2,150 KB |

**pyresilience uses 43% less memory.**

## When to Use pyresilience

**Use pyresilience when you need:**

- Multiple resilience patterns working together
- A single, clean API instead of stacking decorators
- Consistent observability across all patterns
- Shared circuit breaker state across functions
- Production presets for common integration patterns
- Retry, circuit breaker, timeout, fallback, bulkhead, rate limiter, or cache — individually or combined
