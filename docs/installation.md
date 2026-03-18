# Installation

## pip

```bash
pip install pyresilience
```

## With performance backends

```bash
pip install pyresilience[fast]
```

This installs `uvloop` (C-based event loop, Linux/macOS only) and `orjson` (Rust-based JSON serialization) for faster async operations and structured logging.

## uv

```bash
uv pip install pyresilience
```

## From source

```bash
git clone https://github.com/AhsanSheraz/pyresilience.git
cd pyresilience
pip install -e ".[dev]"
```

## Requirements

- Python 3.9+
- No runtime dependencies
