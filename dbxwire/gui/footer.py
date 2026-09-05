"""Barra de baixo, no espirito do Postman: atalhos a esquerda, situacao a direita.

Por que nao usar a QStatusBar do Qt. Ela esconde os widgets comuns toda vez que aparece
uma mensagem, entao os botoes da esquerda sumiam a cada frase de status e voltavam
depois. Esta barra e um widget normal: a mensagem tem o lugar dela e ninguem pisca.

Expoe showMessage e addPermanentWidget com os mesmos nomes da QStatusBar pra que o
resto da janela continue chamando do mesmo jeito.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from . import theme

ALTURA = 30


def botao(texto: str, dica: str, acao) -> QToolButton:
    alvo = QToolButton()
    alvo.setText(texto)
    alvo.setToolTip(dica)
    alvo.setAutoRaise(True)
    alvo.setCursor(Qt.CursorShape.PointingHandCursor)
    theme.estilizar(
        alvo,
        lambda: f"QToolButton {{ border: 0; background: transparent; color: {theme.DIM};"
        f" padding: 3px 10px; border-radius: 9px; }}"
        f"QToolButton:hover {{ background: {theme.RAISE}; color: {theme.TEXT}; }}"
        f"QToolButton:checked {{ color: {theme.ACCENT}; }}",
    )
    alvo.clicked.connect(acao)
    return alvo


class Rodape(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(ALTURA + 1)

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        linha = QFrame()
        linha.setFixedHeight(1)
        theme.estilizar(linha, lambda: f"background: {theme.BORDER};")
        raiz.addWidget(linha)

        corpo = QWidget()
        corpo.setObjectName("rodape")
        theme.estilizar(corpo, lambda: f"QWidget#rodape {{ background: {theme.PANEL}; }}")
        raiz.addWidget(corpo)

        self.linha = QHBoxLayout(corpo)
        self.linha.setContentsMargins(6, 0, 10, 0)
        self.linha.setSpacing(2)

        self.mensagem = QLabel("")
        theme.estilizar(self.mensagem, lambda: f"color: {theme.DIM}; padding-left: 10px;")
        self.linha.addWidget(self.mensagem, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.clearMessage)


    def addWidget(self, widget) -> None:  # noqa: N802
        """Entra a esquerda, antes da mensagem, e nao some quando ela aparece."""
        self.linha.insertWidget(self.linha.count() - 1, widget)

    def addPermanentWidget(self, widget) -> None:  # noqa: N802
        self.linha.addWidget(widget)

    def showMessage(self, texto: str, ms: int = 0) -> None:  # noqa: N802
        self.mensagem.setText(texto or "")
        self._timer.stop()
        if ms:
            self._timer.start(ms)

    def clearMessage(self) -> None:  # noqa: N802
        self.mensagem.setText("")

    def currentMessage(self) -> str:  # noqa: N802
        return self.mensagem.text()

    def setSizeGripEnabled(self, _valor: bool) -> None:  # noqa: N802
        pass

    def separador(self) -> None:
        risco = QFrame()
        risco.setFixedWidth(1)
        risco.setFixedHeight(14)
        theme.estilizar(risco, lambda: f"background: {theme.BORDER};")
        self.addWidget(risco)
