"""Pecas de interface reaproveitadas: aba com marcador e faixa de aviso."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTabBar,
    QTabWidget,
    QWidget,
)

from . import theme


class BadgeTabBar(QTabBar):
    """Aba que desenha um marcador proprio: pilula com numero, ou ponto.

    Escrever o numero dentro do texto da aba, tipo "Headers 3", nao le bem: o olho nao
    separa o rotulo da contagem. Pilula desenhada separa, e o ponto serve pro caso em
    que existe conteudo mas contar nao faz sentido, como corpo e anotacao.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._marcas: dict[int, tuple[str, str, bool]] = {}

    def set_badge(self, indice: int, texto: str = "", cor: str = "", ponto: bool = False) -> None:
        atual = self._marcas.get(indice)
        novo = (texto, cor or theme.DIM, ponto) if (texto or ponto) else None
        if atual == novo:
            return
        if novo is None:
            self._marcas.pop(indice, None)
        else:
            self._marcas[indice] = novo
        # reescrever o texto e o unico gancho publico que faz a barra remedir a aba;
        # so updateGeometry mantem a largura antiga e a pilula cai em cima do rotulo
        if 0 <= indice < self.count():
            self.setTabText(indice, self.tabText(indice))
        self.updateGeometry()
        self.update()

    def tabSizeHint(self, indice: int):  # noqa: N802
        tamanho = super().tabSizeHint(indice)
        marca = self._marcas.get(indice)
        if marca:
            texto, _, ponto = marca
            # a largura extra tem que caber a pilula inteira mais a margem da direita,
            # senao ela desenha por cima do texto da aba
            extra = 14 if ponto else max(16, 9 + 7 * len(texto)) + 12
            tamanho.setWidth(tamanho.width() + extra)
        return tamanho

    def paintEvent(self, evento):  # noqa: N802
        super().paintEvent(evento)
        if not self._marcas:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        fonte = QFont(self.font())
        fonte.setPointSizeF(max(6.5, fonte.pointSizeF() - 1.5))
        fonte.setBold(True)
        painter.setFont(fonte)

        for indice, (texto, cor, ponto) in self._marcas.items():
            if indice >= self.count():
                continue
            caixa = self.tabRect(indice)
            cor_qt = QColor(cor)

            if ponto:
                raio = 3.0
                centro_x = caixa.right() - 12
                centro_y = caixa.center().y()
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(cor_qt)
                painter.drawEllipse(QRectF(centro_x - raio, centro_y - raio, raio * 2, raio * 2))
                continue

            largura = max(16, 9 + 7 * len(texto))
            altura = 14
            pilula = QRectF(
                caixa.right() - largura - 9,
                caixa.center().y() - altura / 2,
                largura,
                altura,
            )
            fundo = QColor(cor_qt)
            fundo.setAlpha(45)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fundo)
            painter.drawRoundedRect(pilula, 8, 8)
            painter.setPen(cor_qt)
            painter.drawText(pilula, Qt.AlignmentFlag.AlignCenter, texto)
        painter.end()


class BadgeTabs(QTabWidget):
    """QTabWidget que ja vem com a barra de marcadores."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._barra = BadgeTabBar(self)
        self.setTabBar(self._barra)
        self.setDocumentMode(True)

    def set_badge(self, indice: int, texto: str = "", cor: str = "", ponto: bool = False) -> None:
        self._barra.set_badge(indice, texto, cor, ponto)


class Faixa(QWidget):
    """Faixa fina de aviso, com bolinha na cor do estado. Some quando nao ha o que dizer.

    O aviso pode vir com um botao de saida. Dizer que falta valor e util, mas mandar a
    pessoa procurar onde arrumar e trabalho a toa, entao o proprio aviso leva ate la.
    """

    acao = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(8)

        self.bolinha = QLabel("●")
        self.bolinha.setFixedWidth(9)
        layout.addWidget(self.bolinha)

        self.texto = QLabel("")
        self.texto.setStyleSheet("font-size: 8pt;")
        layout.addWidget(self.texto, 1)

        self.botao = QPushButton("")
        self.botao.setObjectName("faixaAcao")
        self.botao.setCursor(Qt.CursorShape.PointingHandCursor)
        self.botao.setFlat(True)
        self.botao.clicked.connect(self.acao.emit)
        self.botao.hide()
        layout.addWidget(self.botao)
        self.hide()

    def mostrar(self, mensagem: str, cor: str, acao: str = "") -> None:
        self.texto.setText(mensagem)
        self.botao.setText(acao)
        self.botao.setVisible(bool(acao))
        self.botao.setStyleSheet(
            f"QPushButton#faixaAcao {{ color: {cor}; background: transparent; border: 0;"
            f" font-size: 8pt; font-weight: 600; text-decoration: underline; padding: 0 2px; }}"
        )
        self.texto.setStyleSheet(f"color: {cor}; font-size: 8pt;")
        self.bolinha.setStyleSheet(f"color: {cor}; font-size: 8pt;")
        fundo = QColor(cor)
        # o seletor precisa do objectName, senao os QLabel de dentro herdam a borda e a
        # faixa passa a parecer um campo de texto
        self.setObjectName("faixa")
        self.setStyleSheet(
            f"QWidget#faixa {{ background: rgba({fundo.red()},{fundo.green()},{fundo.blue()},28);"
            f" border-left: 2px solid {cor}; border-radius: 3px; }}"
            f"QWidget#faixa QLabel {{ background: transparent; border: 0; }}"
        )
        self.show()

    def esconder(self) -> None:
        self.hide()


def so_a_pagina_aberta(tabs: QTabWidget) -> None:
    """Faz o conjunto de abas pedir o tamanho da pagina aberta, e nao da maior de todas.

    O QTabWidget de fabrica soma o minimo da MAIOR pagina, mesmo que ela esteja
    escondida. Uma aba com formulario comprido, como Auth, ou com tabela larga, como
    Exemplos, passa a mandar no tamanho do painel inteiro: o divisor entre o request e a
    resposta ja nasce no fim do curso, e o lado direito rouba largura da arvore.

    O jeito de contornar e dizer que a pagina escondida nao tem opiniao sobre tamanho.
    """

    def ajustar(indice: int) -> None:
        for i in range(tabs.count()):
            pagina = tabs.widget(i)
            if pagina is None:
                continue
            politica = (
                QSizePolicy.Policy.Preferred if i == indice else QSizePolicy.Policy.Ignored
            )
            pagina.setSizePolicy(politica, politica)
        atual = tabs.widget(indice)
        if atual is not None:
            atual.updateGeometry()
        tabs.updateGeometry()

    tabs.currentChanged.connect(ajustar)
    ajustar(tabs.currentIndex())
