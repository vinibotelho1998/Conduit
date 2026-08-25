"""Caixa de marcar e botao de apagar, desenhados por conta propria.

Vestir o controle do sistema com folha de estilo so vai ate certo ponto: o visto tem que
ser uma imagem pronta, presa numa grade de pixel que nao acompanha o tamanho da caixa, e
o x acaba centrado pelo motor de texto e nao pelo desenho. Desenhando, os dois nascem do
mesmo traco do resto do app, ficam centrados no pixel certo e mudam de peso conforme o
estado.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QCheckBox

from . import theme

LADO_CAIXA = 15.0
RAIO_CAIXA = 4.5
CELULA = 24


def _traco(pintor: QPainter, cor: QColor, largura: float) -> None:
    caneta = QPen(cor)
    caneta.setWidthF(largura)
    caneta.setCapStyle(Qt.PenCapStyle.RoundCap)
    caneta.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pintor.setPen(caneta)
    pintor.setBrush(Qt.BrushStyle.NoBrush)


class Marcador(QCheckBox):
    """Caixa de marcar sem texto, do tamanho de uma linha de grade."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(QSize(CELULA, CELULA))
        self.setStyleSheet("background: transparent;")

    def sizeHint(self):  # noqa: N802
        return QSize(CELULA, CELULA)

    def paintEvent(self, evento):  # noqa: N802
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        x = round((self.width() - LADO_CAIXA) / 2)
        y = round((self.height() - LADO_CAIXA) / 2)
        caixa = QRectF(x, y, LADO_CAIXA, LADO_CAIXA)
        sob = self.underMouse()

        if self.isChecked():
            fundo = QColor(theme.ACCENT)
            if not sob:
                fundo.setAlpha(226)
            pintor.setPen(Qt.PenStyle.NoPen)
            pintor.setBrush(fundo)
            pintor.drawRoundedRect(caixa, RAIO_CAIXA, RAIO_CAIXA)

            _traco(pintor, QColor("#0c1420"), 1.9)
            caminho = QPainterPath()
            caminho.moveTo(QPointF(x + 3.7, y + 7.8))
            caminho.lineTo(QPointF(x + 6.2, y + 10.4))
            caminho.lineTo(QPointF(x + 11.3, y + 4.7))
            pintor.drawPath(caminho)
            return

        borda = QPen(QColor(theme.FAINT if sob else theme.BORDER))
        borda.setWidthF(1.3)
        pintor.setPen(borda)
        pintor.setBrush(QColor(theme.PANEL2))
        pintor.drawRoundedRect(caixa.adjusted(0.65, 0.65, -0.65, -0.65), RAIO_CAIXA, RAIO_CAIXA)


class BotaoApagar(QAbstractButton):
    """X de apagar a linha, com alvo redondo que so acende quando o mouse encosta."""

    BRACO = 4.1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(QSize(CELULA, CELULA))
        self.setToolTip("apagar esta linha")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet("background: transparent;")

    def sizeHint(self):  # noqa: N802
        return QSize(CELULA, CELULA)

    def enterEvent(self, evento):  # noqa: N802
        self.update()
        super().enterEvent(evento)

    def leaveEvent(self, evento):  # noqa: N802
        self.update()
        super().leaveEvent(evento)

    def paintEvent(self, evento):  # noqa: N802
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        sob = self.underMouse()

        # o centro sai do proprio widget, entao o x e o circulo dividem o mesmo ponto e
        # nunca aparecem desencontrados
        cx = self.width() / 2.0
        cy = self.height() / 2.0

        if sob:
            fundo = QColor(theme.ERR)
            fundo.setAlpha(46)
            pintor.setPen(Qt.PenStyle.NoPen)
            pintor.setBrush(fundo)
            raio = min(self.width(), self.height()) / 2.0
            pintor.drawEllipse(QRectF(cx - raio, cy - raio, raio * 2, raio * 2))

        _traco(pintor, QColor(theme.ERR if sob else theme.FAINT), 1.7)
        braco = self.BRACO
        pintor.drawLine(QPointF(cx - braco, cy - braco), QPointF(cx + braco, cy + braco))
        pintor.drawLine(QPointF(cx + braco, cy - braco), QPointF(cx - braco, cy + braco))
