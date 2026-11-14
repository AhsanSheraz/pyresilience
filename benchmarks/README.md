# Benchmarks

Scripts that measure what pyresilience adds to a call. Run them from the repository
root with the package installed (`uv pip install -e ".[dev]"`).

| Script | What it measures | Extra packages |
|---|---|---|
| `bench_overhead.py` | Decorator overhead per pattern on the happy path | none |
| `bench_new_features.py` | Overhead of the 0.5.0 features: weighted and multi-limit rate limiting, reconcile and server feedback, overall deadline, fallback alternatives and cooldown, shared state, registry sharing, stream idle timeout | none |
| `bench_compare.py` | Working tree against a git ref (default `main`), alternating rounds | none (needs git) |
| `full_benchmark.py` | pyresilience against tenacity, backoff, stamina and pybreaker | `tenacity backoff stamina pybreaker` |
| `stress_test.py` | Throughput and latency under threads, against the same libraries | `tenacity backoff stamina pybreaker` |

```bash
python benchmarks/bench_overhead.py
python benchmarks/bench_new_features.py
python benchmarks/bench_compare.py            # working tree vs main, 5 rounds
python benchmarks/bench_compare.py v0.4.1 9   # vs a tag, 9 rounds
```

The comparison libraries are not dependencies of pyresilience. Install them in a
separate environment when you want to run the last two scripts:

```bash
uv venv .bench-venv
uv pip install --python .bench-venv tenacity backoff stamina pybreaker
PYTHONPATH=src .bench-venv/bin/python benchmarks/full_benchmark.py
```

## Reading the numbers

- Absolute numbers depend on the machine and its load. The figures published in
  the project README and docs come from one Apple Silicon Mac; do not mix numbers
  from different machines in one table.
- To judge a change, compare relative results on one machine with
  `bench_compare.py`. Differences of a few percent are run-to-run noise; use more
  rounds (for example 9) on a quiet machine before drawing a conclusion.
- Sync timeouts run the call in a worker thread, so any configuration with a
  `TimeoutConfig` on a sync function costs tens of microseconds per call. Async
  timeouts do not.
