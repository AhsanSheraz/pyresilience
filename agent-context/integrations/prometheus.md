# Prometheus Integration

<!-- human-owned -->

`src/pyresilience/contrib/prometheus.py` defines `PrometheusListener`, a `ResilienceListener` that increments a counter per event and observes call duration. `prometheus_client` is imported under `try/except ImportError` (`_HAS_PROMETHEUS`); construction raises `ImportError` with an install hint when it is missing.

---

## Metrics

- `PrometheusListener(namespace="pyresilience", subsystem="")` creates, in the default registry of `prometheus_client`:
  - Counter `<namespace>_events_total` with labels `event_type`, `function_name`.
  - Histogram `<namespace>_call_duration_seconds` with label `function_name`; observed whenever `event.duration is not None` (set on SUCCESS events).
- Install hint in code: `pip install prometheus-client` (not declared as a package extra in `pyproject.toml`).

---

## Credentials Summary

<!-- /human-owned -->

<!-- agent-updatable -->

| Component | Dependency | Credentials |
|---|---|---|
| `PrometheusListener` | `prometheus-client` (user installed) | none |

<!-- /agent-updatable -->

<!-- human-owned -->

---

## Known Divergences (Do Not Replicate)

- Metrics are registered at construction time in the default registry, so creating two listeners with the same namespace and subsystem in one process will hit prometheus_client duplicate-name errors; create one listener and share it. <!-- verify: duplicate registration behaviour not exercised by a test in this repo -->
- `function_name` is a label with unbounded cardinality if dynamic function names are decorated; do not add more high-cardinality labels.

<!-- /human-owned -->
