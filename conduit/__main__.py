"""Ponto de entrada: python -m conduit"""

from __future__ import annotations

import argparse
import sys

from . import APP_NAME, __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="conduit", description=f"{APP_NAME}, cliente de API local"
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("gui", help="abre a janela do aplicativo")
    sub.add_parser("ws", help="lista os workspaces")

    args = parser.parse_args(argv)
    cmd = args.cmd or "gui"

    if cmd == "gui":
        from .gui.app import main as run

        return run()

    if cmd == "ws":
        from .core import workspaces as ws

        reg = ws.list_workspaces()
        if not reg["workspaces"]:
            print("nenhum workspace ainda")
            return 0
        for entry in reg["workspaces"]:
            mark = "*" if entry["id"] == reg.get("active") else " "
            print(f"{mark} {entry['id']:<16} {entry['name']:<20} {entry['path']}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
