"""Divisor de paineis com alca fina de ver e larga de pegar."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSplitter, QSplitterHandle

from . import theme

PEGA = 7
RISCO = 1.0


class Alca(QSplitterHandle):
    """Sete pixels de area sensivel, um pixel de risco desenhado."""

    def __init__(self, orientacao, pai):
        super().__init__(orientacao, pai)
        self.setCursor(
            Qt.CursorShape.SplitHCursor
            if orientacao == Qt.Orientation.Horizontal
            else Qt.CursorShape.SplitVCursor
        )
        self._sob = False

    def enterEvent(self, evento):  # noqa: N802
        self._sob = True
        self.update()
        super().enterEvent(evento)

    def leaveEvent(self, evento):  # noqa: N802
        self._sob = False
        self.update()
        super().leaveEvent(evento)

    def paintEvent(self, evento):  # noqa: N802
        pintor = QPainter(self)
        pintor.fillRect(self.rect(), QColor(theme.BG))
        cor = QColor(theme.ACCENT if self._sob else theme.BORDER)
        grossura = RISCO * (3.0 if self._sob else 1.0)
        if self.orientation() == Qt.Orientation.Horizontal:
            x = (self.width() - grossura) / 2
            pintor.fillRect(QRectF(x, 0, grossura, self.height()), cor)
        else:
            y = (self.height() - grossura) / 2
            pintor.fillRect(QRectF(0, y, self.width(), grossura), cor)


class Divisor(QSplitter):
    def __init__(self, orientacao, pai=None):
        super().__init__(orientacao, pai)
        self.setHandleWidth(PEGA)
        self.setChildrenCollapsible(False)

    def createHandle(self):  # noqa: N802
        return Alca(self.orientation(), self)
