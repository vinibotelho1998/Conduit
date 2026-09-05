"""Cartao que aparece ao passar o mouse numa variavel.

Por que nao usar QToolTip: o balao padrao nasce colado no cursor, entao tapa justamente
o que voce esta apontando, nao aceita canto arredondado nem sombra, e o texto fica sem
respiro. Este cartao ancora embaixo da propria variavel e tem hierarquia visual: nome,
etiqueta do escopo, valor num bloco proprio e as observacoes por ultimo.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ..core.scopes import SCOPE_LABEL
from . import highlight
from . import theme
from .request_editor import mono

LARGURA_MAXIMA = 460


class VarPopup(QFrame):
    _instancia: "VarPopup | None" = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        fora = QVBoxLayout(self)
        fora.setContentsMargins(12, 12, 12, 12)  # espaco pra sombra desenhar

        self.cartao = QFrame()
        self.cartao.setObjectName("varCard")
        sombra = QGraphicsDropShadowEffect(self)
        sombra.setBlurRadius(26)
        sombra.setOffset(0, 6)
        sombra.setColor(QColor(0, 0, 0, 190))
        self.cartao.setGraphicsEffect(sombra)
        fora.addWidget(self.cartao)

        dentro = QVBoxLayout(self.cartao)
        dentro.setContentsMargins(14, 11, 14, 12)
        dentro.setSpacing(8)

        topo = QHBoxLayout()
        topo.setSpacing(8)
        self.nome = QLabel("")
        self.nome.setStyleSheet("font-weight: 700; font-size: 10pt;")
        topo.addWidget(self.nome)

        self.etiqueta = QLabel("")
        self.etiqueta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        topo.addWidget(self.etiqueta)
        topo.addStretch(1)

        # o valor secreto aparece mascarado, e so mostra inteiro se voce pedir. O cartao
        # some depois de uma folga, senao a mao nunca chegaria ate aqui pra clicar.
        self.olho = QPushButton("mostrar")
        self.olho.setObjectName("olho")
        self.olho.setCursor(Qt.CursorShape.PointingHandCursor)
        self.olho.setFlat(True)
        self.olho.clicked.connect(self._alternar_segredo)
        self.olho.hide()
        topo.addWidget(self.olho)
        dentro.addLayout(topo)

        self._info = None
        self._revelado = False
        self._sumir = QTimer(self)
        self._sumir.setSingleShot(True)
        self._sumir.setInterval(320)
        self._sumir.timeout.connect(self.hide)

        self.valor = QLabel("")
        self.valor.setFont(mono(9))
        self.valor.setWordWrap(True)
        self.valor.setObjectName("varValor")
        self.valor.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        dentro.addWidget(self.valor)

        self.nota = QLabel("")
        self.nota.setWordWrap(True)
        self.nota.setStyleSheet(f"color: {theme.FAINT}; font-size: 8pt;")
        dentro.addWidget(self.nota)

        self.setMaximumWidth(LARGURA_MAXIMA + 24)


    def _pintar(self, cor: str) -> None:
        self.cartao.setStyleSheet(
            f"""
            QFrame#varCard {{
                background: {theme.PANEL2};
                border: 1px solid {theme.BORDER};
                border-left: 3px solid {cor};
                border-radius: 9px;
            }}
            QPushButton#olho {{
                background: transparent; border: 0; padding: 0 2px;
                color: {cor}; font-size: 8pt; font-weight: 600; text-decoration: underline;
            }}
            QLabel#varValor {{
                background: {theme.BG};
                border: 1px solid {theme.BORDER};
                border-radius: 6px;
                padding: 7px 9px;
                color: {theme.TEXT};
            }}
            """
        )


    def preencher(self, nome: str, info) -> None:
        if info is None:
            self._info = None
            self.olho.hide()
            self._pintar(theme.ERR)
            self.nome.setText(nome)
            self.nome.setStyleSheet(f"font-weight: 700; font-size: 10pt; color: {theme.ERR};")
            self.etiqueta.setText("nao existe")
            self.etiqueta.setStyleSheet(
                f"color: {theme.ERR}; background: rgba(249,80,107,38); border-radius: 8px;"
                f" padding: 1px 8px; font-size: 8pt; font-weight: 600;"
            )
            self.valor.setText("nenhum escopo define esse nome")
            self.nota.setText("procurei em globais, collection, pasta, ambiente e execucao")
            self.nota.setVisible(True)
            self._ajustar()
            return

        cor = highlight.cor_do_escopo(info.scope)
        self._pintar(cor)
        self._info = info
        self._revelado = False
        self.olho.setVisible(bool(info.secret and info.value))
        self.olho.setText("mostrar")

        self.nome.setText(nome)
        self.nome.setStyleSheet(f"font-weight: 700; font-size: 10pt; color: {cor};")

        rotulo = SCOPE_LABEL.get(info.scope, info.scope)
        if info.origin:
            rotulo = f"{rotulo} · {info.origin}"
        self.etiqueta.setText(rotulo)
        qcor = QColor(cor)
        self.etiqueta.setStyleSheet(
            f"color: {cor};"
            f" background: rgba({qcor.red()},{qcor.green()},{qcor.blue()},38);"
            f" border-radius: 8px; padding: 1px 8px; font-size: 8pt; font-weight: 600;"
        )

        valor = info.masked() if info.secret else info.value
        if valor == "":
            self.valor.setText("definida, mas sem valor")
            self.valor.setStyleSheet("")
        else:
            self.valor.setText(valor if len(valor) <= 400 else valor[:400] + " …")

        notas = []
        if info.secret:
            notas.append("valor secreto, nunca vai pro historico em claro")
        if info.shadowed:
            outros = ", ".join(
                f"{SCOPE_LABEL.get(s.scope, s.scope)} {s.origin}".strip() for s in info.shadowed
            )
            notas.append(f"tambem definida em {outros}, e perdeu por precedencia")
        self.nota.setText("   ·   ".join(notas))
        self.nota.setVisible(bool(notas))
        self._ajustar()

    def _alternar_segredo(self) -> None:
        if self._info is None:
            return
        self._revelado = not self._revelado
        self.olho.setText("esconder" if self._revelado else "mostrar")
        self.valor.setText(self._info.value if self._revelado else self._info.masked())
        self._ajustar()

    def enterEvent(self, evento):  # noqa: N802
        self._sumir.stop()
        super().enterEvent(evento)

    def leaveEvent(self, evento):  # noqa: N802
        self.hide()
        super().leaveEvent(evento)

    def _ajustar(self) -> None:
        self.valor.setMaximumWidth(LARGURA_MAXIMA)
        self.adjustSize()


    def mostrar_em(self, ponto: QPoint) -> None:
        self._sumir.stop()
        self.move(ponto - QPoint(12, 0))  # desconta a margem da sombra
        self.show()
        self.raise_()


    @classmethod
    def instancia(cls) -> "VarPopup":
        if cls._instancia is None:
            cls._instancia = VarPopup()
        return cls._instancia

    @classmethod
    def esconder(cls) -> None:
        """Some com folga, pra dar tempo de levar o mouse ate o cartao e clicar no olho."""
        if cls._instancia is None:
            return
        if cls._instancia.olho.isVisible():
            cls._instancia._sumir.start()
        else:
            cls._instancia.hide()

    @classmethod
    def esconder_agora(cls) -> None:
        if cls._instancia is not None:
            cls._instancia._sumir.stop()
            cls._instancia.hide()
