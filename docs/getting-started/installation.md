# Installation

## Basic Install

=== "pip"

    ```bash
    pip install pyresilience
    ```

=== "uv"

    ```bash
    uv pip install pyresilience
    ```

=== "poetry"

    ```bash
    poetry add pyresilience
    ```

## With Performance Backends

For production workloads, install the optional `fast` extras:

```bash
pip install pyresilience[fast]
```

This adds:

| Backend | Language | Benefit |
|---------|----------|---------|
| [uvloop](https://github.com/MagicStack/uvloop) | C | 2-4x faster async event loop (Linux/macOS) |
| [orjson](https://github.com/ijl/orjson) | Rust | ~10x faster JSON for structured logging |

These are **optional** — pyresilience works perfectly with stdlib. The library auto-detects available backends at runtime.

```python
from pyresilience import has_uvloop, has_orjson, install_uvloop

print(has_uvloop())   # True if uvloop is available
print(has_orjson())   # True if orjson is available

install_uvloop()      # Installs uvloop as the default event loop policy
```

## From Source

```bash
git clone https://github.com/AhsanSheraz/pyresilience.git
cd pyresilience
pip install -e ".[dev]"
```

## Requirements

- **Python 3.9+** (tested on 3.9, 3.10, 3.11, 3.12, 3.13, 3.14)
- **No runtime dependencies** — pure Python stdlib
- Runs on **Linux, macOS, and Windows**

## Verify Installation

```python
import pyresilience
print(pyresilience.__version__)  # 0.1.0
```
