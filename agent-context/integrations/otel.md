# OpenTelemetry Integration

<!-- human-owned -->

`src/pyresilience/contrib/otel.py` defines `OpenTelemetryListener`, a `ResilienceListener` that adds span events to the current active span. `opentelemetry` is imported inside a `try/except ImportError` at module level, setting `_HAS_OTEL`; construction raises `ImportError` with an install hint when it is missing, so importing the module never fails.

---

## Behaviour

- `OpenTelemetryListener(tracer_name="pyresilience")` gets a tracer via `trace.get_tracer`.
- On each event: if the current span is `None` or not recording, nothing happens. Otherwise `span.add_event("pyresilience.<event_type>", attributes)` with `pyresilience.event`, `pyresilience.function`, and, when present, `pyresilience.attempt`, `pyresilience.error_type`, `pyresilience.error_message`, `pyresilience.detail`.
- Pass it in `listeners=[...]` of `@resilient` or `ResilienceConfig`.
- Install hint in code: `pip install opentelemetry-api opentelemetry-sdk` (not declared as a package extra in `pyproject.toml`).

---

## Credentials Summary

<!-- /human-owned -->

<!-- agent-updatable -->

| Component | Dependency | Credentials |
|---|---|---|
| `OpenTelemetryListener` | `opentelemetry-api` (user installed) | none |

<!-- /agent-updatable -->

<!-- human-owned -->

---

## Known Divergences (Do Not Replicate)

- Error messages (`str(event.error)`) are written to span attributes verbatim; avoid adding new attributes that could carry request data or secrets.
- The test for the missing-dependency path was recently made deterministic (see `tests/test_otel.py`); keep the optional import guard pattern when adding listeners.

<!-- /human-owned -->
