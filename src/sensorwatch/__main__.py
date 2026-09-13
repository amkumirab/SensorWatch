from __future__ import annotations

import argparse

import uvicorn

from sensorwatch.migration import upgrade_database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sensorwatch", description="Run and manage the SensorWatch service."
    )
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser("migrate", help="Upgrade the configured database schema.")

    serve = subcommands.add_parser("serve", help="Start the API and dashboard.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    if arguments.command == "migrate":
        upgrade_database()
        return

    host = arguments.host if arguments.command == "serve" else "127.0.0.1"
    port = arguments.port if arguments.command == "serve" else 8000
    reload = arguments.reload if arguments.command == "serve" else False
    uvicorn.run("sensorwatch.api:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
