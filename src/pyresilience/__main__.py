"""Allow running pyresilience as a module: python -m pyresilience."""

from __future__ import annotations

import pyresilience


def main() -> None:
    print(f"pyresilience v{pyresilience.__version__}")
    print("Unified resilience patterns for Python")
    print("https://github.com/AhsanSheraz/pyresilience")


if __name__ == "__main__":
    main()
