"""Pecas de interface reaproveitadas: aba com marcador e faixa de aviso."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtGui import Qt as QtTexto
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTabBar,
    QTabWidget,
    QWidget,
)

from . import theme, tokens


def conta(quantos: int, um: str, muitos: str) -> str:
    """Numero com a palavra no singular ou no plural, pra nao sair "1 secretas"."""
    return f"{quantos} {um if quantos == 1 else muitos}"


class Elastico(QLabel):
    """Rotulo que encolhe ate sumir em vez de empurrar o painel.

    Um QLabel comum entrega o texto inteiro como largura minima. Com uma url de cento e
    poucos caracteres, o lado direito da janela passava a exigir quase dois mil pixels, e
    o splitter tirava essa largura da arvore: bastava chegar uma resposta comprida pra
    coluna da esquerda encolher sozinha. O rodape e a faixa de aviso tinham o mesmo
    defeito: enviar pra uma url comprida alargava a janela inteira alem da tela.
    """

    def __init__(self, modo=Qt.TextElideMode.ElideRight, parent=None):
        super().__init__(parent)
        self._modo = modo
        self._cheio = ""
        self.setMinimumWidth(1)
        # o que passa aqui vem do servidor, e texto com cara de tag viraria HTML, ver
        # dica_de_fora
        self.setTextFormat(Qt.TextFormat.PlainText)

    def setText(self, texto: str) -> None:  # noqa: N802
        self._cheio = texto or ""
        self.setToolTip(dica_de_fora(self._cheio))
        self._encaixar()
        self.updateGeometry()

    def texto_cheio(self) -> str:
        return self._cheio

    def sizeHint(self):  # noqa: N802
        """O que ele gostaria de ter e a largura do texto inteiro.

        Sem isso o rotulo pergunta o tamanho do texto ja cortado, que foi cortado no
        tamanho que ele tinha, e a conta se fecha em zero: ele some da barra.
        """
        tamanho = super().sizeHint()
        borda = self.rect().width() - self.contentsRect().width()
        tamanho.setWidth(self.fontMetrics().horizontalAdvance(self._cheio) + 2 + borda)
        return tamanho

    def minimumSizeHint(self):  # noqa: N802
        tamanho = super().minimumSizeHint()
        tamanho.setWidth(1)
        return tamanho

    def resizeEvent(self, evento):  # noqa: N802
        super().resizeEvent(evento)
        self._encaixar()

    def changeEvent(self, evento):  # noqa: N802
        # a folha que troca o tamanho da letra chega depois do setText
        super().changeEvent(evento)
        if evento.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._encaixar()

    def _encaixar(self) -> None:
        # a area de dentro, e nao a largura toda: com margem ou padding, o texto cortado
        # pra largura toda passava da borda e perdia as reticencias
        largura = max(0, self.contentsRect().width() - 2)
        super().setText(self.fontMetrics().elidedText(self._cheio, self._modo, largura))


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

        # Elastico: com cinco variaveis sem dono, o aviso pedia 862 pixels e a janela nao
        # encolhia abaixo de 1087. Texto de fora, como nome de request importado, fica
        # como texto puro, ver dica_de_fora.
        self.texto = Elastico()
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

    def mostrar(self, mensagem: str, papel: str, acao: str = "") -> None:
        """`papel` e o nome do token, tipo "erro" ou "aviso", e nao a cor pronta.

        Cor resolvida vira numero congelado dentro da lambda que repinta, e trocar de
        tema deixaria a faixa na paleta velha. O papel a lambda resolve na hora. De
        quebra o chamador passa a dizer o que a faixa significa em vez de que cor ela e.
        """
        self.texto.setText(mensagem)
        self.botao.setText(acao)
        self.botao.setVisible(bool(acao))
        theme.estilizar(
            self.botao,
            lambda p=papel: f"QPushButton#faixaAcao {{ color: {theme.cor(p)};"
            f" background: transparent; border: 0; font-size: 8pt; font-weight: 600;"
            f" text-decoration: underline; padding: 0 2px; }}",
        )
        theme.estilizar(self.texto, lambda p=papel: f"color: {theme.cor(p)}; font-size: 8pt;")
        theme.estilizar(self.bolinha, lambda p=papel: f"color: {theme.cor(p)}; font-size: 8pt;")
        # o seletor precisa do objectName, senao os QLabel de dentro herdam a borda e a
        # faixa passa a parecer um campo de texto
        self.setObjectName("faixa")
        theme.estilizar(
            self,
            lambda p=papel: f"QWidget#faixa {{"
            f" background: {tokens.alfa(theme.cor(p), 0.11)};"
            f" border-left: 2px solid {theme.cor(p)}; border-radius: 3px; }}"
            f"QWidget#faixa QLabel {{ background: transparent; border: 0; }}",
        )
        self.show()

    def esconder(self) -> None:
        self.hide()


def cabecalho_a_esquerda(tabela) -> None:
    """Poe o nome da coluna em cima da coluna, e nao no meio dela.

    O Qt centraliza o cabecalho de tabela por padrao. Como o conteudo de toda tabela
    daqui e alinhado a esquerda, o rotulo boiava longe da primeira letra do dado e
    deixava de apontar pra coluna que nomeia: com CHAVE em 260 pixels de largura, a
    palavra caia no meio do vazio entre uma coluna e a outra.

    Nao da pra resolver na folha de estilo. `text-align` existe no QSS do Qt pra botao
    e pra barra de progresso, e o cabecalho ignora.
    """
    tabela.horizontalHeader().setDefaultAlignment(
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )


def dica_de_fora(texto: str) -> str:
    """Tooltip pra texto que veio de fora, como header e status mandados pelo servidor.

    O Qt le como HTML todo texto que parece comecar com tag, e um <img> apontando pra
    file://maquina/pasta faz o Windows abrir esse caminho de rede e mandar junto a
    credencial da conta. Convertido aqui, o texto aparece como veio e nada e carregado.
    """
    texto = str(texto or "")
    return QtTexto.convertFromPlainText(texto) if QtTexto.mightBeRichText(texto) else texto


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
