"""Lista de servidores SFTP na lateral, no mesmo desenho da lista de ambientes.

A lateral navega, a area principal trabalha: clicar num servidor aqui conecta e abre a
aba do navegador. Quem ja esta conectado aparece com o ponto aceso, entao da pra saber
o que esta de pe sem abrir nada.
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
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core import sftp
from . import theme

PAPEL_ID = Qt.ItemDataRole.UserRole


class SftpPanel(QWidget):
    conectar = Signal(str)
    criar = Signal()
    editar = Signal(str)
    duplicar = Signal(str)
    excluir = Signal(str)
    desconectar = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tree_data: dict = {}
        self.ligados: set[str] = set()

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        cabeca = QWidget()
        cabeca.setFixedHeight(36)
        cl = QHBoxLayout(cabeca)
        cl.setContentsMargins(12, 0, 6, 0)
        titulo = QLabel("SERVIDORES SFTP")
        titulo.setObjectName("sectionTitle")
        cl.addWidget(titulo)
        cl.addStretch(1)

        self.btn_novo = QToolButton()
        self.btn_novo.setText("+")
        self.btn_novo.setToolTip("Cadastrar um servidor")
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
        self.lista.itemDoubleClicked.connect(self._abrir)
        self.lista.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.lista.customContextMenuRequested.connect(self._menu)
        raiz.addWidget(self.lista, 1)

        # Estado vazio com o proprio botao dentro. So o + do cabecalho e um alvo de 20
        # pixels no canto: quem abre a aba pela primeira vez le que nao tem nada e nao
        # tem pra onde ir a partir dali.
        self.vazio = QWidget()
        vl = QVBoxLayout(self.vazio)
        vl.setContentsMargins(18, 24, 18, 24)
        vl.setSpacing(10)
        vl.addStretch(1)

        titulo_vazio = QLabel("Nenhum servidor cadastrado")
        titulo_vazio.setAlignment(Qt.AlignmentFlag.AlignCenter)
        theme.estilizar(
            titulo_vazio, lambda: f"color: {theme.DIM}; font-size: 10pt; font-weight: 600;"
        )
        vl.addWidget(titulo_vazio)

        texto_vazio = QLabel(
            "Host, porta e usuario ficam no workspace. A senha e a frase da chave vao "
            "pro cofre, e nunca pro arquivo que voce versiona."
        )
        texto_vazio.setWordWrap(True)
        texto_vazio.setAlignment(Qt.AlignmentFlag.AlignCenter)
        theme.estilizar(texto_vazio, lambda: f"color: {theme.FAINT}; font-size: 8pt;")
        vl.addWidget(texto_vazio)

        botao_vazio = QPushButton("Cadastrar servidor")
        botao_vazio.setObjectName("primario")
        botao_vazio.setCursor(Qt.CursorShape.PointingHandCursor)
        botao_vazio.clicked.connect(self.criar.emit)
        linha_botao = QHBoxLayout()
        linha_botao.addStretch(1)
        linha_botao.addWidget(botao_vazio)
        linha_botao.addStretch(1)
        vl.addLayout(linha_botao)
        vl.addStretch(2)

        raiz.addWidget(self.vazio, 1)

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

    def marcar_ligado(self, perfil_id: str, ligado: bool) -> None:
        if ligado:
            self.ligados.add(perfil_id)
        else:
            self.ligados.discard(perfil_id)
        self.refresh()

    def refresh(self) -> None:
        self.lista.clear()
        perfis = sftp.listar_perfis(self.tree_data)

        self.vazio.setVisible(not perfis)
        self.lista.setVisible(bool(perfis))

        for perfil in perfis:
            ligado = perfil.id in self.ligados
            marca = "●  " if ligado else "     "
            item = QListWidgetItem(f"{marca}{perfil.nome}")
            item.setData(PAPEL_ID, perfil.id)
            item.setToolTip(
                f"{perfil.rotulo()}\n{sftp.AUTH.get(perfil.auth, perfil.auth)}"
                + ("\nconectado" if ligado else "\nduplo clique conecta")
            )
            if ligado:
                item.setForeground(QColor(theme.OK))
                fonte = item.font()
                fonte.setBold(True)
                item.setFont(fonte)
            self.lista.addItem(item)

        if not perfis:
            self.rodape.setText("")
            return
        abertos = len(self.ligados)
        self.rodape.setText(
            f"{len(perfis)} servidores"
            + (f", {abertos} conectados" if abertos else ". Duplo clique conecta.")
        )

    def _abrir(self, item: QListWidgetItem) -> None:
        alvo = item.data(PAPEL_ID)
        if alvo:
            self.conectar.emit(alvo)

    def _menu(self, pos) -> None:
        item = self.lista.itemAt(pos)
        alvo = item.data(PAPEL_ID) if item else None
        menu = QMenu(self)
        menu.addAction("Cadastrar servidor", self.criar.emit)

        if alvo:
            menu.addSeparator()
            if alvo in self.ligados:
                menu.addAction("Ir para a aba", lambda: self.conectar.emit(alvo))
                menu.addAction("Desconectar", lambda: self.desconectar.emit(alvo))
            else:
                menu.addAction("Conectar", lambda: self.conectar.emit(alvo))
            menu.addAction("Editar", lambda: self.editar.emit(alvo))
            menu.addAction("Duplicar", lambda: self.duplicar.emit(alvo))
            menu.addSeparator()
            menu.addAction("Excluir", lambda: self.excluir.emit(alvo))

        menu.exec(self.lista.viewport().mapToGlobal(pos))
