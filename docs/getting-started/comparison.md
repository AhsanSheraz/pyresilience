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
| bare (no decorator) | 0.12us | 0.08us | 0.04us | 0.05us |
| **pyresilience** | **0.67us** | **0.58us** | **0.55us** | **0.56us** |
| tenacity | 10.75us | 7.80us | 7.47us | 7.31us |
| backoff | 1.66us | 1.65us | 1.53us | 1.52us |
| stamina | 9.31us | 7.49us | 7.03us | 6.90us |
| pybreaker | 1.25us | 0.91us | 0.86us | 0.87us |

**pyresilience is 12-13x faster than tenacity on the happy path.**

### Retry Performance (fail 2x, succeed on 3rd, 10k calls)

| Library | Python 3.10 | Python 3.12 | Python 3.13 | Python 3.14 |
|---------|----------:|----------:|----------:|----------:|
| **pyresilience** | 3,786us | 3,807us | 3,828us | 3,821us |
| tenacity | 2,681us | 2,667us | 2,703us | 2,709us |
| backoff | 1,371us | 1,380us | 1,423us | 1,380us |
| stamina | 2,809us | 2,742us | 2,833us | 2,921us |

!!! note
    Retry timings are dominated by `time.sleep(0.001)` which has ~1.2ms OS scheduler overhead per call. pyresilience's higher time reflects its full pipeline (circuit breaker tracking, event system) running on every attempt.

### Individual Pattern Overhead (Python 3.14, 100k calls)

| Pattern | Mean Latency |
|---------|----------:|
| Retry (happy path) | 0.55us |
| Circuit Breaker | 0.99us |
| Fallback (triggered) | 0.67us |
| Bulkhead | 0.78us |
| Rate Limiter | 0.84us |
| Cache (hit) | 0.66us |
| **All 7 patterns (cache hit)** | **0.66us** |

### Throughput (10k calls, 10 threads)

| Library | Python 3.10 | Python 3.12 | Python 3.13 | Python 3.14 |
|---------|----------:|----------:|----------:|----------:|
| **pyresilience** | **145,942** | **172,508** | **228,151** | **241,822** |
| tenacity | 44,980 | 73,735 | 80,909 | 86,976 |

**pyresilience achieves 2.8-3.2x higher throughput under concurrent load.**

### Async Overhead (50k calls)

| Library | Python 3.10 | Python 3.12 | Python 3.13 | Python 3.14 |
|---------|----------:|----------:|----------:|----------:|
| **pyresilience** | **0.79us** | **0.73us** | **0.66us** | **0.72us** |
| tenacity | 20.46us | 17.27us | 20.51us | 19.85us |

**pyresilience is 24-28x faster than tenacity for async functions.**

### Memory (1,000 decorated functions)

| Library | Python 3.10 | Python 3.12 | Python 3.13 | Python 3.14 |
|---------|----------:|----------:|----------:|----------:|
| **pyresilience** | **1,528 KB** | **1,290 KB** | **1,295 KB** | **1,104 KB** |
| tenacity | 2,416 KB | 2,192 KB | 2,336 KB | 2,255 KB |

**pyresilience uses ~51% less memory.**

## When to Use pyresilience

**Use pyresilience when you need:**

- Multiple resilience patterns working together
- A single, clean API instead of stacking decorators
- Consistent observability across all patterns
- Shared circuit breaker state across functions
- Production presets for common integration patterns
- Retry, circuit breaker, timeout, fallback, bulkhead, rate limiter, or cache — individually or combined
