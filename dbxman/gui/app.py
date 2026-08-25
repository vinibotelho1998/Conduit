"""Sobe a aplicacao Qt."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .. import APP_ID, APP_NAME
from ..core import workspaces as ws
from ..seed import seed
from . import theme
from .icon import build_icon
from .main_window import MainWindow


def app_icon():
    return build_icon()


def main() -> int:
    if sys.platform == "win32":
        import ctypes

        # sem isso o Windows agrupa a janela pelo executavel do Python, e o icone
        # da barra de tarefas vira o da linguagem em vez do nosso
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)

    ws.ensure_root()
    seed()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Conduit")
    app.setStyle("Fusion")
    app.setStyleSheet(theme.folha())
    app.setWindowIcon(app_icon())

    window = MainWindow()
    window.setWindowIcon(app_icon())
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
