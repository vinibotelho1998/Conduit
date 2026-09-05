"""Sobe a aplicacao Qt."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .. import APP_ID, APP_NAME, __version__
from ..core import workspaces as ws
from ..seed import seed
from . import theme
from .icon import build_icon
from .main_window import MainWindow


def app_icon():
    return build_icon()


def _registrar_tombo(tipo, valor, rastro) -> None:
    """O que fazer quando alguma coisa estoura fora de qualquer try.

    Existe por causa de como um app de janela morre no Windows. O executavel e montado
    sem console, entao stderr nao vai pra lugar nenhum: uma excecao dentro de um slot do
    Qt some sem mensagem, e o programa ou fecha do nada ou fica de pe com uma tela que
    parou de responder. Nos dois casos nao sobra nada pra investigar depois.

    Aqui o tombo vira tres coisas: uma linha no arquivo de erros, com data e hora, uma
    caixa dizendo o que foi e onde ficou anotado, e a chance de continuar. Continuar e o
    certo: o erro quase sempre e de uma tela so, e derrubar o app junto faria a pessoa
    perder o rascunho das abas abertas por causa de um botao que falhou.
    """
    if issubclass(tipo, KeyboardInterrupt):
        sys.__excepthook__(tipo, valor, rastro)
        return

    import traceback
    from datetime import datetime

    texto = "".join(traceback.format_exception(tipo, valor, rastro))
    destino = ws.ROOT / "erros.log"
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        with destino.open("a", encoding="utf-8") as arquivo:
            arquivo.write(
                f"\n===== {datetime.now().isoformat(timespec='seconds')}"
                f"  {APP_NAME} {__version__} =====\n{texto}"
            )
    except OSError:
        destino = None

    print(texto, file=sys.stderr)

    from PySide6.QtWidgets import QMessageBox

    if QApplication.instance() is None:
        return
    caixa = QMessageBox()
    caixa.setWindowTitle(APP_NAME)
    caixa.setIcon(QMessageBox.Icon.Warning)
    caixa.setText(f"{tipo.__name__}: {valor}")
    caixa.setInformativeText(
        "O programa continua aberto e o que estava salvo esta a salvo.\n\n"
        + (f"O detalhe completo foi para {destino}." if destino else "")
    )
    caixa.setDetailedText(texto)
    caixa.exec()


def main() -> int:
    if sys.platform == "win32":
        import ctypes

        # sem isso o Windows agrupa a janela pelo executavel do Python, e o icone
        # da barra de tarefas vira o da linguagem em vez do nosso
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)

    sys.excepthook = _registrar_tombo

    ws.ensure_root()
    seed()

    preferencias = ws.read_preferences()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Dbx")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    theme.aplicar(None, preferencias.get("tema"), preferencias.get("densidade"))
    app.setPalette(theme.paleta_qt())
    app.setStyleSheet(theme.folha())
    app.setWindowIcon(app_icon())

    window = MainWindow()
    window.setWindowIcon(app_icon())
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
