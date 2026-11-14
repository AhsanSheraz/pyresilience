# Agent Index - pyresilience

This file is the router for all agent-facing context. Stable rules and the
quick start live in the root `AGENTS.md`. Detail lives in the files below.

---

## Section Markers (read this once)

Inside every doc, sections are marked for who owns them:

- `<!-- agent-updatable -->` ... `<!-- /agent-updatable -->`
  Catalogs and inventories of things that exist (public API catalog, exception
  tables, integration lists). Add a row when you add a new thing. Do not rewrite
  existing rows for routine changes.

- `<!-- human-owned -->` ... `<!-- /human-owned -->`
  Conventions, patterns, "What NOT to Do" sections. Agents must read these
  and follow them. **Never edit human-owned sections.** If something needs
  to change, see the workflow below.

Anything unmarked defaults to **human-owned**.

### When you think a human-owned section needs to change

Three cases, same workflow:

- **Confused** - the rule is unclear. Ask before acting.
- **Outdated** - the rule no longer matches what the code does. Flag it as
  a finding with file:line evidence, propose the new wording, wait for the human.
- **In conflict** - your task seems to require violating the rule. Stop and
  surface the conflict; ask whether to comply, refactor to comply, or change
  the rule first.

The agent surfaces, the human decides. Never silently edit a human-owned
section, never silently ignore a convention, never silently violate a rule.

---

## Directory Tree (agent-context/)

```
agent-context/
├── AGENT_INDEX.md              <- this file
├── business-context.md         <- what the library is for, actors, invariants
├── architecture.md             <- layers, pipeline overview, tech stack, directories
├── conventions.md              <- naming, typing (3.9), logging, concurrency
├── api-conventions.md          <- public Python API catalog (__all__), how to add symbols
├── error-handling.md           <- exceptions, config validation messages
├── testing.md                  <- test layout, async mode, no-mock rule, coverage gate
├── infrastructure.md           <- build, CI, PyPI/RTD publishing
├── glossary.md                 <- terms, EventType and CircuitState values
├── integrations/               <- optional adapters and optional deps
│   ├── fastapi.md  django.md  flask.md  http.md
│   ├── otel.md  prometheus.md
│   ├── redis.md                <- Redis state backend
│   └── perf-deps.md            <- uvloop / orjson
└── domains/                    <- pattern internals
    ├── executor-pipeline.md    <- order of patterns, registry, shutdown
    ├── retry.md                <- retry loop, backoff, retry budget
    ├── circuit-breaker.md      <- state machine, sliding window
    ├── rate-limiting.md        <- plain and weighted limiters, feedback
    ├── fallback.md             <- handler, alternatives, cooldown
    └── shared-state.md         <- registry sharing, state backends, sync pass
```

---

## Topic -> File Mapping

| Topic | File |
|---|---|
| What is this library, who uses it, why zero deps | `business-context.md` |
| Module layout, layers, tech stack | `architecture.md` |
| Naming, Python 3.9 typing rules, logging, locks | `conventions.md` |
| What is public, how to add an exported symbol | `api-conventions.md` |
| Exceptions raised, `__post_init__` validation | `error-handling.md` |
| Writing or running tests, coverage gate | `testing.md` |
| Build, CI jobs, publishing, docs hosting | `infrastructure.md` |
| Domain terms, event types | `glossary.md` |
| Order of patterns, registry sharing, timeouts, shutdown | `domains/executor-pipeline.md` |
| Retry loop, `retry_on_result`, `delay_func`, budget | `domains/retry.md` |
| Circuit breaker states and sliding window | `domains/circuit-breaker.md` |
| FastAPI / Django / Flask adapters | `integrations/fastapi.md`, `integrations/django.md`, `integrations/flask.md` |
| HTTP status and Retry-After helpers | `integrations/http.md` |
| OpenTelemetry / Prometheus listeners | `integrations/otel.md`, `integrations/prometheus.md` |
| uvloop / orjson detection | `integrations/perf-deps.md` |
| Rate limits, weighted costs, server feedback | `domains/rate-limiting.md` |
| Fallback alternatives, cooldown | `domains/fallback.md` |
| Shared state, state backends, registry sharing | `domains/shared-state.md` |
| Redis backend | `integrations/redis.md` |

---

## Boundary Rules (where new docs go)

Top-level files are universal singletons; plural folders hold variable-count items.

- **`integrations/`** - one file per optional adapter or optional third-party
  package the library detects or integrates with. Short lowercase names. Every
  integration doc ends with `## Known Divergences (Do Not Replicate)`.
- **`domains/`** - one file per pattern or subsystem with real state or ordering
  rules (3+ states, load-bearing invariants, sync/async twin code). Plain
  small modules (bulkhead, rate limiter, cache) stay in `architecture.md` and
  `domains/executor-pipeline.md`.
- **`business-context.md`** - exactly one; product framing only.
- This repo has no database, authentication or HTTP surface, so there are no
  files for those topics.

---

## Feature Catalogue

<!-- agent-updatable -->

| Feature | Key Files | Doc |
|---|---|---|
| `@resilient` decorator | `src/pyresilience/_decorator.py` | `domains/executor-pipeline.md` |
| Executor pipeline | `src/pyresilience/_executor.py` | `domains/executor-pipeline.md` |
| Retry, retry budget, `retry_on_result`, `delay_func` | `src/pyresilience/_executor.py`, `_retry_budget.py`, `_types.py` | `domains/retry.md` |
| Circuit breaker (consecutive, sliding window) | `src/pyresilience/_circuit_breaker.py` | `domains/circuit-breaker.md` |
| Timeout (thread pool sync, `wait_for` async), overall deadline, stream idle timeout | `src/pyresilience/_executor.py`, `_stream.py` | `domains/executor-pipeline.md` |
| Bulkhead, result cache | `_bulkhead.py`, `_cache.py` | `architecture.md`, `domains/executor-pipeline.md` |
| Rate limiting (plain, weighted, multi-limit, server feedback) | `_rate_limiter.py`, `_limiter_core.py`, `_weighted_limiter.py` | `domains/rate-limiting.md` |
| Fallback handler, alternatives, cooldown | `_fallback.py` | `domains/fallback.md` |
| Shared state (in-process via registry, cross-process via backend) | `_parts.py`, `_backend.py`, `_shared.py`, `_shared_breaker.py`, `contrib/redis.py` | `domains/shared-state.md`, `integrations/redis.md` |
| Registry (shared named state; sync and async share breaker, limits, budget, cooldown) | `src/pyresilience/_registry.py`, `_parts.py` | `domains/executor-pipeline.md`, `domains/shared-state.md` |
| Presets | `src/pyresilience/_presets.py`, `presets.py` | `api-conventions.md` |
| Events, logging, metrics, context | `src/pyresilience/_logging.py`, `_types.py` | `glossary.md` |
| Health check, graceful shutdown | `_health.py`, `_executor.py` | `domains/executor-pipeline.md` |
| Framework, telemetry, HTTP and Redis adapters | `src/pyresilience/contrib/` | `integrations/` |

<!-- /agent-updatable -->
