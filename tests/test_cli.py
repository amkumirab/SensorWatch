from __future__ import annotations

import sys
from typing import Any

from sensorwatch import __main__ as cli


def test_migrate_command_runs_database_upgrade(monkeypatch: Any) -> None:
    calls: list[str] = []
    monkeypatch.setattr(sys, "argv", ["sensorwatch", "migrate"])
    monkeypatch.setattr(cli, "upgrade_database", lambda: calls.append("migrate"))

    cli.main()

    assert calls == ["migrate"]


def test_default_command_starts_local_server(monkeypatch: Any) -> None:
    calls: list[tuple[str, str, int, bool]] = []
    monkeypatch.setattr(sys, "argv", ["sensorwatch"])
    monkeypatch.setattr(
        cli.uvicorn,
        "run",
        lambda app, *, host, port, reload: calls.append((app, host, port, reload)),
    )

    cli.main()

    assert calls == [("sensorwatch.api:app", "127.0.0.1", 8000, False)]


def test_serve_command_accepts_network_options(monkeypatch: Any) -> None:
    calls: list[tuple[str, str, int, bool]] = []
    monkeypatch.setattr(
        sys,
        "argv",
        ["sensorwatch", "serve", "--host", "0.0.0.0", "--port", "9000", "--reload"],
    )
    monkeypatch.setattr(
        cli.uvicorn,
        "run",
        lambda app, *, host, port, reload: calls.append((app, host, port, reload)),
    )

    cli.main()

    assert calls == [("sensorwatch.api:app", "0.0.0.0", 9000, True)]
