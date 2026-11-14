"""Benchmark: compare the working tree against a git ref (default: main).

Run: python benchmarks/bench_compare.py [ref] [rounds]

Exports the ref into a temporary directory and times the configurations of
``bench_overhead.py`` (the ref's copy, so both sides measure the same functions)
against each source tree. Rounds are short and alternate between the two trees:
every round times each configuration with ``timeit`` and keeps the best of seven
repeats. Short alternating rounds cancel drift in machine load far better than
two long runs, so use this before merging a change to the hot path. Absolute
numbers move with the machine; the difference does not.

Reports the median and the minimum over all rounds. Requires git, no
third-party packages.
"""

from __future__ import annotations

import io
import os
import statistics
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

# Runs in a subprocess with one source tree on PYTHONPATH. argv[1] is the
# directory holding the bench_overhead.py to import.
TIMER = r"""
import sys, timeit
sys.path.insert(0, sys.argv[1])
import bench_overhead as bench

cases = [
    ("@resilient (default retry)", "with_default_retry", {}, 100000),
    ("retry only", "with_retry_only", {}, 100000),
    ("retry + ignore_on (happy path)", "with_retry_ignore_on", {}, 100000),
    ("retry + delay_func (happy path)", "with_retry_delay_func", {}, 100000),
    ("retry + timeout", "with_retry_timeout", {}, 3000),
    ("retry + circuit breaker", "with_retry_circuit", {}, 100000),
    ("all patterns (no cache)", "with_all_patterns", {}, 3000),
    ("cache (hit)", "with_cache", {"x": 99}, 100000),
]
for label, name, kwargs, number in cases:
    func = getattr(bench, name, None)
    if func is None:  # the ref predates this configuration
        continue
    func(**kwargs)
    best = min(timeit.repeat(lambda: func(**kwargs), number=number, repeat=7))
    print(f"{label}|{best / number * 1e6:.4f}")
"""


def export_ref(repo: Path, ref: str, target: Path) -> None:
    """Extract ``src/`` and ``benchmarks/`` of *ref* into *target*."""
    archive = subprocess.run(
        ["git", "archive", ref, "src", "benchmarks"],
        cwd=repo,
        capture_output=True,
        check=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(target)


def time_once(bench_dir: Path, source: Path) -> dict[str, float]:
    """Time every configuration with *source* on the import path; return us per call."""
    env = dict(os.environ, PYTHONPATH=str(source))
    output = subprocess.run(
        [sys.executable, "-c", TIMER, str(bench_dir)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    results: dict[str, float] = {}
    for line in output.splitlines():
        label, _, value = line.partition("|")
        if value:
            results[label] = float(value)
    return results


def main() -> None:
    ref = sys.argv[1] if len(sys.argv) > 1 else "main"
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 25
    repo = Path(__file__).resolve().parent.parent

    with tempfile.TemporaryDirectory() as tmp:
        baseline = Path(tmp)
        export_ref(repo, ref, baseline)
        bench_dir = baseline / "benchmarks"
        sources = {ref: baseline / "src", "working tree": repo / "src"}

        samples: dict[str, dict[str, list[float]]] = {name: {} for name in sources}
        for round_number in range(1, rounds + 1):
            print(f"round {round_number}/{rounds}", file=sys.stderr)
            for name, source in sources.items():
                for label, per_call in time_once(bench_dir, source).items():
                    samples[name].setdefault(label, []).append(per_call)

    print(f"\n{rounds} alternating rounds, microseconds per call\n")
    print(
        f"{'Configuration':<34}{'median':>9}{'median':>9}{'change':>9}"
        f"{'min':>9}{'min':>9}{'change':>9}"
    )
    print(f"{'':<34}{ref[:8]:>9}{'tree':>9}{'':>9}{ref[:8]:>9}{'tree':>9}")
    print("-" * 88)
    for label, before in samples[ref].items():
        after = samples["working tree"].get(label)
        if not after:
            continue
        med_a, med_b = statistics.median(before), statistics.median(after)
        min_a, min_b = min(before), min(after)
        print(
            f"{label:<34}{med_a:>9.3f}{med_b:>9.3f}{(med_b - med_a) / med_a * 100:>+8.1f}%"
            f"{min_a:>9.3f}{min_b:>9.3f}{(min_b - min_a) / min_a * 100:>+8.1f}%"
        )


if __name__ == "__main__":
    main()
