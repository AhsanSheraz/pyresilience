# Infrastructure

There is no deployed infrastructure. This file covers build, CI and publishing.

<!-- human-owned -->

## Build

- Backend: hatchling (`[build-system]` in `pyproject.toml`); wheel packages `src/pyresilience`; sdist includes `src/pyresilience`, `README.md`, `LICENSE`, `CHANGELOG.md`.
- Dev tooling uses `uv`: `make dev` (`uv pip install -e ".[dev]"`), `make build` (`uv build`).
- Version lives in two places that must match: `[project] version` in `pyproject.toml` and `__version__` in `src/pyresilience/__init__.py`.

### Annotation Processor / Codegen Ordering

Not applicable.

## Profiles

Not applicable. Optional extras: `fast` (uvloop on non-Windows, orjson), `dev`.

## Containerization

None.

## Deployment

Distribution only: PyPI (package) and Read the Docs (documentation).

## Local Development

1. `make dev`
2. `make test` (or `make test-cov` for the 95% branch gate)
3. `make lint` and `make typecheck` before pushing; `pre-commit run --all-files` mirrors them.
4. `make docs` to preview mkdocs.

## Observability

### Health and Metrics

`health_check(registry)` in `src/pyresilience/_health.py` returns, per registered name that has a circuit breaker, `{"circuit_breaker": {"state", "failure_count"}}`. It does not report in-flight calls or rate limiter state.

### Logging

`pyresilience` logger; see `integrations/otel.md`, `integrations/prometheus.md` and `architecture.md`.

<!-- /human-owned -->

<!-- agent-updatable -->

## External Services Used

| Service | Purpose | Config / wiring |
|---|---|---|
| PyPI | Package distribution | `.github/workflows/ci.yml` `publish` job, `environment: pypi`, `id-token: write` (trusted publishing, no stored token) |
| Read the Docs | Hosted docs | `.readthedocs.yml` (Python 3.12, `mkdocs.yml`, `docs/requirements.txt`) |
| GitHub Pages (mkdocs gh-deploy) | Docs deploy on pushes touching `docs/**` or `mkdocs.yml` | `.github/workflows/docs.yml` |
| Codecov | Coverage upload | `ci.yml` `coverage` job (uses the `CODECOV_TOKEN` repository secret) |
| Redis (optional, user-supplied) | Cross-process shared state through `contrib/redis.py` `RedisBackend`; no Redis library is a dependency | `integrations/redis.md` |
| Dependabot | Dependency PRs | `.github/dependabot.yml`, `.github/workflows/auto-merge-dependabot.yml` |

## Benchmarks

`benchmarks/README.md` documents them. `bench_overhead.py` (per-pattern overhead), `bench_new_features.py` (0.5.0 features), `bench_compare.py` (working tree against a git ref, default `main`, alternating rounds), `full_benchmark.py` and `stress_test.py` (against tenacity, backoff, stamina, pybreaker; these are not dependencies).

## CI Python Matrix

`.github/workflows/ci.yml` `test` job: Python 3.10 to 3.15 on ubuntu, macos, windows. `tox.ini` envlist: py39 to py315, lint, typecheck. `pyproject.toml` classifiers list 3.10 to 3.15.

<!-- /agent-updatable -->

<!-- human-owned -->

## CI/CD

`.github/workflows/ci.yml` runs on pushes to `main`, `v*` tags and PRs to `main`:

- `test`: ubuntu/macos/windows x Python 3.10 to 3.15 (`pytest -v`). Python 3.9 is not in the CI matrix; it is only listed in `tox.ini`.
- `coverage`: Python 3.12, `--cov-branch --cov-fail-under=95`, uploads to Codecov.
- `lint`: `ruff check` and `ruff format --check` on `src/ tests/`.
- `type-check`: `mypy src/pyresilience`.
- `ci-pass`: aggregator requiring the four jobs above.
- `publish`: runs on pushed `v*` tags after `test`, `lint`, `type-check`; `uv build` then `pypa/gh-action-pypi-publish`.

## What NOT to Do

- Do NOT modify `.github/workflows/*.yml`, `pyproject.toml`, `ruff.toml`, `tox.ini`, `mkdocs.yml`, `.readthedocs.yml` or `.pre-commit-config.yaml` without explicit approval.
- Do NOT add stored PyPI tokens; publishing relies on trusted publishing.
- Do NOT bump only one of the two version locations.
- Do NOT bypass hooks with `--no-verify`.

<!-- /human-owned -->
