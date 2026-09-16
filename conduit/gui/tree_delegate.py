"""Desenho da linha da arvore: guias de nivel, seta, pilula e nome.

Por que desenhar por conta propria em vez de usar icone. O icone do item vive numa
faixa de largura fixa, entao entre a seta e o texto sobra um vao morto que faz o item
parecer solto do proprio pai. Desenhando a linha inteira, a pilula encosta na seta, o
nome vem logo depois, e sobra espaco pra guia vertical que mostra o que esta dentro do
que.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from . import theme

ROLE_PINTURA = Qt.ItemDataRole.UserRole + 5

RECUO = 16
GAP = 7


def altura_linha() -> int:
    """A altura de uma linha da arvore, na densidade em uso.

    Funcao e nao constante: densidade troca em tempo de execucao pelo menu Ver, e a
    arvore precisa perguntar de novo toda vez que o Qt pede o tamanho da linha.
    """
    return theme.medida("linha_arvore")


def _fonte_pilula(painter: QPainter) -> QFont:
    fonte = QFont("Segoe UI")
    fonte.setPointSizeF(8.0)
    fonte.setWeight(QFont.Weight.Bold)
    fonte.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.4)
    fonte.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return fonte


def pintar_pilula(painter: QPainter, x: float, centro_y: float, texto: str, cor: str) -> float:
    """Desenha a pilula comecando em x e devolve onde ela termina."""
    painter.save()
    painter.setFont(_fonte_pilula(painter))
    qcor = QColor(cor)

    largura = painter.fontMetrics().horizontalAdvance(texto) + 12
    altura = 17.0
    caixa = QRectF(x, centro_y - altura / 2, largura, altura)

    fundo = QColor(qcor)
    fundo.setAlpha(40)
    contorno = QColor(qcor)
    contorno.setAlpha(110)

    caneta = QPen(contorno)
    caneta.setWidthF(0.9)
    painter.setPen(caneta)
    painter.setBrush(fundo)
    painter.drawRoundedRect(caixa, 5.5, 5.5)

    painter.setPen(QPen(qcor))
    painter.drawText(caixa, Qt.AlignmentFlag.AlignCenter, texto)
    painter.restore()
    return caixa.right()


def pintar_camadas(painter: QPainter, x: float, centro_y: float, cor: str) -> float:
    """Icone de collection: tres placas empilhadas."""
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    base = QColor(cor)
    centro_x = x + 7.0
    for deslocamento, alpha in ((4.6, 80), (2.3, 135), (0.0, 255)):
        camada = QColor(base)
        camada.setAlpha(alpha)
        painter.setBrush(camada)
        y = centro_y + deslocamento - 2.3
        caminho = QPainterPath()
        caminho.moveTo(QPointF(centro_x, y - 2.9))
        caminho.lineTo(QPointF(centro_x + 6.6, y))
        caminho.lineTo(QPointF(centro_x, y + 2.9))
        caminho.lineTo(QPointF(centro_x - 6.6, y))
        caminho.closeSubpath()
        painter.drawPath(caminho)
    painter.restore()
    return x + 14.0


def pintar_pasta(painter: QPainter, x: float, centro_y: float, aberta: bool) -> float:
    painter.save()
    base = QColor(theme.ACCENT).lighter(108) if aberta else QColor(theme.DIM)
    largura, altura = 13.0, 9.6
    topo = centro_y - altura / 2 + 1.0

    aba = QColor(base)
    aba.setAlpha(140)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(aba)
    painter.drawRoundedRect(QRectF(x, topo - 2.2, largura * 0.46, 3.2), 1.2, 1.2)

    corpo = QColor(base)
    corpo.setAlpha(215)
    contorno = QColor(base)
    contorno.setAlpha(150)
    caneta = QPen(contorno)
    caneta.setWidthF(0.8)

    if not aberta:
        painter.setPen(caneta)
        painter.setBrush(corpo)
        painter.drawRoundedRect(QRectF(x, topo, largura, altura), 2.0, 2.0)
    else:
        fundo = QColor(base)
        fundo.setAlpha(100)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fundo)
        painter.drawRoundedRect(QRectF(x, topo, largura, altura), 2.0, 2.0)
        frente = QPainterPath()
        frente.moveTo(QPointF(x + 2.4, topo + altura))
        frente.lineTo(QPointF(x + largura + 2.2, topo + altura))
        frente.lineTo(QPointF(x + largura - 1.0, topo + 3.4))
        frente.lineTo(QPointF(x - 1.5, topo + 3.4))
        frente.closeSubpath()
        painter.setPen(caneta)
        painter.setBrush(corpo)
        painter.drawPath(frente)

    painter.restore()
    return x + largura + 1.0


def pintar_estrela(painter: QPainter, centro_x: float, centro_y: float, cor: str) -> None:
    """Estrela de cinco pontas, desenhada com caminho pra nao depender de fonte."""
    import math

    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(cor))
    caminho = QPainterPath()
    raio_externo, raio_interno = 5.0, 2.2
    for passo in range(10):
        angulo = math.pi / 2 * -1 + passo * math.pi / 5
        raio = raio_externo if passo % 2 == 0 else raio_interno
        ponto = QPointF(centro_x + raio * math.cos(angulo), centro_y + raio * math.sin(angulo))
        if passo == 0:
            caminho.moveTo(ponto)
        else:
            caminho.lineTo(ponto)
    caminho.closeSubpath()
    painter.drawPath(caminho)
    painter.restore()


def pintar_chevron(painter: QPainter, centro_x: float, centro_y: float, aberto: bool, cor: str) -> None:
    painter.save()
    caneta = QPen(QColor(cor))
    caneta.setWidthF(1.4)
    caneta.setCapStyle(Qt.PenCapStyle.RoundCap)
    caneta.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(caneta)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    caminho = QPainterPath()
    if aberto:
        caminho.moveTo(QPointF(centro_x - 3.0, centro_y - 1.4))
        caminho.lineTo(QPointF(centro_x, centro_y + 1.8))
        caminho.lineTo(QPointF(centro_x + 3.0, centro_y - 1.4))
    else:
        caminho.moveTo(QPointF(centro_x - 1.4, centro_y - 3.0))
        caminho.lineTo(QPointF(centro_x + 1.8, centro_y))
        caminho.lineTo(QPointF(centro_x - 1.4, centro_y + 3.0))
    painter.drawPath(caminho)
    painter.restore()


def cor_do_status(status, ok: bool = True) -> str:
    """A mesma leitura do painel de resposta, vinda do tema."""
    return theme.cor_do_status(status, ok)


def cor_da_linha(selecionado: bool, sob_mouse: bool) -> QColor | None:
    if selecionado:
        return QColor(theme.RAISE)
    if sob_mouse:
        return QColor(theme.PANEL2)
    return None


def pintar_fundo(painter: QPainter, recorte, esquerda: float, direita: float,
                 topo: float, altura: float, cor: QColor) -> None:
    """Pinta a faixa da linha inteira e corta no pedaco que cabe a quem chamou.

    Quem chama e a propria arvore, em drawRow, uma vez por linha. Ja foi desenhada em dois
    pedacos, a coluna do recuo de um lado e o resto do outro, e a borda suavizada de cada
    metade deixava um risco no ponto em que os dois recortes se encostavam.
    """
    painter.save()
    painter.setClipRect(recorte)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(cor)
    painter.drawRoundedRect(QRectF(esquerda, topo, max(0.0, direita - esquerda), altura), 8.0, 8.0)
    painter.restore()


class TreeDelegate(QStyledItemDelegate):
    """Pinta a linha inteira: pilula ou icone colado na seta, nome e contagem."""

    def __init__(self, painel, parent=None):
        super().__init__(parent)
        self.painel = painel

    def sizeHint(self, option, index):
        tamanho = super().sizeHint(option, index)
        tamanho.setHeight(altura_linha())
        return tamanho

    def paint(self, painter, option, index):
        node = self.painel._node_por_indice(index)
        if node is None:
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        area = option.rect
        selecionado = bool(option.state & QStyle.StateFlag.State_Selected)
        sob_mouse = bool(option.state & QStyle.StateFlag.State_MouseOver)

        # o fundo da linha nao e desenhado aqui: quem pinta e a arvore, em drawRow,
        # pra faixa sair de um pincel so e nao ter costura no meio
        _ = (selecionado, sob_mouse)

        centro_y = area.center().y() + 0.5
        x = area.left() + 2.0
        tipo = node.get("type")

        if tipo == "request":
            metodo = (node.get("method") or "GET").upper()
            from .icons import ABREVIACAO

            x = pintar_pilula(
                painter, x, centro_y, ABREVIACAO.get(metodo, metodo),
                theme.METHOD_COLORS.get(metodo, theme.DIM),
            ) + GAP
        elif tipo == "example":
            exemplo = node.get("_exemplo") or {}
            status = exemplo.get("status")
            x = pintar_pilula(
                painter, x, centro_y, str(status or "ex"),
                cor_do_status(status, bool(exemplo.get("ok", True))),
            ) + GAP
        elif tipo == "collection":
            x = pintar_camadas(painter, x, centro_y, theme.ACCENT) + GAP
        else:
            x = pintar_pasta(painter, x, centro_y, bool(node.get("expanded"))) + GAP

        direita = area.right() - 8

        # estrela do favorito, sempre a direita de tudo
        if tipo == "request" and node.get("favorite"):
            pintar_estrela(painter, direita - 5, centro_y, theme.WARN)
            direita -= 16

        # contagem de filhos, encostada na direita
        if tipo not in ("request", "example"):
            quantos = len(node.get("items") or [])
            if quantos:
                fonte = QFont(option.font)
                fonte.setPointSizeF(max(7.0, option.font.pointSizeF() - 1.5))
                painter.setFont(fonte)
                painter.setPen(QPen(QColor(theme.FAINT)))
                texto = str(quantos)
                largura = painter.fontMetrics().horizontalAdvance(texto)
                painter.drawText(
                    QRectF(direita - largura, area.top(), largura, area.height()),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                    texto,
                )
                direita -= largura + 8

        fonte = QFont(option.font)
        if tipo == "collection":
            fonte.setBold(True)
        painter.setFont(fonte)
        painter.setPen(QPen(QColor(theme.DIM if tipo in ("folder", "example") else theme.TEXT)))
        metricas = painter.fontMetrics()
        disponivel = max(0, direita - x)
        nome = metricas.elidedText(node.get("name") or "", Qt.TextElideMode.ElideRight, int(disponivel))
        painter.drawText(
            QRectF(x, area.top(), disponivel, area.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            nome,
        )
        painter.restore()
