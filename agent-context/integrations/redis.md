# Redis State Backend

<!-- human-owned -->

`src/pyresilience/contrib/redis.py` provides `RedisBackend`, a `StateBackend` over a synchronous redis-py compatible client (`redis.Redis`, `valkey.Valkey`, ...). The module imports nothing: the caller passes the client in, so no Redis library is a dependency of the package or an extra.

---

## Behaviour

- `RedisBackend(client, prefix="pyresilience:")`: every key gets the prefix.
- Uses only `get`, `set` (with `px` for a TTL), `incrbyfloat`, `pexpire`, `delete` on the client.
- `get` decodes bytes to `str`. `incr` uses `INCRBYFLOAT` (atomic on the server) and sets the expiry in a second call.
- Wire it with `SharedStateConfig(backend=RedisBackend(client), key=...)` (`../domains/shared-state.md`).

---

## Credentials Summary

<!-- /human-owned -->

<!-- agent-updatable -->

| Component | Dependency | Credentials |
|---|---|---|
| `RedisBackend` | none imported; caller supplies a redis-py compatible client | connection credentials live in the caller's client, never in this repo |

<!-- /agent-updatable -->

<!-- human-owned -->

---

## Known Divergences (Do Not Replicate)

- Do not import `redis` or `valkey` in this module; keep it duck-typed.
- Async Redis clients are not supported; the backend methods are synchronous.

<!-- /human-owned -->
