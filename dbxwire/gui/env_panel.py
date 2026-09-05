"""Lista de ambientes na lateral, no modelo do Postman.

Ambiente e coisa que a pessoa cria, edita e troca o tempo todo. Morava dentro de uma
janela modal, o que obrigava a abrir, mexer e fechar pra cada ajuste. Aqui ele vira
item de lista na lateral e abre um editor na area principal, igual a um request.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import theme

PAPEL_ID = Qt.ItemDataRole.UserRole
GLOBAIS = "__globais__"


class EnvPanel(QWidget):
    abrir = Signal(str)        # id do ambiente, ou GLOBAIS
    criar = Signal()
    ativar = Signal(str)
    renomear = Signal(str)
    duplicar = Signal(str)
    excluir = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tree_data: dict = {}

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        cabeca = QWidget()
        cabeca.setFixedHeight(36)
        cl = QHBoxLayout(cabeca)
        cl.setContentsMargins(12, 0, 6, 0)
        titulo = QLabel("AMBIENTES")
        titulo.setObjectName("sectionTitle")
        cl.addWidget(titulo)
        cl.addStretch(1)

        self.btn_novo = QToolButton()
        self.btn_novo.setText("+")
        self.btn_novo.setToolTip("Novo ambiente, Ctrl+Shift+E")
        theme.estilizar(
            self.btn_novo,
            lambda: f"QToolButton {{ border: 0; background: transparent; color: {theme.DIM};"
            f" padding: 2px 6px; border-radius: 4px; }}"
            f"QToolButton:hover {{ background: {theme.RAISE}; color: {theme.TEXT}; }}",
        )
        self.btn_novo.clicked.connect(self.criar.emit)
        cl.addWidget(self.btn_novo)
        raiz.addWidget(cabeca)

        self.lista = QListWidget()
        self.lista.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        theme.estilizar(
            self.lista,
            lambda: f"QListWidget {{ border: 0; background: {theme.PANEL}; outline: 0; }}"
            f"QListWidget::item {{ padding: 7px 12px; border-radius: 4px; margin: 1px 6px; }}"
            f"QListWidget::item:hover {{ background: {theme.PANEL2}; }}"
            f"QListWidget::item:selected {{ background: {theme.RAISE}; color: {theme.TEXT}; }}",
        )
        self.lista.itemClicked.connect(self._clicou)
        self.lista.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.lista.customContextMenuRequested.connect(self._menu)
        raiz.addWidget(self.lista, 1)

        self.rodape = QLabel("")
        self.rodape.setObjectName("hint")
        self.rodape.setWordWrap(True)
        theme.estilizar(
            self.rodape, lambda: f"color: {theme.FAINT}; padding: 8px 12px; font-size: 8pt;"
        )
        raiz.addWidget(self.rodape)


    def load(self, tree_data: dict) -> None:
        self.tree_data = tree_data
        self.refresh()

    def refresh(self) -> None:
        self.lista.clear()
        ativo = self.tree_data.get("activeEnv")

        for env in self.tree_data.get("environments") or []:
            quantos = len([v for v in env.get("values") or [] if v.get("key")])
            secretas = len([v for v in env.get("values") or [] if v.get("secret")])
            marca = "●  " if env.get("id") == ativo else "     "
            item = QListWidgetItem(f"{marca}{env.get('name') or 'sem nome'}")
            item.setData(PAPEL_ID, env.get("id"))
            detalhe = f"{quantos} variaveis"
            if secretas:
                detalhe += f", {secretas} secretas"
            item.setToolTip(detalhe)
            if env.get("id") == ativo:
                item.setForeground(QColor(theme.ACCENT))
                fonte = item.font()
                fonte.setBold(True)
                item.setFont(fonte)
            self.lista.addItem(item)

        if self.lista.count():
            separador = QListWidgetItem("")
            separador.setFlags(Qt.ItemFlag.NoItemFlags)
            separador.setSizeHint(separador.sizeHint().__class__(0, 8))
            self.lista.addItem(separador)

        globais = QListWidgetItem("     Globais do workspace")
        globais.setData(PAPEL_ID, GLOBAIS)
        globais.setForeground(QColor(theme.DIM))
        globais.setToolTip("Valem para todas as collections deste workspace")
        self.lista.addItem(globais)

        total = len(self.tree_data.get("environments") or [])
        nome = next(
            (e.get("name") for e in self.tree_data.get("environments") or [] if e.get("id") == ativo),
            None,
        )
        self.rodape.setText(
            f"{total} ambientes. Ativo: {nome}" if nome else
            f"{total} ambientes. Nenhum ativo, clique com o direito e escolha Usar este."
        )

    def selecionar(self, env_id: str | None) -> None:
        for indice in range(self.lista.count()):
            if self.lista.item(indice).data(PAPEL_ID) == env_id:
                self.lista.setCurrentRow(indice)
                return


    def _clicou(self, item: QListWidgetItem) -> None:
        alvo = item.data(PAPEL_ID)
        if alvo:
            self.abrir.emit(alvo)

    def _menu(self, pos) -> None:
        item = self.lista.itemAt(pos)
        alvo = item.data(PAPEL_ID) if item else None
        menu = QMenu(self)
        menu.addAction("Novo ambiente", self.criar.emit)

        if alvo and alvo != GLOBAIS:
            menu.addSeparator()
            menu.addAction("Abrir", lambda: self.abrir.emit(alvo))
            menu.addAction("Usar este", lambda: self.ativar.emit(alvo))
            menu.addAction("Renomear", lambda: self.renomear.emit(alvo))
            menu.addAction("Duplicar", lambda: self.duplicar.emit(alvo))
            menu.addSeparator()
            menu.addAction("Excluir", lambda: self.excluir.emit(alvo))
        elif alvo == GLOBAIS:
            menu.addSeparator()
            menu.addAction("Abrir", lambda: self.abrir.emit(alvo))

        menu.exec(self.lista.viewport().mapToGlobal(pos))
