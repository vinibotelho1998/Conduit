"""Paleta de comandos e busca rapida, no estilo Ctrl+P de editor de codigo."""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
)

from . import icons, theme


@dataclass
class PaletteItem:
    label: str
    sub: str = ""
    badge: str = ""
    badge_color: str = ""
    action: object = None
    hint: str = ""
    payload: object = None
    score: int = field(default=0, compare=False)


def fuzzy(consulta: str, texto: str) -> int | None:
    """Pontuacao simples de subsequencia. Devolve None quando nao casa.

    Casamento no comeco de palavra vale mais, e caracteres seguidos valem mais ainda.
    E o suficiente pra uma lista de algumas centenas de requests e nao precisa de lib.
    """
    if not consulta:
        return 0
    alvo = texto.lower()
    busca = consulta.lower()

    pontos = 0
    posicao = 0
    anterior = -2
    for letra in busca:
        achou = alvo.find(letra, posicao)
        if achou < 0:
            return None
        if achou == anterior + 1:
            pontos += 6
        if achou == 0 or alvo[achou - 1] in " /-_.":
            pontos += 8
        pontos += max(0, 4 - (achou - posicao))
        anterior = achou
        posicao = achou + 1
    pontos += max(0, 20 - len(alvo) // 4)

    # Substring inteira vale muito mais que subsequencia espalhada, senao buscar
    # "banco" traz "Basic auth" quase no mesmo nivel de "Banco por codigo".
    if busca in alvo:
        pontos += 120
        if alvo.startswith(busca):
            pontos += 60
    return pontos


class LinhaPaleta(QStyledItemDelegate):
    """Desenha cada linha da paleta.

    Nome e atalho iam no mesmo texto, separados por quebra de linha, numa linha da
    altura da arvore: o atalho, que era o motivo da segunda linha, nunca aparecia, e o
    nome saia cortado com reticencias. Aqui o comando tem o atalho alinhado a direita, e
    o request tem a pilula do metodo, o nome e, embaixo, o caminho e a url mais apagados.
    """

    def sizeHint(self, option, index):  # noqa: N802
        item = index.data(Qt.ItemDataRole.UserRole)
        altura = 46 if item is not None and item.badge else 34
        return QSize(max(1, option.rect.width()), altura)

    def paint(self, painter, option, index):
        item = index.data(Qt.ItemDataRole.UserRole)
        if item is None:
            super().paint(painter, option, index)
            return

        painter.save()
        fundo = option.rect.adjusted(2, 1, -2, -1)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.RAISE))
            painter.drawRoundedRect(fundo, 6, 6)
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.cor("hover")))
            painter.drawRoundedRect(fundo, 6, 6)

        area = option.rect.adjusted(12, 0, -12, 0)
        fonte = QFont(option.font)
        painter.setFont(fonte)
        metricas = painter.fontMetrics()

        if item.badge:
            pilula = icons.method_icon(item.badge.upper()).pixmap(icons.LARGURA, icons.ALTURA)
            topo = area.top() + 5
            # a pilula do metodo e desenhada encostada a direita da faixa de 52
            painter.drawPixmap(area.left() - 6, topo, pilula)
            x = area.left() + icons.LARGURA + 2
            painter.setPen(QColor(theme.TEXT))
            nome = metricas.elidedText(item.label, Qt.TextElideMode.ElideRight, area.right() - x)
            painter.drawText(QRect(x, topo, area.right() - x, icons.ALTURA),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, nome)
            if item.sub:
                menor = QFont(option.font)
                menor.setPointSizeF(max(7.5, option.font.pointSizeF() - 1.5))
                painter.setFont(menor)
                sub = painter.fontMetrics()
                texto = sub.elidedText(item.sub.strip(), Qt.TextElideMode.ElideMiddle, area.right() - x)
                painter.setPen(QColor(theme.FAINT))
                painter.drawText(QRect(x, topo + icons.ALTURA + 1, area.right() - x, sub.height()),
                                 Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, texto)
        else:
            atalho = item.sub or ""
            largura_atalho = metricas.horizontalAdvance(atalho) + (16 if atalho else 0)
            painter.setPen(QColor(theme.TEXT))
            nome = metricas.elidedText(item.label, Qt.TextElideMode.ElideRight,
                                       max(0, area.width() - largura_atalho))
            painter.drawText(area, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, nome)
            if atalho:
                painter.setPen(QColor(theme.FAINT))
                painter.drawText(area, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, atalho)
        painter.restore()


class Palette(QDialog):
    def __init__(self, itens: list[PaletteItem], titulo: str, parent=None):
        super().__init__(parent)
        self.itens = itens
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        self.resize(720, 460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        theme.estilizar(
            self,
            lambda: f"QDialog {{ background: {theme.PANEL2};"
            f" border: 1px solid {theme.ACCENT}; border-radius: 10px; }}",
        )

        self.busca = QLineEdit()
        self.busca.setPlaceholderText(titulo)
        theme.estilizar(
            self.busca,
            lambda: f"QLineEdit {{ border: 0; border-bottom: 1px solid {theme.BORDER};"
            f" border-radius: 0; padding: 12px 14px; font-size: 11pt;"
            f" background: transparent; }}",
        )
        self.busca.textChanged.connect(self._filtrar)
        self.busca.returnPressed.connect(self._aceitar)
        layout.addWidget(self.busca)

        self.lista = QListWidget()
        theme.estilizar(
            self.lista,
            lambda: f"QListWidget {{ border: 0; background: transparent; padding: 6px; }}"
            f"QListWidget::item {{ padding: 6px 10px; border-radius: 6px; }}"
            f"QListWidget::item:selected {{ background: {theme.RAISE}; }}",
        )
        self.lista.setItemDelegate(LinhaPaleta(self.lista))
        self.lista.setMouseTracking(True)
        self.lista.itemActivated.connect(lambda _: self._aceitar())
        self.lista.itemDoubleClicked.connect(lambda _: self._aceitar())
        layout.addWidget(self.lista, 1)

        self.rodape = QLabel("  Enter abre   ·   Esc fecha   ·   setas navegam")
        self.rodape.setObjectName("hint")
        theme.estilizar(
            self.rodape,
            lambda: f"color: {theme.FAINT}; border-top: 1px solid {theme.BORDER};"
            f" padding: 6px 12px;",
        )
        layout.addWidget(self.rodape)

        self.escolhido: PaletteItem | None = None
        self._filtrar("")


    def _filtrar(self, consulta: str) -> None:
        pontuados = []
        for item in self.itens:
            alvo = f"{item.label} {item.sub} {item.badge}"
            nota = fuzzy(consulta, alvo)
            if nota is not None:
                item.score = nota
                pontuados.append(item)
        pontuados.sort(key=lambda i: -i.score)

        self.lista.clear()
        for item in pontuados[:200]:
            # o texto fica pra leitor de tela e pra quem procura na lista; o desenho e do
            # LinhaPaleta
            linha = QListWidgetItem(" ".join(p for p in (item.badge, item.label, item.sub) if p))
            linha.setData(Qt.ItemDataRole.UserRole, item)
            if item.hint:
                linha.setToolTip(item.hint)
            self.lista.addItem(linha)

        if self.lista.count():
            self.lista.setCurrentRow(0)
        self.rodape.setText(f"  {self.lista.count()} de {len(self.itens)}   ·   Enter abre   ·   Esc fecha")

    def _aceitar(self) -> None:
        atual = self.lista.currentItem()
        if atual is None:
            return
        self.escolhido = atual.data(Qt.ItemDataRole.UserRole)
        self.accept()


    def keyPressEvent(self, event):  # noqa: N802
        tecla = event.key()
        if tecla == Qt.Key.Key_Escape:
            self.reject()
            return
        if tecla in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            linha = self.lista.currentRow()
            total = self.lista.count()
            if total:
                passo = 1 if tecla == Qt.Key.Key_Down else -1
                self.lista.setCurrentRow((linha + passo) % total)
            return
        if tecla in (Qt.Key.Key_PageDown, Qt.Key.Key_PageUp):
            linha = self.lista.currentRow()
            passo = 8 if tecla == Qt.Key.Key_PageDown else -8
            self.lista.setCurrentRow(max(0, min(self.lista.count() - 1, linha + passo)))
            return
        super().keyPressEvent(event)


    @staticmethod
    def escolher(itens: list[PaletteItem], titulo: str, parent=None) -> PaletteItem | None:
        dialogo = Palette(itens, titulo, parent)
        if parent is not None:
            geo = parent.geometry()
            dialogo.move(
                geo.center().x() - dialogo.width() // 2,
                geo.top() + max(60, geo.height() // 8),
            )
        if dialogo.exec() == QDialog.DialogCode.Accepted:
            return dialogo.escolhido
        return None
