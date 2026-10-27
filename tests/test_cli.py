from __future__ import annotations

import sys
from typing import Any

import pytest

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


def test_monitor_command_dispatches_once(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["sensorwatch", "monitor", "--once", "--interval", "5"])
    calls = []
    monkeypatch.setattr(cli, "run_monitor", lambda **kwargs: calls.append(kwargs) or 0)
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == 0
    assert calls == [{"interval": 5, "once": True}]


@pytest.mark.parametrize("interval", ["0", "-1", "3601", "nan"])
def test_monitor_rejects_invalid_intervals(interval):
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["monitor", "--interval", interval])
