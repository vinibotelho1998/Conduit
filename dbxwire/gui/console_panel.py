"""Console do app: o que ele fez, em ordem, com hora.

E o equivalente ao console do Postman. A barra de status mostra uma frase por vez e a
frase anterior se perde, entao quando algo da errado no meio de uma sequencia nao sobra
rastro. Aqui sobra: envio, resposta, salvamento, importacao e erro ficam listados.

Nao substitui o historico. O historico guarda a execucao inteira, com corpo e headers,
e fica no disco. O console e a fita do que aconteceu nesta sessao, some ao fechar.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .request_editor import mono

CORES = {
    "info": theme.DIM,
    "envio": theme.ACCENT,
    "ok": theme.OK,
    "aviso": theme.WARN,
    "erro": theme.ERR,
}

LIMITE_LINHAS = 2000


class ConsolePanel(QWidget):
    fechar_pedido = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._linhas: list[tuple[str, str, str]] = []

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        barra = QWidget()
        barra.setFixedHeight(34)
        bl = QHBoxLayout(barra)
        bl.setContentsMargins(12, 0, 8, 0)
        bl.setSpacing(8)

        titulo = QLabel("CONSOLE")
        titulo.setObjectName("sectionTitle")
        bl.addWidget(titulo)

        self.contador = QLabel("")
        self.contador.setObjectName("hint")
        bl.addWidget(self.contador)
        bl.addStretch(1)

        self.filtro = QLineEdit()
        self.filtro.setPlaceholderText("filtrar")
        self.filtro.setFixedWidth(220)
        self.filtro.textChanged.connect(self._redesenhar)
        bl.addWidget(self.filtro)

        self.btn_copiar = QPushButton("copiar")
        self.btn_copiar.clicked.connect(self._copiar)
        self.btn_limpar = QPushButton("limpar")
        self.btn_limpar.clicked.connect(self.limpar)
        self.btn_fechar = QPushButton("fechar")
        self.btn_fechar.clicked.connect(self.fechar_pedido.emit)
        for botao in (self.btn_copiar, self.btn_limpar, self.btn_fechar):
            # setFlat(True) nao muda nada aqui: com folha de estilo global aplicada, o
            # Qt ignora a flag nativa e desenha o botao do jeito que a QSS manda. O
            # objectName flat e a mesma classe visual que o resto do app usa.
            botao.setObjectName("flat")
            bl.addWidget(botao)
        raiz.addWidget(barra)

        self.texto = QPlainTextEdit()
        self.texto.setReadOnly(True)
        self.texto.setFont(mono(9))
        self.texto.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.texto.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.texto.setPlaceholderText("nada aconteceu ainda nesta sessao")
        raiz.addWidget(self.texto, 1)


    def registrar(self, mensagem: str, nivel: str = "info") -> None:
        hora = datetime.now().strftime("%H:%M:%S")
        self._linhas.append((hora, nivel, mensagem))
        if len(self._linhas) > LIMITE_LINHAS:
            del self._linhas[: len(self._linhas) - LIMITE_LINHAS]
        if self._passa(nivel, mensagem):
            self._acrescentar(hora, nivel, mensagem)
        self.contador.setText(f"{len(self._linhas)} linhas")

    def _passa(self, nivel: str, mensagem: str) -> bool:
        alvo = self.filtro.text().strip().lower()
        return not alvo or alvo in mensagem.lower() or alvo in nivel

    def _acrescentar(self, hora: str, nivel: str, mensagem: str) -> None:
        cursor = self.texto.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        formato = cursor.charFormat()

        formato.setForeground(QColor(theme.FAINT))
        cursor.setCharFormat(formato)
        cursor.insertText(f"{hora}  ")

        formato.setForeground(QColor(CORES.get(nivel, theme.DIM)))
        cursor.setCharFormat(formato)
        cursor.insertText(f"{nivel:<6}")

        formato.setForeground(QColor(theme.TEXT))
        cursor.setCharFormat(formato)
        cursor.insertText(f"  {mensagem}\n")

        self.texto.verticalScrollBar().setValue(self.texto.verticalScrollBar().maximum())

    def _redesenhar(self) -> None:
        self.texto.clear()
        for hora, nivel, mensagem in self._linhas:
            if self._passa(nivel, mensagem):
                self._acrescentar(hora, nivel, mensagem)

    def limpar(self) -> None:
        self._linhas.clear()
        self.texto.clear()
        self.contador.setText("")

    def _copiar(self) -> None:
        QGuiApplication.clipboard().setText(
            "\n".join(f"{h}  {n:<6}  {m}" for h, n, m in self._linhas)
        )
