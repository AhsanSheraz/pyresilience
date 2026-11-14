"""Benchmark: compare the working tree against a git ref (default: main).

Run: python benchmarks/bench_compare.py [ref] [rounds]

Exports the ref into a temporary directory and runs ``bench_overhead.py`` (the
ref's copy, so both sides measure identical configurations) against each source
tree in alternating rounds. Alternating cancels drift in machine load, and the
minimum per configuration is reported. Use it before merging a change to the
hot path: absolute numbers move with the machine, the difference does not.

Requires git. No third-party packages.
"""

from __future__ import annotations

import io
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROW = re.compile(r"^(.+?)\s+([\d.]+)\s+([\d.]+) us")


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


def run_once(script: Path, source: Path) -> dict[str, float]:
    """Run the benchmark with *source* on the import path; return us per call."""
    env = dict(os.environ, PYTHONPATH=str(source))
    output = subprocess.run(
        [sys.executable, str(script)], env=env, capture_output=True, text=True, check=True
    ).stdout
    results: dict[str, float] = {}
    for line in output.splitlines():
        match = ROW.match(line)
        if match:
            results[match.group(1).strip()] = float(match.group(3))
    return results


def main() -> None:
    ref = sys.argv[1] if len(sys.argv) > 1 else "main"
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    repo = Path(__file__).resolve().parent.parent

    with tempfile.TemporaryDirectory() as tmp:
        baseline = Path(tmp)
        export_ref(repo, ref, baseline)
        script = baseline / "benchmarks" / "bench_overhead.py"
        sources = {ref: baseline / "src", "working tree": repo / "src"}

        best: dict[str, dict[str, float]] = {name: {} for name in sources}
        for round_number in range(1, rounds + 1):
            print(f"round {round_number}/{rounds}", file=sys.stderr)
            for name, source in sources.items():
                for label, per_call in run_once(script, source).items():
                    previous = best[name].get(label)
                    if previous is None or per_call < previous:
                        best[name][label] = per_call

    print(f"\nMinimum of {rounds} alternating rounds, microseconds per call\n")
    print(f"{'Configuration':<34}{ref:>10}{'tree':>10}{'delta':>10}{'change':>9}")
    print("-" * 73)
    for label, before in best[ref].items():
        after = best["working tree"].get(label)
        if after is None:
            continue
        delta = after - before
        change = delta / before * 100 if before else 0.0
        print(f"{label:<34}{before:>10.3f}{after:>10.3f}{delta:>+10.3f}{change:>+8.1f}%")


if __name__ == "__main__":
    main()
