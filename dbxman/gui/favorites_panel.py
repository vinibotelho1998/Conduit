"""Aba de favoritos: os requests que voce marcou, em qualquer collection.

Favorito e marca no proprio request, entao vai junto no arquivo e sobrevive a fechar o
app. A lista mostra o caminho embaixo do nome porque favorito costuma vir de collections
diferentes, e so o nome nao diz de onde saiu.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .icons import ABREVIACAO
from .tree_delegate import pintar_pilula

PAPEL = Qt.ItemDataRole.UserRole
PAPEL_DADOS = Qt.ItemDataRole.UserRole + 1


class LinhaFavorito(QStyledItemDelegate):
    ALTURA = 44

    def paint(self, painter, option, index):
        dados = index.data(PAPEL_DADOS)
        if not dados:
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        area = option.rect

        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(area.adjusted(4, 2, -6, -2), QColor(theme.RAISE))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(area.adjusted(4, 2, -6, -2), QColor(theme.PANEL2))

        metodo = dados["metodo"]
        fim = pintar_pilula(
            painter,
            area.left() + 10,
            area.top() + 15,
            ABREVIACAO.get(metodo, metodo),
            theme.METHOD_COLORS.get(metodo, theme.DIM),
        )

        fonte = QFont(option.font)
        painter.setFont(fonte)
        painter.setPen(QPen(QColor(theme.TEXT)))
        metricas = painter.fontMetrics()
        largura = area.right() - fim - 18
        nome = metricas.elidedText(dados["nome"], Qt.TextElideMode.ElideRight, max(0, int(largura)))
        painter.drawText(
            QRectF(fim + 8, area.top() + 4, largura, 20),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            nome,
        )

        sub = QFont(option.font)
        sub.setPointSizeF(max(7.0, option.font.pointSizeF() - 1.2))
        painter.setFont(sub)
        painter.setPen(QPen(QColor(theme.FAINT)))
        metricas_sub = painter.fontMetrics()
        caminho = metricas_sub.elidedText(
            dados["caminho"], Qt.TextElideMode.ElideLeft, max(0, area.width() - 24)
        )
        painter.drawText(
            QRectF(area.left() + 10, area.top() + 23, area.width() - 24, 18),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            caminho,
        )
        painter.restore()

    def sizeHint(self, option, index):
        tamanho = super().sizeHint(option, index)
        tamanho.setHeight(self.ALTURA)
        return tamanho


class FavoritesPanel(QWidget):
    abrir = Signal(str)         # id do request
    desfavoritar = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tree_data: dict = {}

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        cabeca = QWidget()
        cabeca.setFixedHeight(36)
        cl = QHBoxLayout(cabeca)
        cl.setContentsMargins(12, 0, 10, 0)
        titulo = QLabel("FAVORITOS")
        titulo.setObjectName("sectionTitle")
        cl.addWidget(titulo)
        cl.addStretch(1)
        self.contagem = QLabel("")
        self.contagem.setObjectName("hint")
        cl.addWidget(self.contagem)
        raiz.addWidget(cabeca)

        self.lista = QListWidget()
        self.lista.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.lista.setMouseTracking(True)
        self.lista.setItemDelegate(LinhaFavorito(self.lista))
        self.lista.setStyleSheet(
            f"QListWidget {{ border: 0; background: {theme.PANEL}; outline: 0; }}"
        )
        self.lista.itemClicked.connect(self._clicou)
        self.lista.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.lista.customContextMenuRequested.connect(self._menu)
        raiz.addWidget(self.lista, 1)

        self.vazio = QLabel(
            "Nenhum favorito ainda.\n\n"
            "Botao direito num request na arvore e Favoritar,\n"
            "ou Ctrl+Shift+F com ele aberto."
        )
        self.vazio.setObjectName("hint")
        self.vazio.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.vazio.setWordWrap(True)
        raiz.addWidget(self.vazio, 1)

    # ------------------------------------------------------------------ dados

    def load(self, tree_data: dict) -> None:
        self.tree_data = tree_data
        self.refresh()

    def _favoritos(self) -> list[tuple[dict, str]]:
        achados: list[tuple[dict, str]] = []

        def andar(items, prefixo):
            for node in items or []:
                caminho = prefixo + [node.get("name") or ""]
                if node.get("type") == "request":
                    if node.get("favorite"):
                        achados.append((node, " / ".join(caminho[:-1])))
                else:
                    andar(node.get("items"), caminho)

        andar(self.tree_data.get("collections"), [])
        return achados

    def refresh(self) -> None:
        self.lista.clear()
        favoritos = self._favoritos()

        for node, caminho in favoritos:
            item = QListWidgetItem()
            item.setData(PAPEL, node.get("id"))
            item.setData(
                PAPEL_DADOS,
                {
                    "nome": node.get("name") or "sem nome",
                    "caminho": caminho or "na raiz",
                    "metodo": (node.get("method") or "GET").upper(),
                },
            )
            item.setToolTip(f"{caminho}\n{node.get('url') or ''}")
            self.lista.addItem(item)

        tem = bool(favoritos)
        self.lista.setVisible(tem)
        self.vazio.setVisible(not tem)
        self.contagem.setText(str(len(favoritos)) if tem else "")

    # ---------------------------------------------------------------- eventos

    def _clicou(self, item: QListWidgetItem) -> None:
        alvo = item.data(PAPEL)
        if alvo:
            self.abrir.emit(alvo)

    def _menu(self, pos) -> None:
        item = self.lista.itemAt(pos)
        if not item:
            return
        alvo = item.data(PAPEL)
        menu = QMenu(self)
        menu.addAction("Abrir", lambda: self.abrir.emit(alvo))
        menu.addSeparator()
        menu.addAction("Remover dos favoritos", lambda: self.desfavoritar.emit(alvo))
        menu.exec(self.lista.viewport().mapToGlobal(pos))
