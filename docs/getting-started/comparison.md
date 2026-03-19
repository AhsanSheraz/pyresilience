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

| Library | Python 3.10 | Python 3.12 | Python 3.13 | Python 3.14 |
|---------|----------:|----------:|----------:|----------:|
| bare (no decorator) | 0.12us | 0.08us | 0.04us | 0.11us |
| **pyresilience** | **0.67us** | **0.58us** | **0.55us** | **0.56us** |
| tenacity | 10.75us | 7.80us | 7.47us | 7.09us |
| backoff | 1.66us | 1.65us | 1.53us | 1.49us |
| stamina | 9.31us | 7.49us | 7.03us | 6.72us |
| pybreaker | 1.25us | 0.91us | 0.86us | 0.83us |

**pyresilience is 12-16x faster than tenacity on the happy path.**

### Retry Performance (fail 2x, succeed on 3rd, 10k calls)

| Library | Python 3.10 | Python 3.12 | Python 3.13 | Python 3.14 |
|---------|----------:|----------:|----------:|----------:|
| **pyresilience** | 3,786us | 3,807us | 3,828us | 3,834us |
| tenacity | 2,681us | 2,667us | 2,703us | 2,678us |
| backoff | 1,371us | 1,380us | 1,423us | 1,398us |
| stamina | 2,809us | 2,742us | 2,833us | 2,767us |

!!! note
    Retry timings are dominated by `time.sleep(0.001)` which has ~1.2ms OS scheduler overhead per call. pyresilience's higher time reflects its full pipeline (circuit breaker tracking, event system) running on every attempt.

### Individual Pattern Overhead (Python 3.14, 100k calls)

| Pattern | Mean Latency |
|---------|----------:|
| Retry (happy path) | 0.56us |
| Circuit Breaker | 1.04us |
| Fallback (triggered) | 0.90us |
| Bulkhead | 1.09us |
| Rate Limiter | 0.86us |
| Cache (hit) | 0.95us |
| **All 7 patterns (cache hit)** | **0.98us** |

### Throughput (10k calls, 10 threads)

| Library | Python 3.10 | Python 3.12 | Python 3.13 | Python 3.14 |
|---------|----------:|----------:|----------:|----------:|
| **pyresilience** | **145,942** | **172,508** | **228,151** | **228,685** |
| tenacity | 44,980 | 73,735 | 80,909 | 84,348 |

**pyresilience achieves 2.7-3.2x higher throughput under concurrent load.**

### Async Overhead (50k calls)

| Library | Python 3.10 | Python 3.12 | Python 3.13 | Python 3.14 |
|---------|----------:|----------:|----------:|----------:|
| **pyresilience** | **0.79us** | **0.73us** | **0.66us** | **0.72us** |
| tenacity | 20.46us | 17.27us | 20.51us | 20.14us |

**pyresilience is 24-31x faster than tenacity for async functions.**

### Memory (1,000 decorated functions)

| Library | Python 3.10 | Python 3.12 | Python 3.13 | Python 3.14 |
|---------|----------:|----------:|----------:|----------:|
| **pyresilience** | **1,528 KB** | **1,290 KB** | **1,295 KB** | **1,202 KB** |
| tenacity | 2,416 KB | 2,192 KB | 2,336 KB | 2,254 KB |

**pyresilience uses ~45% less memory.**

## When to Use pyresilience

**Use pyresilience when you need:**

- Multiple resilience patterns working together
- A single, clean API instead of stacking decorators
- Consistent observability across all patterns
- Shared circuit breaker state across functions
- Production presets for common integration patterns
- Retry, circuit breaker, timeout, fallback, bulkhead, rate limiter, or cache — individually or combined
