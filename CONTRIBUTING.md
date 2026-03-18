# Contributing to pyresilience

Thank you for considering contributing to pyresilience!

## Development Setup

```bash
git clone https://github.com/AhsanSheraz/pyresilience.git
cd pyresilience
make dev
```

## Running Tests

```bash
make test        # Run tests
make test-cov    # Run tests with coverage
make lint        # Run linting
make typecheck   # Run type checking
```

## Code Style

- We use [ruff](https://docs.astral.sh/ruff/) for linting and formatting
- We use [mypy](https://mypy.readthedocs.io/) in strict mode for type checking
- Target Python 3.9+ compatibility

## Pull Request Process

1. Create a feature branch from `main`
2. Make your changes
3. Add tests for new functionality
4. Ensure all checks pass: `make test lint typecheck`
5. Update CHANGELOG.md
6. Submit a pull request
