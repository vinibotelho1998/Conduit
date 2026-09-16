"""Campo de codigo com a régua de numero de linha na esquerda.

Por que isto existe. Corpo de request e corpo de resposta sao os dois lugares do app em
que se le codigo de verdade, e ate agora eles eram um bloco de texto sem referencia
nenhuma. Quando o servidor responde "erro na linha 42", ou quando alguem pede pra olhar
o comeco do terceiro objeto, contar linha no olho e o trabalho que a maquina devia estar
fazendo. Todo editor faz isso, o Postman inclusive, e o desenho ja e conhecido: faixa
mais funda que o texto, numero alinhado a direita, o da linha do cursor mais claro.

A cor sai de `theme` na hora de pintar e nao no construtor, entao trocar de tema pelo
menu Ver ja repinta certo sem ninguem se registrar em lugar nenhum.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from . import theme

# respiro dos dois lados do numero, e a distancia entre a regua e a primeira letra
FOLGA_ESQUERDA = 10
FOLGA_DIREITA = 10


class Regua(QWidget):
    """A faixa da esquerda. Nao pinta nada sozinha, so devolve o desenho pro editor.

    Ela e filha do editor e nao entra em layout nenhum: quem posiciona e o resizeEvent
    do editor, porque a area util do texto e definida por setViewportMargins e as duas
    contas precisam sair do mesmo numero.
    """

    def __init__(self, editor: "EditorNumerado"):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.editor.largura_regua(), 0)

    def paintEvent(self, evento):  # noqa: N802
        self.editor.pintar_regua(evento)


class EditorNumerado(QPlainTextEdit):
    """QPlainTextEdit com a regua. Serve pro corpo do request e pro da resposta."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.regua = Regua(self)
        self.blockCountChanged.connect(self._ajustar_margem)
        self.updateRequest.connect(self._rolar_regua)
        # o numero da linha do cursor sai mais claro, entao mover o cursor repinta
        self.cursorPositionChanged.connect(self.regua.update)
        self._ajustar_margem()

    def largura_regua(self) -> int:
        """Larga o bastante pro maior numero que o documento vai chegar a mostrar.

        Medido em digito e nao em pixel fixo: com mil linhas a regua cresce sozinha, e
        num corpo de tres linhas ela nao rouba espaco do texto.
        """
        digitos = len(str(max(1, self.blockCount())))
        largura_digito = self.fontMetrics().horizontalAdvance("9")
        return FOLGA_ESQUERDA + largura_digito * digitos + FOLGA_DIREITA

    def _ajustar_margem(self) -> None:
        self.setViewportMargins(self.largura_regua(), 0, 0, 0)

    def _rolar_regua(self, area: QRect, dy: int) -> None:
        if dy:
            self.regua.scroll(0, dy)
        else:
            self.regua.update(0, area.y(), self.regua.width(), area.height())
        if area.contains(self.viewport().rect()):
            self._ajustar_margem()

    def resizeEvent(self, evento):  # noqa: N802
        super().resizeEvent(evento)
        caixa = self.contentsRect()
        self.regua.setGeometry(
            QRect(caixa.left(), caixa.top(), self.largura_regua(), caixa.height())
        )

    def setFont(self, fonte):  # noqa: N802
        """A regua usa a mesma fonte do texto, entao trocar uma remede a outra."""
        super().setFont(fonte)
        # o Qt chama setFont durante o construtor da base, antes da regua existir
        if getattr(self, "regua", None) is None:
            return
        self.regua.setFont(fonte)
        self._ajustar_margem()

    def pintar_regua(self, evento) -> None:
        pintor = QPainter(self.regua)
        # a regua usa a cor de fundo da janela e nao a da superficie de baixo: fundo e
        # o unico tom que fica mais afastado que o campo nos dois temas. Com superficie
        # a regua ficava mais escura que o campo no escuro e mais clara no claro, ou
        # seja, recuava num tema e saltava no outro
        pintor.fillRect(evento.rect(), QColor(theme.BG))
        # um fio na divisa, senao a regua e o texto viram duas manchas de cinza
        # parecidas e o olho nao acha onde uma acaba
        pintor.fillRect(
            QRect(self.regua.width() - 1, evento.rect().top(), 1, evento.rect().height()),
            QColor(theme.BORDER),
        )

        bloco = self.firstVisibleBlock()
        numero = bloco.blockNumber()
        topo = self.blockBoundingGeometry(bloco).translated(self.contentOffset()).top()
        base = topo + self.blockBoundingRect(bloco).height()
        atual = self.textCursor().blockNumber()
        altura = self.fontMetrics().height()
        pintor.setFont(self.font())

        while bloco.isValid() and topo <= evento.rect().bottom():
            if bloco.isVisible() and base >= evento.rect().top():
                aceso = numero == atual and not self.isReadOnly()
                pintor.setPen(QColor(theme.TEXT if aceso else theme.FAINT))
                pintor.drawText(
                    0,
                    int(topo),
                    self.regua.width() - FOLGA_DIREITA,
                    altura,
                    int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                    str(numero + 1),
                )
            bloco = bloco.next()
            topo = base
            base = topo + self.blockBoundingRect(bloco).height()
            numero += 1
        pintor.end()
