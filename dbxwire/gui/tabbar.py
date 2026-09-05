"""Barra de abas do editor: pilula do metodo, ponto de nao salvo e X pra fechar.

Por que desenhar a aba inteira em vez de usar a barra pronta do Qt. A barra padrao so
sabe mostrar texto mais um botao de fechar, e nao tem onde encaixar duas coisas que a
aba precisa dizer o tempo todo: qual e o metodo do request e se ele tem alteracao sem
salvar. Desenhando, a pilula fica na frente do nome, e o canto direito alterna entre o
ponto laranja de rascunho e o X, igual editor de codigo: o ponto vira X quando o mouse
entra, entao um so canto serve pras duas coisas e a aba nao fica mais larga por isso.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QMenu, QTabBar, QTabWidget

from . import theme
from .tree_delegate import _fonte_pilula, pintar_pilula

# canto de cima da aba, no mesmo acabamento dos campos e botoes
RAIO = 10.0
MARGEM = 12
GAP = 7
ZONA_X = 17.0
LARGURA_MIN = 146
LARGURA_MAX = 280


def altura() -> int:
    """Altura da aba, na densidade em uso.

    Funcao e nao constante de proposito, pra Densidade trocar pelo menu Ver sem
    precisar reabrir o app: o Qt pergunta de novo toda vez que remede a barra.
    """
    return theme.medida("altura_aba")


def _fonte_nome(negrito: bool = False) -> QFont:
    fonte = QFont("Segoe UI")
    fonte.setPointSizeF(10.0)
    if negrito:
        fonte.setWeight(QFont.Weight.DemiBold)
    return fonte


def marcar(pagina, tipo: str = "request", metodo: str = "", sujo: bool = False) -> None:
    """Guarda na propria pagina o que a aba dela precisa desenhar."""
    pagina.setProperty("aba_tipo", tipo)
    pagina.setProperty("aba_metodo", metodo)
    pagina.setProperty("aba_sujo", sujo)


class AbaBar(QTabBar):
    fechar_pedido = Signal(int)
    salvar_pedido = Signal(int)
    fechar_outras = Signal(int)
    fechar_direita = Signal(int)
    fechar_todas = Signal()
    duplicar_pedido = Signal(int)
    curl_pedido = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setDrawBase(False)
        self.setExpanding(False)
        self.setElideMode(Qt.TextElideMode.ElideNone)
        self._sob = -1
        self._sob_x = False
        self._pressionado = -1


    def _pagina(self, index: int):
        pai = self.parent()
        return pai.widget(index) if isinstance(pai, QTabWidget) else None

    def _info(self, index: int) -> tuple[str, str, bool]:
        pagina = self._pagina(index)
        if pagina is None:
            return "request", "", False
        return (
            pagina.property("aba_tipo") or "request",
            pagina.property("aba_metodo") or "",
            bool(pagina.property("aba_sujo")),
        )

    def tabSizeHint(self, index: int):  # noqa: N802
        _, metodo, _ = self._info(index)
        if metodo:
            largura_marca = QFontMetricsF(_fonte_pilula(None)).horizontalAdvance(metodo) + 12
        else:
            largura_marca = 14.0
        texto = QFontMetricsF(_fonte_nome()).horizontalAdvance(self.tabText(index))
        total = MARGEM + largura_marca + GAP + texto + GAP + ZONA_X + MARGEM
        return QRect(0, 0, int(max(LARGURA_MIN, min(LARGURA_MAX, total))), altura()).size()

    def _caixa_x(self, index: int) -> QRectF:
        r = self.tabRect(index)
        return QRectF(r.right() - MARGEM - ZONA_X, r.center().y() - 8.5, ZONA_X, 17.0)


    def paintEvent(self, evento):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(theme.BG))

        atual = self.currentIndex()
        for index in range(self.count()):
            if index != atual:
                self._pintar_aba(painter, index)
        if atual >= 0:
            self._pintar_aba(painter, atual)

    def _pintar_aba(self, painter: QPainter, index: int) -> None:
        r = QRectF(self.tabRect(index))
        if r.isEmpty():
            return
        selecionada = index == self.currentIndex()
        sob = index == self._sob
        _, metodo, sujo = self._info(index)

        # A aba encosta na resposta por baixo, entao so o topo arredonda: pastilha
        # com quatro cantos redondos flutua solta em cima do conteudo.
        fundo = None
        if selecionada:
            fundo = QColor(theme.PANEL2)
        elif sob:
            fundo = QColor(theme.PANEL)
        if fundo is not None:
            caminho = QPainterPath()
            caminho.addRoundedRect(
                QRectF(r.left(), r.top(), r.width(), r.height() + RAIO), RAIO, RAIO
            )
            painter.save()
            painter.setClipRect(r)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fundo)
            painter.drawPath(caminho)
            painter.restore()

        if not selecionada:
            painter.setPen(QPen(QColor(theme.BORDER), 1))
            painter.drawLine(
                QPointF(r.right(), r.top() + 8), QPointF(r.right(), r.bottom() - 8)
            )

        if selecionada:
            painter.fillRect(QRectF(r.left(), r.bottom() - 2, r.width(), 2), QColor(theme.ACCENT))

        centro = r.center().y()
        x = r.left() + MARGEM
        if metodo:
            x = pintar_pilula(painter, x, centro, metodo, theme.METHOD_COLORS.get(metodo, theme.DIM))
        else:
            x = self._pintar_globo(painter, x, centro)
        x += GAP

        limite = r.right() - MARGEM - ZONA_X - GAP
        painter.setFont(_fonte_nome(selecionada))
        painter.setPen(QPen(QColor(theme.TEXT if selecionada or sob else theme.DIM)))
        texto = painter.fontMetrics().elidedText(
            self.tabText(index), Qt.TextElideMode.ElideRight, int(max(10, limite - x))
        )
        painter.drawText(
            QRectF(x, r.top(), max(10.0, limite - x), r.height()),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            texto,
        )

        caixa = self._caixa_x(index)
        if sob or selecionada:
            self._pintar_x(painter, caixa, aceso=sob and self._sob_x, sujo=sujo)
        elif sujo:
            self._pintar_ponto(painter, caixa)

    @staticmethod
    def _pintar_ponto(painter: QPainter, caixa: QRectF) -> None:
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.WARN))
        painter.drawEllipse(caixa.center(), 4.0, 4.0)
        painter.restore()

    @staticmethod
    def _pintar_x(painter: QPainter, caixa: QRectF, aceso: bool, sujo: bool) -> None:
        painter.save()
        if aceso:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.RAISE))
            painter.drawRoundedRect(caixa, 7, 7)
        if aceso:
            cor = QColor(theme.TEXT)
        elif sujo:
            cor = QColor(theme.WARN)
        else:
            cor = QColor(theme.FAINT)
        caneta = QPen(cor)
        caneta.setWidthF(1.4)
        caneta.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(caneta)
        c = caixa.center()
        d = 3.6
        painter.drawLine(QPointF(c.x() - d, c.y() - d), QPointF(c.x() + d, c.y() + d))
        painter.drawLine(QPointF(c.x() + d, c.y() - d), QPointF(c.x() - d, c.y() + d))
        painter.restore()

    @staticmethod
    def _pintar_globo(painter: QPainter, x: float, centro: float) -> float:
        """Marca da aba de ambiente: um circulo com a linha do equador."""
        painter.save()
        caneta = QPen(QColor(theme.ACCENT))
        caneta.setWidthF(1.2)
        painter.setPen(caneta)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        raio = 6.0
        centro_x = x + raio
        painter.drawEllipse(QPointF(centro_x, centro), raio, raio)
        painter.drawLine(QPointF(centro_x - raio, centro), QPointF(centro_x + raio, centro))
        painter.drawEllipse(QPointF(centro_x, centro), raio / 2.1, raio)
        painter.restore()
        return x + raio * 2


    def _no_x(self, index: int, ponto) -> bool:
        return index >= 0 and self._caixa_x(index).adjusted(-3, -3, 3, 3).contains(ponto)

    def mouseMoveEvent(self, evento):  # noqa: N802
        index = self.tabAt(evento.position().toPoint())
        sobre_x = self._no_x(index, evento.position())
        if (index, sobre_x) != (self._sob, self._sob_x):
            self._sob, self._sob_x = index, sobre_x
            self.update()
        super().mouseMoveEvent(evento)

    def leaveEvent(self, evento):  # noqa: N802
        if self._sob != -1:
            self._sob, self._sob_x = -1, False
            self.update()
        super().leaveEvent(evento)

    def mousePressEvent(self, evento):  # noqa: N802
        index = self.tabAt(evento.position().toPoint())
        botao = evento.button()
        if botao == Qt.MouseButton.MiddleButton and index >= 0:
            self._pressionado = index
            return
        if botao == Qt.MouseButton.LeftButton and self._no_x(index, evento.position()):
            # nao chama o super de proposito: com ele o Qt comecaria a arrastar a aba
            self._pressionado = index
            return
        self._pressionado = -1
        super().mousePressEvent(evento)

    def mouseReleaseEvent(self, evento):  # noqa: N802
        if self._pressionado >= 0:
            index = self.tabAt(evento.position().toPoint())
            pedido, self._pressionado = self._pressionado, -1
            if index == pedido:
                self.fechar_pedido.emit(pedido)
            return
        super().mouseReleaseEvent(evento)

    def mouseDoubleClickEvent(self, evento):  # noqa: N802
        index = self.tabAt(evento.position().toPoint())
        if index >= 0 and self._info(index)[2]:
            self.salvar_pedido.emit(index)
            return
        super().mouseDoubleClickEvent(evento)

    def contextMenuEvent(self, evento):  # noqa: N802
        index = self.tabAt(evento.pos())
        if index < 0:
            return
        menu = QMenu(self)
        if self._info(index)[2]:
            menu.addAction("Salvar", lambda: self.salvar_pedido.emit(index))
            menu.addSeparator()
        if self._info(index)[1]:
            menu.addAction("Duplicar request", lambda: self.duplicar_pedido.emit(index))
            menu.addAction("Copiar como curl", lambda: self.curl_pedido.emit(index))
            menu.addSeparator()
        menu.addAction("Fechar", lambda: self.fechar_pedido.emit(index))
        acao_outras = menu.addAction("Fechar as outras", lambda: self.fechar_outras.emit(index))
        acao_outras.setEnabled(self.count() > 1)
        acao_dir = menu.addAction("Fechar as da direita", lambda: self.fechar_direita.emit(index))
        acao_dir.setEnabled(index < self.count() - 1)
        menu.addAction("Fechar todas", self.fechar_todas.emit)
        menu.exec(evento.globalPos())


class AbaTabs(QTabWidget):
    """QTabWidget que usa a AbaBar e conhece a marcacao de cada pagina."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.barra = AbaBar(self)
        self.setTabBar(self.barra)
        self.setTabsClosable(False)
        self.setMovable(True)
        self.setDocumentMode(True)
        self.setUsesScrollButtons(True)

    def marcar(self, pagina, tipo: str = "request", metodo: str = "", sujo: bool = False) -> None:
        marcar(pagina, tipo, metodo, sujo)
        indice = self.indexOf(pagina)
        if indice >= 0:
            # reescrever o texto e o unico gancho publico que faz a barra remedir a aba,
            # e a largura muda quando a pilula do metodo muda
            self.barra.setTabText(indice, self.barra.tabText(indice))
        self.barra.update()

    def sujo(self, pagina) -> bool:
        return bool(pagina.property("aba_sujo"))
