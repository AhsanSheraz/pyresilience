# Optional Performance Dependencies (uvloop, orjson)

<!-- human-owned -->

`src/pyresilience/_compat.py` and `src/pyresilience/_logging.py` detect `uvloop` and `orjson` without importing them at module load. They are declared only under the `fast` extra in `pyproject.toml` (`uvloop>=0.17.0; sys_platform != 'win32'`, `orjson>=3.9.0`).

---

## Behaviour

- `has_uvloop()`: false on `win32`, otherwise `importlib.util.find_spec("uvloop")`. `has_orjson()`: `find_spec("orjson")`. Both are public (`__all__`).
- `install_uvloop()`: sets `uvloop.EventLoopPolicy()` through `asyncio.set_event_loop_policy`; returns `False` when uvloop is missing or any exception occurs. It is never called automatically.
- `get_json_dumps()` in `_compat.py` returns `orjson.dumps` or `json.dumps`.
- `JsonEventLogger` uses `_logging._make_dumps()`: with orjson it decodes `orjson.dumps(obj)` to `str`; otherwise `json.dumps(obj, default=str)`.

---

## Credentials Summary

<!-- /human-owned -->

<!-- agent-updatable -->

| Component | Dependency | Credentials |
|---|---|---|
| `_compat.py` helpers, `JsonEventLogger` | uvloop, orjson (extra `fast`) | none |

<!-- /agent-updatable -->

<!-- human-owned -->

---

## Known Divergences (Do Not Replicate)

- The orjson branch of `_make_dumps` does not pass a `default=str` fallback like the stdlib branch, so non-JSON-serializable event fields can behave differently depending on whether orjson is installed. When adding event fields, keep them JSON-native or convert them in `_event_to_dict`. <!-- verify: exact orjson failure mode unconfirmed -->
- Never import `uvloop` or `orjson` at module top level in core; use `find_spec` or a local import as `_compat.py` does.

<!-- /human-owned -->
