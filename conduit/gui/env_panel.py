"""Lista de ambientes na lateral, no modelo do Postman.

Ambiente e coisa que a pessoa cria, edita e troca o tempo todo. Morava dentro de uma
janela modal, o que obrigava a abrir, mexer e fechar pra cada ajuste. Aqui ele vira
item de lista na lateral e abre um editor na area principal, igual a um request.

Por que a lista virou linha desenhada e ganhou barra de acoes. Antes tudo que se fazia
com um ambiente estava no botao direito, e so la: trocar de ativo, renomear, duplicar e
excluir. O sintoma disso e que o rodape precisava ensinar o gesto, com a frase "clique
com o direito e escolha Usar este". Quando a interface precisa explicar como se usa, o
que falta nao e explicacao, e o botao.

O ponto da esquerda tambem virou botao: clicar nele troca o ambiente ativo sem abrir
menu nenhum, que e a acao mais repetida do painel inteiro.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
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

from . import icons, theme

PAPEL_ID = Qt.ItemDataRole.UserRole
GLOBAIS = "__globais__"


class LinhaAmbiente(QWidget):
    """Uma linha da lista: ponto que ativa, nome e a contagem embaixo."""

    ativar_pedido = Signal()

    def __init__(self, nome: str, detalhe: str, ativo: bool, globais: bool = False, parent=None):
        super().__init__(parent)

        linha = QHBoxLayout(self)
        linha.setContentsMargins(10, 5, 10, 5)
        linha.setSpacing(9)

        self.ponto = QToolButton()
        self.ponto.setObjectName("silencioso")
        self.ponto.setIconSize(QSize(15, 15))
        self.ponto.setFixedSize(QSize(26, 26))
        if globais:
            # globais nao se ativa: elas valem sempre, em qualquer ambiente
            self.ponto.setEnabled(False)
            self.ponto.setToolTip("as globais valem sempre, nao precisam ser ativadas")
        else:
            self.ponto.setCursor(Qt.CursorShape.PointingHandCursor)
            self.ponto.setToolTip("este ja e o ativo" if ativo else "usar este ambiente")
            self.ponto.clicked.connect(self.ativar_pedido.emit)

        # a cor sai de theme na hora de desenhar, e nao aqui: guardada agora, ela ficava
        # congelada na paleta de quando a linha nasceu e nao acompanhava a troca de tema
        def pintar(alvo, a=ativo, g=globais):
            # globais fica sem radio nenhum, e nao com um radio apagado: circulo vazio
            # ali sugeria que dava pra escolher ela como ativa, que e o que nao existe.
            # O botao continua ocupando o lugar, entao o nome nao desalinha da lista.
            alvo.setIcon(QIcon() if g else icons.radio(a))

        theme.ao_trocar_widget(self.ponto, pintar)
        linha.addWidget(self.ponto, 0, Qt.AlignmentFlag.AlignVCenter)

        coluna = QVBoxLayout()
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(1)

        self.nome = QLabel(nome)
        theme.estilizar(
            self.nome,
            lambda a=ativo, g=globais: f"color: {theme.DIM if g else theme.TEXT};"
            f" font-weight: {'700' if a else '500'}; font-size: 10pt;",
        )
        coluna.addWidget(self.nome)

        self.detalhe = QLabel(detalhe)
        theme.estilizar(self.detalhe, lambda: f"color: {theme.FAINT}; font-size: 8pt;")
        coluna.addWidget(self.detalhe)
        linha.addLayout(coluna, 1)

        if ativo and not globais:
            marca = QLabel("ativo")
            theme.estilizar(
                marca,
                lambda: f"color: {theme.ACCENT}; font-size: 8pt; font-weight: 600;",
            )
            linha.addWidget(marca, 0, Qt.AlignmentFlag.AlignVCenter)


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
        self.btn_novo.setToolTip("Novo ambiente, Ctrl+Alt+E")
        self.btn_novo.setObjectName("silencioso")
        self.btn_novo.setCursor(Qt.CursorShape.PointingHandCursor)
        # sem foco de teclado: o anel de foco num botao de acao logo que o painel abre
        # sugere que ele e o que voce deve apertar, e ainda deixa um Enter distraido
        # criando ambiente sem querer
        self.btn_novo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_novo.clicked.connect(self.criar.emit)
        cl.addWidget(self.btn_novo)
        raiz.addWidget(cabeca)

        self.lista = QListWidget()
        self.lista.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.lista.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.lista.setUniformItemSizes(False)
        theme.estilizar(
            self.lista,
            lambda: f"QListWidget {{ border: 0; background: {theme.PANEL}; outline: 0; }}"
            f"QListWidget::item {{ border-radius: 7px; margin: 1px 6px; }}"
            f"QListWidget::item:hover {{ background: {theme.PANEL2}; }}"
            f"QListWidget::item:selected {{ background: {theme.SEL}; color: {theme.TEXT}; }}",
        )
        self.lista.itemClicked.connect(self._clicou)
        self.lista.itemSelectionChanged.connect(self._ajustar_botoes)
        self.lista.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.lista.customContextMenuRequested.connect(self._menu)
        raiz.addWidget(self.lista, 1)

        risco = QFrame()
        risco.setObjectName("divisorH")
        raiz.addWidget(risco)

        # Barra de acoes visivel. Cada uma delas existia so no botao direito, entao
        # quem nao descobria o gesto nao tinha como renomear nem excluir um ambiente.
        barra = QWidget()
        bl = QHBoxLayout(barra)
        bl.setContentsMargins(8, 6, 8, 6)
        bl.setSpacing(4)

        self.acoes = {}
        for chave, rotulo, dica in (
            ("usar", "Usar", "torna este o ambiente ativo"),
            ("editar", "Editar", "abre o ambiente numa aba"),
            ("excluir", "Excluir", "apaga este ambiente"),
        ):
            botao = QPushButton(rotulo)
            botao.setCursor(Qt.CursorShape.PointingHandCursor)
            if chave == "excluir":
                botao.setObjectName("perigo")
            botao.setToolTip(dica)
            botao.clicked.connect(lambda _=False, c=chave: self._acao(c))
            bl.addWidget(botao)
            self.acoes[chave] = botao

        # Renomear e duplicar entram aqui, e nao como mais dois botoes: cinco rotulos
        # nao cabem numa lateral de 340 pixels sem virar texto cortado. O importante e
        # que nada dependa mais do botao direito, e por este ponto tambem se chega.
        self.btn_mais = QToolButton()
        self.btn_mais.setText("...")
        self.btn_mais.setObjectName("silencioso")
        self.btn_mais.setToolTip("Renomear e duplicar")
        self.btn_mais.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mais.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_mais.setFixedWidth(34)
        self.menu_mais = QMenu(self)
        self.menu_mais.addAction("Renomear", lambda: self._acao("renomear"))
        self.menu_mais.addAction("Duplicar", lambda: self._acao("duplicar"))
        self.btn_mais.setMenu(self.menu_mais)
        bl.addWidget(self.btn_mais)
        self.acoes["mais"] = self.btn_mais
        raiz.addWidget(barra)

        self.rodape = QLabel("")
        self.rodape.setObjectName("hint")
        self.rodape.setWordWrap(True)
        theme.estilizar(
            self.rodape, lambda: f"color: {theme.FAINT}; padding: 0 12px 8px 12px; font-size: 8pt;"
        )
        raiz.addWidget(self.rodape)


    def load(self, tree_data: dict) -> None:
        self.tree_data = tree_data
        self.refresh()

    def _linha(self, nome: str, detalhe: str, ativo: bool, ident: str, globais: bool = False) -> None:
        widget = LinhaAmbiente(nome, detalhe, ativo, globais)
        if not globais:
            widget.ativar_pedido.connect(lambda i=ident: self.ativar.emit(i))
        item = QListWidgetItem()
        item.setData(PAPEL_ID, ident)
        item.setSizeHint(widget.sizeHint())
        self.lista.addItem(item)
        self.lista.setItemWidget(item, widget)

    @staticmethod
    def _contar(valores) -> str:
        quantos = len([v for v in valores or [] if v.get("key")])
        secretas = len([v for v in valores or [] if v.get("secret")])
        vazias = len([v for v in valores or [] if v.get("key") and not v.get("value")])
        partes = [f"{quantos} variavel" if quantos == 1 else f"{quantos} variaveis"]
        if secretas:
            partes.append(f"{secretas} secretas")
        if vazias:
            partes.append(f"{vazias} sem valor")
        return "  ·  ".join(partes)

    def refresh(self) -> None:
        escolhido = self.selecionado()
        self.lista.clear()
        ativo = self.tree_data.get("activeEnv")

        for env in self.tree_data.get("environments") or []:
            self._linha(
                env.get("name") or "sem nome",
                self._contar(env.get("values")),
                env.get("id") == ativo,
                env.get("id"),
            )

        self._linha(
            "Globais do workspace",
            self._contar(self.tree_data.get("globals")),
            False,
            GLOBAIS,
            globais=True,
        )

        if escolhido:
            self.selecionar(escolhido)

        total = len(self.tree_data.get("environments") or [])
        nome = next(
            (e.get("name") for e in self.tree_data.get("environments") or [] if e.get("id") == ativo),
            None,
        )
        plural = "ambiente" if total == 1 else "ambientes"
        self.rodape.setText(
            f"{total} {plural}, ativo {nome}" if nome
            else f"{total} {plural}, nenhum ativo. Clique no ponto pra escolher."
        )
        self._ajustar_botoes()

    def selecionado(self) -> str | None:
        item = self.lista.currentItem()
        return item.data(PAPEL_ID) if item is not None else None

    def selecionar(self, env_id: str | None) -> None:
        for indice in range(self.lista.count()):
            if self.lista.item(indice).data(PAPEL_ID) == env_id:
                self.lista.setCurrentRow(indice)
                return

    def _ajustar_botoes(self) -> None:
        alvo = self.selecionado()
        # Globais nao se ativa, nao se duplica e nao se exclui: ela e do workspace, e
        # nao um ambiente. Sem isso os botoes ficavam acesos e falhavam no clique.
        comum = bool(alvo) and alvo != GLOBAIS
        ativo = self.tree_data.get("activeEnv")
        self.acoes["usar"].setEnabled(comum and alvo != ativo)
        self.acoes["editar"].setEnabled(bool(alvo))
        self.acoes["excluir"].setEnabled(comum)
        self.acoes["mais"].setEnabled(comum)

    def _acao(self, chave: str) -> None:
        alvo = self.selecionado()
        if not alvo:
            return
        if chave == "editar":
            self.abrir.emit(alvo)
        elif alvo != GLOBAIS:
            {
                "usar": self.ativar,
                "renomear": self.renomear,
                "duplicar": self.duplicar,
                "excluir": self.excluir,
            }[chave].emit(alvo)


    def _clicou(self, item: QListWidgetItem) -> None:
        alvo = item.data(PAPEL_ID)
        if alvo:
            self.abrir.emit(alvo)

    def _menu(self, pos) -> None:
        item = self.lista.itemAt(pos)
        alvo = item.data(PAPEL_ID) if item else None
        if item is not None:
            self.lista.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction("Novo ambiente", self.criar.emit)

        if alvo and alvo != GLOBAIS:
            menu.addSeparator()
            menu.addAction("Abrir", lambda: self.abrir.emit(alvo))
            if alvo != self.tree_data.get("activeEnv"):
                menu.addAction("Usar este", lambda: self.ativar.emit(alvo))
            menu.addAction("Renomear", lambda: self.renomear.emit(alvo))
            menu.addAction("Duplicar", lambda: self.duplicar.emit(alvo))
            menu.addSeparator()
            menu.addAction("Excluir", lambda: self.excluir.emit(alvo))
        elif alvo == GLOBAIS:
            menu.addSeparator()
            menu.addAction("Abrir", lambda: self.abrir.emit(alvo))

        menu.exec(self.lista.viewport().mapToGlobal(pos))
