# Contributing to SensorWatch

Thank you for considering a contribution. SensorWatch is a focused portfolio project, so
small, well-tested changes are easier to review than broad rewrites.

## Development setup

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
ruff check .
pytest --cov=sensorwatch --cov-report=term-missing
```

Activate the virtual environment before installing dependencies. On Windows PowerShell, use
`.venv\Scripts\Activate.ps1`; on macOS or Linux, use `source .venv/bin/activate`.

## Pull requests

1. Open an issue for substantial behavior or architecture changes.
2. Keep each pull request focused on one problem.
3. Add or update tests for behavior changes.
4. Run linting and the complete test suite locally.
5. Explain the motivation, implementation, and validation in the pull request description.

Do not include production credentials, private sensor data, database files, or generated build
artifacts in a contribution.

## Reporting defects

Include the Python version, operating system, reproduction steps, expected result, and actual
result. For detector issues, include a minimal synthetic sequence rather than confidential
telemetry. Report security vulnerabilities privately according to [SECURITY.md](SECURITY.md).
