"""Lista de exemplos de resposta salvos de um request.

Fica como aba do proprio request, do lado de Params e Headers, porque o exemplo e do
request e nao da execucao. O historico responde "o que eu chamei ontem", o exemplo
responde "como essa API responde", e sao perguntas diferentes.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QMenu,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import examples
from . import theme
from .widgets import cabecalho_a_esquerda


class ExamplesPanel(QWidget):
    abrir = Signal(object)
    renomear = Signal(object)
    excluir = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.exemplos: list = []

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 8, 0, 0)
        raiz.setSpacing(8)

        self.vazio = QLabel(
            "Nenhum exemplo salvo ainda.\n\n"
            "Envie o request e clique no marcador, o ultimo icone a direita na barra da resposta.\n"
            "O exemplo fica dentro do request e vai junto quando a collection for compartilhada."
        )
        self.vazio.setObjectName("hint")
        self.vazio.setAlignment(Qt.AlignmentFlag.AlignCenter)
        raiz.addWidget(self.vazio, 1)

        self.tabela = QTableWidget(0, 4)
        self.tabela.setHorizontalHeaderLabels(["Nome", "Status", "Salvo em", "Tamanho"])
        cabecalho_a_esquerda(self.tabela)
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.setShowGrid(False)
        self.tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabela.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabela.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tabela.setColumnWidth(1, 100)
        self.tabela.setColumnWidth(2, 155)
        self.tabela.setColumnWidth(3, 100)
        self.tabela.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabela.customContextMenuRequested.connect(self._menu)
        self.tabela.itemDoubleClicked.connect(self._abrir_item)
        self.tabela.hide()
        raiz.addWidget(self.tabela, 1)


    def definir(self, exemplos: list | None) -> None:
        # import aqui dentro porque o painel de resposta importa o editor de request, e
        # o editor traz este painel: no topo do arquivo os tres se mordem
        from .response_view import status_tone

        self.exemplos = list(exemplos or [])
        tem = bool(self.exemplos)
        self.tabela.setVisible(tem)
        self.vazio.setVisible(not tem)

        self.tabela.setRowCount(len(self.exemplos))
        for linha, exemplo in enumerate(self.exemplos):
            nome = QTableWidgetItem(exemplo.get("name") or "exemplo")
            self.tabela.setItem(linha, 0, nome)

            status = exemplo.get("status")
            cor, _ = status_tone(status, bool(exemplo.get("ok", True)))
            celula = QTableWidgetItem(str(status or "?"))
            celula.setForeground(QColor(cor))
            self.tabela.setItem(linha, 1, celula)

            quando = QTableWidgetItem((exemplo.get("savedAt") or "")[:16].replace("T", " "))
            quando.setForeground(QColor(theme.FAINT))
            self.tabela.setItem(linha, 2, quando)

            tamanho = exemplo.get("size")
            medida = QTableWidgetItem(f"{tamanho} B" if tamanho else "")
            medida.setForeground(QColor(theme.FAINT))
            self.tabela.setItem(linha, 3, medida)
            self.tabela.setRowHeight(linha, theme.medida("linha_tabela"))

    def _exemplo_da_linha(self, linha: int) -> dict | None:
        if 0 <= linha < len(self.exemplos):
            return self.exemplos[linha]
        return None

    def _abrir_item(self, item) -> None:
        exemplo = self._exemplo_da_linha(item.row())
        if exemplo:
            self.abrir.emit(exemplo)

    def _menu(self, pos: QPoint) -> None:
        item = self.tabela.itemAt(pos)
        if item is None:
            return
        exemplo = self._exemplo_da_linha(item.row())
        if exemplo is None:
            return
        menu = QMenu(self)
        menu.addAction("Abrir", lambda: self.abrir.emit(exemplo))
        menu.addAction("Renomear", lambda: self.renomear.emit(exemplo))
        menu.addSeparator()
        menu.addAction("Excluir", lambda: self.excluir.emit(exemplo))
        menu.exec(self.tabela.viewport().mapToGlobal(pos))

    def resumo(self) -> str:
        if not self.exemplos:
            return ""
        return examples.resumo(self.exemplos[0])
