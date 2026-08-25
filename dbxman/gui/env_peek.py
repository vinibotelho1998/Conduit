"""Espiada rapida nas variaveis do ambiente ativo, sem sair da tela.

Substitui os comandos que moravam dentro do seletor de ambiente. Seletor serve pra
escolher, nao pra guardar acao, e misturar as duas coisas fazia a barra parecer um menu
disfarcado de campo.

Da pra editar o valor aqui mesmo. Quase toda visita a esta lista termina em "faltou
preencher essa", e mandar a pessoa abrir outra tela pra digitar uma linha era o caminho
mais longo pro trabalho mais curto. Cada linha sabe de que escopo veio, entao a edicao
volta pro lugar certo: ambiente, globais, collection ou pasta.

Valor secreto continua mascarado na lista, com um olho por linha pra ver quando quiser.
Ao editar, o campo ja abre com o valor de verdade, senao salvar por cima gravaria a
mascara no lugar do segredo.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
)

from ..core import scopes
from . import theme
from .highlight import COR_VAR_SECRETA
from .request_editor import mono

PAPEL_VALOR = Qt.ItemDataRole.UserRole + 1
PAPEL_SECRETO = Qt.ItemDataRole.UserRole + 2
PAPEL_NOME = Qt.ItemDataRole.UserRole + 3


class ValorDelegate(QStyledItemDelegate):
    """Abre a edicao com o valor de verdade, mesmo quando a celula mostra a mascara."""

    def __init__(self, ao_editar, parent=None):
        super().__init__(parent)
        self.ao_editar = ao_editar

    def createEditor(self, parent, option, index):  # noqa: N802
        editor = QLineEdit(parent)
        editor.setFont(mono(9))
        editor.setFrame(False)
        editor.setStyleSheet(
            f"QLineEdit {{ background: {theme.BG}; border: 1px solid {theme.ACCENT};"
            f" border-radius: 6px; padding: 0 7px; color: {theme.TEXT}; }}"
        )
        return editor

    def setEditorData(self, editor, index):  # noqa: N802
        editor.setText(index.data(PAPEL_VALOR) or "")
        editor.selectAll()

    def setModelData(self, editor, model, index):  # noqa: N802
        self.ao_editar(index.row(), editor.text())


class EnvPeek(QFrame):
    editar_ambiente = Signal()
    abrir_variaveis = Signal()
    valor_alterado = Signal(str, str)   # nome, valor novo
    nova_variavel = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._carregando = False
        self._revelados: set = set()

        fora = QVBoxLayout(self)
        fora.setContentsMargins(12, 12, 12, 12)

        self.cartao = QFrame()
        self.cartao.setObjectName("peekCard")
        self.cartao.setStyleSheet(
            f"QFrame#peekCard {{ background: {theme.PANEL2}; border: 1px solid {theme.BORDER};"
            f" border-radius: 10px; }}"
        )
        sombra = QGraphicsDropShadowEffect(self)
        sombra.setBlurRadius(28)
        sombra.setOffset(0, 8)
        sombra.setColor(QColor(0, 0, 0, 200))
        self.cartao.setGraphicsEffect(sombra)
        fora.addWidget(self.cartao)

        dentro = QVBoxLayout(self.cartao)
        dentro.setContentsMargins(14, 12, 14, 12)
        dentro.setSpacing(8)

        topo = QHBoxLayout()
        self.titulo = QLabel("")
        self.titulo.setStyleSheet("font-weight: 700; font-size: 10pt;")
        topo.addWidget(self.titulo)
        topo.addStretch(1)
        self.resumo = QLabel("")
        self.resumo.setObjectName("hint")
        topo.addWidget(self.resumo)
        dentro.addLayout(topo)

        self.tabela = QTableWidget(0, 4)
        self.tabela.setHorizontalHeaderLabels(["Nome", "Valor", "", "Vem de"])
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.setShowGrid(False)
        self.tabela.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.tabela.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabela.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tabela.setColumnWidth(0, 190)
        self.tabela.setColumnWidth(2, 30)
        self.tabela.setColumnWidth(3, 165)
        self.tabela.setMinimumHeight(220)
        self.tabela.setItemDelegateForColumn(1, ValorDelegate(self._editou, self.tabela))
        dentro.addWidget(self.tabela, 1)

        rodape = QHBoxLayout()
        self.aviso = QLabel("Clique duas vezes no valor pra editar aqui mesmo")
        self.aviso.setObjectName("hint")
        rodape.addWidget(self.aviso, 1)

        self.btn_nova = QPushButton("Nova variavel")
        self.btn_nova.clicked.connect(self._nova)
        self.btn_editar = QPushButton("Editar ambiente")
        self.btn_editar.clicked.connect(self._editar)
        self.btn_todas = QPushButton("Todas as variaveis")
        self.btn_todas.clicked.connect(self._todas)
        for botao in (self.btn_nova, self.btn_editar, self.btn_todas):
            rodape.addWidget(botao)
        dentro.addLayout(rodape)

        self.resize(780, 430)

    # ------------------------------------------------------------------ dados

    def preencher(self, mapa: dict, nome_ambiente: str) -> None:
        self._carregando = True
        self._mapa = mapa
        self.titulo.setText(nome_ambiente or "sem ambiente")

        nomes = sorted(mapa)
        self.tabela.setRowCount(len(nomes))
        secretas = 0
        vazias = 0

        for indice, nome in enumerate(nomes):
            info = mapa[nome]
            item_nome = QTableWidgetItem(nome)
            item_nome.setFont(mono(9))
            item_nome.setForeground(QColor(scopes.SCOPE_COLOR.get(info.scope, theme.TEXT)))
            item_nome.setFlags(item_nome.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.tabela.setItem(indice, 0, item_nome)

            item_valor = QTableWidgetItem("")
            item_valor.setFont(mono(9))
            item_valor.setData(PAPEL_VALOR, info.value)
            item_valor.setData(PAPEL_SECRETO, bool(info.secret))
            item_valor.setData(PAPEL_NOME, nome)
            self.tabela.setItem(indice, 1, item_valor)
            self._pintar_valor(indice)

            if info.secret:
                secretas += 1
                self.tabela.setCellWidget(indice, 2, self._olho(indice, nome))
            else:
                self.tabela.setCellWidget(indice, 2, None)
            if not info.value:
                vazias += 1

            origem = f"{scopes.SCOPE_LABEL.get(info.scope, info.scope)} {info.origin}".strip()
            item_origem = QTableWidgetItem(origem)
            item_origem.setForeground(QColor(theme.FAINT))
            item_origem.setFlags(item_origem.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.tabela.setItem(indice, 3, item_origem)
            self.tabela.setRowHeight(indice, 30)

        partes = [f"{len(nomes)} variaveis"]
        if secretas:
            partes.append(f"{secretas} secretas")
        if vazias:
            partes.append(f"{vazias} sem valor")
        self.resumo.setText("   ·   ".join(partes))
        self.btn_editar.setEnabled(bool(nome_ambiente))
        self._carregando = False

    def _olho(self, linha: int, nome: str) -> QToolButton:
        botao = QToolButton()
        botao.setText("◉" if nome in self._revelados else "◎")
        botao.setToolTip("esconder o valor" if nome in self._revelados else "mostrar o valor")
        botao.setCursor(Qt.CursorShape.PointingHandCursor)
        botao.setStyleSheet(
            f"QToolButton {{ border: 0; background: transparent; color: {theme.FAINT};"
            f" font-size: 11pt; padding: 0; }}"
            f"QToolButton:hover {{ color: {COR_VAR_SECRETA}; }}"
        )
        botao.clicked.connect(lambda _=False, n=nome, l=linha: self._alternar(n, l))
        return botao

    def _alternar(self, nome: str, linha: int) -> None:
        if nome in self._revelados:
            self._revelados.discard(nome)
        else:
            self._revelados.add(nome)
        self._pintar_valor(linha)
        self.tabela.setCellWidget(linha, 2, self._olho(linha, nome))

    def _pintar_valor(self, linha: int) -> None:
        item = self.tabela.item(linha, 1)
        if item is None:
            return
        nome = item.data(PAPEL_NOME) or ""
        valor = item.data(PAPEL_VALOR) or ""
        secreto = bool(item.data(PAPEL_SECRETO))
        info = getattr(self, "_mapa", {}).get(nome)

        if not valor:
            mostrado = "sem valor"
            cor = theme.WARN
        elif secreto and nome not in self._revelados:
            mostrado = info.masked() if info is not None else "***"
            cor = COR_VAR_SECRETA
        else:
            mostrado = valor
            cor = COR_VAR_SECRETA if secreto else theme.TEXT

        anterior = self._carregando
        self._carregando = True
        item.setText(mostrado)
        item.setToolTip(mostrado)
        item.setForeground(QColor(cor))
        self._carregando = anterior

    def _editou(self, linha: int, texto: str) -> None:
        item = self.tabela.item(linha, 1)
        if item is None:
            return
        nome = item.data(PAPEL_NOME) or ""
        if texto == (item.data(PAPEL_VALOR) or ""):
            return
        item.setData(PAPEL_VALOR, texto)
        if bool(item.data(PAPEL_SECRETO)):
            # depois de digitar, mostra o que voce acabou de escrever ate fechar o cartao
            self._revelados.add(nome)
            self.tabela.setCellWidget(linha, 2, self._olho(linha, nome))
        self._pintar_valor(linha)
        self.valor_alterado.emit(nome, texto)

    def focar(self, nome: str) -> bool:
        for linha in range(self.tabela.rowCount()):
            item = self.tabela.item(linha, 0)
            if item is not None and item.text() == nome:
                alvo = self.tabela.item(linha, 1)
                self.tabela.setCurrentCell(linha, 1)
                self.tabela.scrollToItem(alvo)
                self.tabela.editItem(alvo)
                return True
        return False

    def mostrar_em(self, ponto: QPoint) -> None:
        self.move(ponto - QPoint(self.width() - 40, 0))
        self.show()

    def _editar(self) -> None:
        self.hide()
        self.editar_ambiente.emit()

    def _todas(self) -> None:
        self.hide()
        self.abrir_variaveis.emit()

    def _nova(self) -> None:
        self.nova_variavel.emit()
