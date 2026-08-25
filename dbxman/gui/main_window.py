"""Janela principal do DBX Wire."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, VERSION_LABEL, __version__
from ..core import auth, codegen, engine, examples, scopes, workspaces as ws
from ..core.history import History
from . import theme
from .codegen_dialog import CodegenDialog
from .console_panel import ConsolePanel
from .env_editor import EnvEditor
from .env_panel import GLOBAIS, EnvPanel
from .env_peek import EnvPeek
from .favorites_panel import FavoritesPanel
from .footer import Rodape, botao as botao_rodape
from .history_panel import HistoryPanel
from .palette import Palette, PaletteItem
from .request_editor import RequestEditor
from .variables_dialog import VariablesDialog
from .response_view import ResponseView
from .splitter import Divisor
from .tabbar import AbaTabs
from .tree_panel import TreePanel


class SendSignals(QObject):
    done = Signal(dict, object)


class SendTask(QRunnable):
    """Envio fora da thread da interface, pra janela nunca congelar.

    O autoDelete fica desligado de proposito. Com ele ligado o Qt destroi o runnable
    assim que run termina, o objeto de sinal morre junto, e a resposta enfileirada pra
    thread da interface se perde antes de ser entregue. Quem segura a referencia e a
    janela, que a solta no _finish_send.
    """

    def __init__(self, prepared, node):
        super().__init__()
        self.setAutoDelete(False)
        self.prepared = prepared
        self.node = node
        self.signals = SendSignals()

    @Slot()
    def run(self) -> None:
        result = engine.send(self.prepared)
        self.signals.done.emit(result, self.node)


# O que a aba edita e, portanto, o que entra na comparacao de salvo contra alterado.
# Nome, favorito e posicao na arvore nao estao aqui de proposito: quem manda nisso e a
# arvore, e renomear com a aba aberta nao pode virar alteracao pendente do request.
CAMPOS_EDITAVEIS = ("method", "url", "params", "headers", "body", "auth", "docs")


def _foto(no: dict) -> str:
    """Retrato normalizado do request, so com o que a aba edita.

    Normaliza porque a mesma request tem mais de uma escrita valida, e nenhuma delas e
    alteracao de verdade:

    - url com a query dentro e a lista de Params sao duas vistas do mesmo dado, e a aba
      passa tudo pra lista assim que abre
    - auth vazio e auth marcado como herdado significam a mesma coisa
    - o editor cria body vazio em request que nunca teve corpo

    Sem juntar esses casos, todo request antigo abriria com o ponto de nao salvo aceso
    sem ninguem ter tocado em nada, e o ponto perderia o sentido.
    """
    url = no.get("url") or ""
    base, _, query = url.partition("?")

    brutos = list(no.get("params") or [])
    ligados = [
        [p.get("key"), p.get("value") or ""]
        for p in brutos
        if p.get("enabled") is not False and p.get("key")
    ]
    if not ligados and query:
        for pedaco in query.split("&"):
            chave, _, valor = pedaco.partition("=")
            if chave:
                ligados.append([chave, valor])
    desligados = [
        [p.get("key"), p.get("value") or ""] for p in brutos if p.get("enabled") is False
    ]

    autenticacao = dict(no.get("auth") or {})
    if (autenticacao.get("type") or "inherit") == "inherit" and len(autenticacao) <= 1:
        autenticacao = {}

    corpo = no.get("body") or {}
    dados = {
        "method": no.get("method") or "GET",
        "url": base,
        "params": [ligados, desligados],
        "headers": [
            [h.get("key"), h.get("value") or "", h.get("enabled") is not False]
            for h in no.get("headers") or []
        ],
        "body": {"mode": corpo.get("mode") or "none", "raw": corpo.get("raw") or ""},
        "auth": autenticacao,
        "docs": no.get("docs") or "",
    }
    return json.dumps(dados, sort_keys=True, ensure_ascii=False, default=str)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1360, 860)

        self.pool = QThreadPool.globalInstance()
        self.workspace_id: str | None = None
        self.tree_data: dict = {"collections": [], "environments": []}
        self.editors: dict[str, RequestEditor] = {}
        self.env_editors: dict[str, EnvEditor] = {}
        self.pending: set[str] = set()
        self.history: History | None = None
        self._tasks: set = set()
        self._assinatura: dict = {}
        self.jar = None
        self.runtime_vars: dict = {}
        self.rascunhos: dict = {}
        # a ultima resposta de cada request aberto, pra voltar na aba e ela ainda estar la
        self.respostas: dict = {}

        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(500)
        self.save_timer.timeout.connect(self._save_now)

        # o rascunho da aba vai pro disco sozinho, so que sem entrar na arvore
        self.rascunho_timer = QTimer(self)
        self.rascunho_timer.setSingleShot(True)
        self.rascunho_timer.setInterval(700)
        self.rascunho_timer.timeout.connect(self._guardar_rascunhos)

        self._build_toolbar()
        self._build_central()
        self._build_menu()
        self._build_status()

        self._load_registry()

    # ---------------------------------------------------------------- layout

    def _build_toolbar(self) -> None:
        bar = QToolBar()
        bar.setMovable(False)
        bar.setFloatable(False)
        self.addToolBar(bar)

        self.ws_button = QToolButton()
        self.ws_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.ws_menu = QMenu(self)
        self.ws_button.setMenu(self.ws_menu)
        bar.addWidget(self.ws_button)

        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().horizontalPolicy().Expanding, spacer.sizePolicy().verticalPolicy())
        bar.addWidget(spacer)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar request, url ou pasta")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(300)
        self.search.textChanged.connect(lambda text: self.tree_panel.apply_filter(text))
        bar.addWidget(self.search)

        label = QLabel("  Ambiente ")
        label.setObjectName("hint")
        bar.addWidget(label)

        self.env_combo = QComboBox()
        self.env_combo.setFixedWidth(186)
        self.env_combo.setToolTip("Ambiente ativo. Criar e gerenciar ficam na aba Ambientes.")
        self.env_combo.currentIndexChanged.connect(self._on_env_changed)
        bar.addWidget(self.env_combo)

        # Espiada rapida no lugar do antigo botao Variaveis. Seletor serve pra escolher,
        # nao pra guardar comando, entao criar e gerenciar sairam de dentro dele.
        self.btn_peek = QToolButton()
        self.btn_peek.setToolTip("Ver as variaveis que valem agora")
        self.btn_peek.clicked.connect(self._espiar_variaveis)
        bar.addWidget(self.btn_peek)

        self.peek = EnvPeek(self)
        self.peek.editar_ambiente.connect(self._editar_ambiente_ativo)
        self.peek.abrir_variaveis.connect(self.open_variables)
        self.peek.valor_alterado.connect(self._peek_valor)
        self.peek.nova_variavel.connect(self._peek_nova)

    def _build_central(self) -> None:
        self.tree_panel = TreePanel()
        self.tree_panel.request_opened.connect(self.open_request)
        self.tree_panel.tree_changed.connect(self.mark_dirty)
        self.tree_panel.menu_novo.addAction(
            self._action("Nova collection", self.new_collection, "Ctrl+Shift+N")
        )
        self.tree_panel.menu_novo.addAction(
            self._action("Nova pasta", self.new_folder, "Ctrl+Alt+N")
        )
        self.tree_panel.menu_novo.addAction(
            self._action("Novo request", self.new_request, "Ctrl+N")
        )
        self.tree_panel.favorito_mudou.connect(lambda: self.fav_panel.refresh())
        self.tree_panel.ordem_aplicada.connect(self._aplicar_ordem)
        self.tree_panel.auth_pedida.connect(self.editar_auth_do_grupo)
        self.tree_panel.exemplo_aberto.connect(self._exemplo_da_arvore)
        self.tree_panel.curl_pedido.connect(self.copiar_curl)
        self.tree_panel.codigo_pedido.connect(self._codigo_do_no)

        self.history_panel = HistoryPanel()
        self.history_panel.replay_requested.connect(self.replay_entry)
        self.history_panel.open_request_requested.connect(self.reveal_request)
        self.history_panel.load_response_requested.connect(self.show_history_response)

        self.env_panel = EnvPanel()
        self.env_panel.abrir.connect(self.open_environment)
        self.env_panel.criar.connect(self.new_environment)
        self.env_panel.ativar.connect(self._usar_ambiente)
        self.env_panel.renomear.connect(self.rename_environment)
        self.env_panel.duplicar.connect(self.duplicate_environment)
        self.env_panel.excluir.connect(self.delete_environment)

        self.fav_panel = FavoritesPanel()
        self.fav_panel.abrir.connect(self.reveal_request)
        self.fav_panel.desfavoritar.connect(self._desfavoritar)

        self.side = QTabWidget()
        self.side.setObjectName("sideTabs")
        self.side.setDocumentMode(True)
        self.side.addTab(self.tree_panel, "Collections")
        self.side.addTab(self.fav_panel, "Favoritos")
        self.side.addTab(self.env_panel, "Ambientes")
        self.side.addTab(self.history_panel, "Historico")

        self.tabs = AbaTabs()
        self.tabs.barra.fechar_pedido.connect(self.pedir_fechar)
        self.tabs.barra.salvar_pedido.connect(self.salvar_aba)
        self.tabs.barra.fechar_outras.connect(self._fechar_outras)
        self.tabs.barra.fechar_direita.connect(self._fechar_direita)
        self.tabs.barra.fechar_todas.connect(lambda: self._fechar_muitas(range(self.tabs.count())))
        self.tabs.barra.duplicar_pedido.connect(self._duplicar_aba)
        self.tabs.barra.curl_pedido.connect(self._curl_da_aba)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self.empty = QLabel("Nenhum request aberto\n\nEscolha um item na arvore ou crie um novo")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setObjectName("hint")

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.addWidget(self.empty)
        center_layout.addWidget(self.tabs)
        self.tabs.hide()
        self.center_layout = center_layout

        self.response = ResponseView()
        self.response.salvar_exemplo.connect(self.salvar_exemplo)

        self.console = ConsolePanel()
        self.console.fechar_pedido.connect(lambda: self.alternar_console(False))
        self.console.hide()

        right = Divisor(Qt.Orientation.Vertical)
        right.addWidget(center)
        right.addWidget(self.response)
        right.addWidget(self.console)
        right.setSizes([520, 320, 0])
        right.setChildrenCollapsible(False)
        self.splitter_direita = right

        # A coluna da esquerda tem tamanho proprio: sem fator de esticar, o Qt
        # reparte qualquer sobra entre os dois lados e a arvore anda sozinha toda vez
        # que a janela muda de tamanho.
        self.side.setMinimumWidth(190)
        self.side.setMaximumWidth(640)
        main = Divisor(Qt.Orientation.Horizontal)
        main.addWidget(self.side)
        main.addWidget(right)
        main.setSizes([340, 1020])
        main.setChildrenCollapsible(False)
        main.setStretchFactor(0, 0)
        main.setStretchFactor(1, 1)
        main.splitterMoved.connect(lambda *_: self._guardar_janela())
        self.splitter_principal = main

        # a barra de baixo e um widget comum, e nao a QStatusBar do Qt: a de fabrica
        # esconde os botoes toda vez que aparece uma mensagem
        self.rodape = Rodape()
        raiz = QWidget()
        pilha = QVBoxLayout(raiz)
        pilha.setContentsMargins(0, 0, 0, 0)
        pilha.setSpacing(0)
        pilha.addWidget(main, 1)
        pilha.addWidget(self.rodape)
        self.setCentralWidget(raiz)

    def _build_menu(self) -> None:
        menu = self.menuBar()

        arquivo = menu.addMenu("&Arquivo")
        arquivo.addAction(self._action("Novo workspace", self.new_workspace))
        arquivo.addAction(self._action("Gerenciar workspaces", self.manage_workspaces))
        arquivo.addAction(self._action("Nova collection", self.new_collection, "Ctrl+Shift+N"))
        arquivo.addSeparator()
        arquivo.addSeparator()
        arquivo.addAction(self._action("Importar", self.importar_arquivo, "Ctrl+I"))
        arquivo.addAction(self._action("Importar de curl", self.importar_curl, "Ctrl+Shift+V"))
        arquivo.addAction(self._action("Exportar", self.exportar_arquivo, "Ctrl+Shift+E"))
        arquivo.addSeparator()
        arquivo.addAction(
            self._action("Salvar o request", lambda: self.salvar_aba(), QKeySequence.StandardKey.Save)
        )
        arquivo.addAction(self._action("Salvar todos", self.salvar_todas, "Ctrl+Shift+S"))
        arquivo.addAction(self._action("Reverter o request", self.reverter_aba))
        arquivo.addAction(self._action("Abrir pasta do workspace", self.open_workspace_folder))
        arquivo.addSeparator()
        arquivo.addAction(self._action("Sair", self.close, "Ctrl+Q"))

        editar = menu.addMenu("&Editar")
        editar.addAction(self._action("Desfazer na arvore", self.undo_tree, "Ctrl+Z"))
        editar.addSeparator()
        editar.addAction(self._action("Novo request na selecao", self.new_request, "Ctrl+N"))
        editar.addAction(self._action("Nova pasta na selecao", self.new_folder, "Ctrl+Alt+N"))
        editar.addAction(self._action("Renomear", self.rename_selected, "F2"))
        editar.addAction(self._action("Duplicar", self.duplicate_selected, "Ctrl+D"))
        editar.addAction(self._action("Excluir", self.delete_selected, "Del"))
        editar.addSeparator()
        editar.addAction(self._action("Favoritar ou desfavoritar", self.toggle_favorite, "Ctrl+Shift+F"))
        editar.addSeparator()
        editar.addAction(self._action("Buscar", lambda: self.search.setFocus(), QKeySequence.StandardKey.Find))
        editar.addSeparator()
        editar.addAction(self._action("Variaveis", self.open_variables, "Ctrl+E"))

        ambientes = editar.addMenu("Ambientes")
        ambientes.addAction(self._action("Novo ambiente", self.new_environment, "Ctrl+Shift+E"))
        ambientes.addAction(
            self._action("Gerenciar ambientes", lambda: self.open_variables("Ambientes"))
        )
        ambientes.aboutToShow.connect(lambda: self._montar_menu_ambientes(ambientes))

        executar = menu.addMenu("E&xecutar")
        executar.addAction(self._action("Enviar", self.send_current, "Ctrl+Return"))
        executar.addAction(self._action("Focar na URL", self.focus_url, "Ctrl+L"))
        executar.addSeparator()
        executar.addAction(self._action("Gerar codigo", self.open_codegen, "Ctrl+G"))
        executar.addAction(
            self._action("Importar de curl", self.importar_curl, "Ctrl+Shift+V")
        )
        executar.addSeparator()
        executar.addAction(self._action("Certificados cliente", self.open_certs))
        executar.addAction(self._action("Cookies guardados", self.open_cookies))
        executar.addAction(self._action("Esquecer tokens do OAuth2", self.limpar_tokens))

        ir = menu.addMenu("&Ir")
        ir.addAction(self._action("Ir para request", self.goto_request, "Ctrl+P"))
        ir.addAction(self._action("Paleta de comandos", self.command_palette, "Ctrl+K"))
        ir.addSeparator()
        ir.addAction(self._action("Proxima aba", lambda: self._passo_aba(1), "Ctrl+Tab"))
        ir.addAction(self._action("Aba anterior", lambda: self._passo_aba(-1), "Ctrl+Shift+Tab"))
        ir.addAction(self._action("Fechar aba", self.fechar_aba_atual, "Ctrl+W"))
        ir.addSeparator()
        ir.addAction(self._action("Copiar como curl", lambda: self.copiar_curl(), "Ctrl+Shift+C"))
        ir.addAction(self._action("Console", lambda: self.alternar_console(), "Ctrl+`"))
        ir.addAction(self._action("Salvar resposta como exemplo", self.salvar_exemplo))
        ir.addSeparator()
        ir.addAction(self._action("Mostrar ou esconder a lateral", self._alternar_lateral, "Ctrl+B"))

        historico = menu.addMenu("&Historico")
        historico.addAction(self._action("Ver historico", lambda: self.side.setCurrentIndex(3), "Ctrl+H"))
        historico.addAction(self._action("Reenviar a execucao selecionada", self.history_panel._replay))
        historico.addSeparator()
        historico.addAction(self._action("Reconstruir indice", self.rebuild_history_index))
        historico.addAction(self._action("Expurgar antigos", self.purge_history))
        historico.addAction(self._action("Limpar tudo", self.clear_history))

        ajuda = menu.addMenu("A&juda")
        ajuda.addAction(self._action("Atalhos de teclado", self.show_shortcuts, "F1"))
        ajuda.addAction(self._action("Novidades desta versao", self.show_changelog))
        ajuda.addAction(self._action(f"Sobre o {APP_NAME}", self.show_about))

        for numero in range(1, 10):
            atalho = QAction(self)
            atalho.setShortcut(f"Ctrl+{numero}")
            atalho.triggered.connect(lambda _=False, n=numero: self._ir_para_aba(n - 1))
            self.addAction(atalho)

    def _action(self, text: str, slot, shortcut=None) -> QAction:
        action = QAction(text, self)
        action.triggered.connect(slot)
        if shortcut:
            action.setShortcut(shortcut)
        return action

    def statusBar(self):  # noqa: N802
        """A janela inteira ja fala com a barra de baixo por este nome."""
        return self.rodape

    def _rodape_botao(self, texto: str, dica: str, acao):
        return botao_rodape(texto, dica, acao)

    def _build_status(self) -> None:
        """O rodape, no espirito do Postman: atalhos a esquerda, situacao a direita."""
        barra = self.statusBar()
        barra.setSizeGripEnabled(False)

        self.btn_lateral = self._rodape_botao(
            "▐▌", "mostrar ou esconder a lateral,  Ctrl+B", self._alternar_lateral
        )
        barra.addWidget(self.btn_lateral)

        self.btn_console = self._rodape_botao(
            "Console", "o que o app fez nesta sessao,  Ctrl+`", lambda: self.alternar_console()
        )
        self.btn_console.setCheckable(True)
        barra.addWidget(self.btn_console)

        self.btn_historico_rodape = self._rodape_botao(
            "Historico", "execucoes gravadas,  Ctrl+H", lambda: self.side.setCurrentIndex(3)
        )
        barra.addWidget(self.btn_historico_rodape)

        self.btn_pasta_rodape = self._rodape_botao(
            "Pasta do workspace", "abrir a pasta no explorador", self.open_workspace_folder
        )
        barra.addWidget(self.btn_pasta_rodape)
        barra.separador()

        self.status_right = QLabel("")
        self.status_right.setObjectName("hint")
        self.statusBar().addPermanentWidget(self.status_right)

        versao = QLabel(f"  v{__version__}")
        versao.setObjectName("hint")
        versao.setToolTip(f"{APP_NAME} {VERSION_LABEL}. Ajuda, Novidades mostra o que mudou.")
        self.statusBar().addPermanentWidget(versao)

        self.statusBar().showMessage("pronto")

    # -------------------------------------------------------------- console

    def alternar_console(self, mostrar: bool | None = None) -> None:
        if mostrar is None:
            mostrar = not self.console.isVisible()
        self.console.setVisible(mostrar)
        self.btn_console.setChecked(mostrar)
        if mostrar:
            alturas = self.splitter_direita.sizes()
            total = sum(alturas) or 800
            self.splitter_direita.setSizes(
                [int(total * 0.45), int(total * 0.33), int(total * 0.22)]
            )

    def registrar(self, mensagem: str, nivel: str = "info", segundos: int = 5) -> None:
        """Uma linha no console e, de quebra, a mesma frase na barra de baixo."""
        self.console.registrar(mensagem, nivel)
        if segundos:
            self.statusBar().showMessage(mensagem, segundos * 1000)

    # ------------------------------------------------------------ workspaces

    def _load_registry(self) -> None:
        registry = ws.list_workspaces()
        self.registry = registry
        self.ws_menu.clear()

        for entry in registry["workspaces"]:
            action = QAction(entry["name"], self)
            action.setCheckable(True)
            action.setChecked(entry["id"] == registry.get("active"))
            action.setToolTip(entry["path"])
            action.triggered.connect(lambda _=False, wid=entry["id"]: self.load_workspace(wid))
            self.ws_menu.addAction(action)

        self.ws_menu.addSeparator()
        self.ws_menu.addAction(self._action("Novo workspace", self.new_workspace))
        self.ws_menu.addAction(self._action("Gerenciar workspaces", self.manage_workspaces))

        target = registry.get("active") or (registry["workspaces"][0]["id"] if registry["workspaces"] else None)
        if target:
            self.load_workspace(target)

    def load_workspace(self, wid: str) -> None:
        if self.workspace_id and self.save_timer.isActive():
            self._save_now()

        entry = ws.get_workspace(wid)
        self.workspace_id = wid
        self.tree_data = ws.read_tree(wid)
        self._assinatura = ws.assinatura(wid)
        ws.set_active(wid)

        self.ws_button.setText(f"  {entry['name']}  ▾")
        self.ws_button.setStyleSheet(
            f"QToolButton {{ color: {theme.TEXT}; font-weight: 600;"
            f" border-left: 3px solid {entry['color']}; }}"
        )

        self.tabs.clear()
        self.editors.clear()
        self.env_editors.clear()
        self.rascunhos = self._ler_rascunhos()
        self.respostas.clear()
        self._sync_tabs_visibility()
        self.response.clear()
        self.tree_panel.load(self.tree_data)
        self.tree_panel.definir_ordenacao(self.tree_data.get("sortMode") or "manual")
        self.fav_panel.load(self.tree_data)
        self.env_panel.load(self.tree_data)
        self._reload_envs()

        if self.history:
            self.history.close()
        from ..core.cookies import CookieJar

        self.jar = CookieJar(entry["path"])
        self.history = History(entry["path"])
        self.history.purge()
        self.history_panel.set_history(self.history)
        self.tree_panel.uso = self.history.uso_por_request()
        self.statusBar().showMessage(f"workspace {entry['name']}", 3000)
        self._reabrir_rascunhos()
        self._ler_janela()

    def _reabrir_rascunhos(self) -> None:
        """Abre de volta as abas que ficaram com alteracao sem salvar."""
        if not self.rascunhos:
            return
        pendentes = set(self.rascunhos)
        abertas = 0
        for node in self.tree_panel._iter_nodes():
            if node.get("id") in pendentes and node.get("type") == "request":
                self.open_request(node)
                abertas += 1
        if abertas:
            self.statusBar().showMessage(
                f"{abertas} request com alteracao sem salvar da sessao anterior", 9000
            )

    def new_workspace(self) -> None:
        name, ok = QInputDialog.getText(self, "Novo workspace", "Nome do workspace")
        if not ok or not name.strip():
            return
        try:
            entry = ws.create_workspace(name.strip())
        except ValueError as exc:
            QMessageBox.warning(self, "DBX Wire", str(exc))
            return
        self._load_registry()
        self.load_workspace(entry["id"])

    def manage_workspaces(self) -> None:
        """Renomear, trocar cor, duplicar, abrir a pasta e excluir."""
        from .workspaces_dialog import WorkspacesDialog

        dialog = WorkspacesDialog(self)
        dialog.exec()
        self._load_registry()
        if self.workspace_id and self.workspace_id not in {
            e["id"] for e in self.registry["workspaces"]
        }:
            # o workspace aberto foi excluido, entao abre o primeiro que sobrou
            if self.registry["workspaces"]:
                self.load_workspace(self.registry["workspaces"][0]["id"])
        elif self.workspace_id:
            entrada = ws.get_workspace(self.workspace_id)
            self.ws_button.setText(f"  {entrada['name']}  \u25be")
            self.ws_button.setStyleSheet(
                f"QToolButton {{ color: {theme.TEXT}; font-weight: 600;"
                f" border-left: 3px solid {entrada['color']}; }}"
            )

    def open_workspace_folder(self) -> None:
        import os

        if self.workspace_id:
            os.startfile(ws.get_workspace(self.workspace_id)["path"])  # noqa: S606

    # ------------------------------------------------------------- ambientes

    def _reload_envs(self) -> None:
        self.env_combo.blockSignals(True)
        self.env_combo.clear()
        self.env_combo.addItem("sem ambiente", None)
        for env in self.tree_data.get("environments") or []:
            self.env_combo.addItem(env.get("name") or "sem nome", env.get("id"))

        active = self.tree_data.get("activeEnv")
        index = self.env_combo.findData(active)
        self.env_combo.setCurrentIndex(index if index >= 0 else 0)
        self.env_combo.blockSignals(False)
        self._refresh_var_hints()

    def _espiar_variaveis(self) -> None:
        node = self.current_node()
        mapa = self.variables_for(node)
        self.peek.preencher(mapa, self.env_combo.currentText() if self.env_combo.currentData() else "")
        canto = self.btn_peek.mapToGlobal(self.btn_peek.rect().bottomRight())
        self.peek.mostrar_em(canto)

    def _lista_do_escopo(self, info) -> list | None:
        """Onde mora, de verdade, a variavel que o cartao mostrou nessa linha."""
        if info.scope == "globais":
            return self.tree_data.setdefault("globals", [])
        if info.scope == "ambiente":
            env = scopes.active_env(self.tree_data)
            return env.setdefault("values", []) if env is not None else None
        if info.scope in ("collection", "pasta"):
            tipo = "collection" if info.scope == "collection" else "folder"
            for node in self.ancestry_of(self.current_node() or {}):
                if node.get("type") == tipo and (node.get("name") or "") == info.origin:
                    return node.setdefault("variables", [])
        return None

    def _peek_valor(self, nome: str, valor: str) -> None:
        """Grava o valor editado no cartao, no mesmo escopo de onde ele veio.

        Editar aqui e escrever no lugar certo, e nao criar uma copia no ambiente: a
        linha diz de onde o valor veio, entao e la que a alteracao tem que cair.
        """
        info = self.variables_for(self.current_node()).get(nome)
        if info is None:
            return
        if info.scope == "execucao":
            self.runtime_vars[nome] = valor
            self._refresh_var_hints()
            return

        lista = self._lista_do_escopo(info)
        if lista is None:
            self.statusBar().showMessage(f"nao achei onde {nome} esta definida", 5000)
            return
        for item in lista:
            if (item.get("key") or "").strip() == nome:
                item["value"] = valor
                break
        else:
            lista.append({"key": nome, "value": valor, "enabled": True})

        for editor in self.env_editors.values():
            editor.tabela.reload()
            editor.atualizar()
        self.env_panel.refresh()
        self._reload_envs()
        self.mark_dirty()
        onde = f"{scopes.SCOPE_LABEL.get(info.scope, info.scope)} {info.origin}".strip()
        self.statusBar().showMessage(f"{nome} salvo em {onde}", 4000)

    def _peek_nova(self) -> None:
        self.peek.hide()
        nome, ok = QInputDialog.getText(self, "Nova variavel", "Nome")
        nome = (nome or "").strip()
        if not ok or not nome:
            return
        self.criar_variaveis([nome])
        self._espiar_variaveis()
        self.peek.focar(nome)

    def _editar_ambiente_ativo(self) -> None:
        alvo = self.tree_data.get("activeEnv")
        if not alvo:
            self.side.setCurrentIndex(2)
            return
        self.side.setCurrentIndex(2)
        self.env_panel.selecionar(alvo)
        self.open_environment(alvo)

    def _on_env_changed(self, _index: int) -> None:
        self.tree_data["activeEnv"] = self.env_combo.currentData()
        self.mark_dirty()
        self._refresh_var_hints()
        nome = self.env_combo.currentText()
        self.statusBar().showMessage(f"ambiente {nome}", 3000)

    def new_environment(self) -> None:
        nome, ok = QInputDialog.getText(
            self, "Novo ambiente", "Nome do ambiente, por exemplo dev, hml ou prd"
        )
        if not ok or not nome.strip():
            return
        env = {"id": ws.new_id("env"), "name": nome.strip(), "values": []}
        self.tree_data.setdefault("environments", []).append(env)
        self.tree_data["activeEnv"] = env["id"]
        self._reload_envs()
        self.env_panel.refresh()
        self.env_panel.selecionar(env["id"])
        self.mark_dirty()
        self.side.setCurrentIndex(2)
        self.open_environment(env["id"])
        self.statusBar().showMessage(f"ambiente {env['name']} criado e ja ativo", 5000)

    def ancestry_of(self, target: dict) -> list[dict]:
        """Collection e pastas acima do request, na ordem do mais geral pro mais proximo."""
        trilha: list[dict] = []

        alvo_id = target.get("id")

        def buscar(items, prefixo):
            for node in items or []:
                if node is target or (alvo_id and node.get("id") == alvo_id):
                    trilha.extend(prefixo)
                    return True
                if node.get("items") and buscar(node["items"], prefixo + [node]):
                    return True
            return False

        buscar(self.tree_data.get("collections"), [])
        return trilha

    def variables_for(self, node: dict | None) -> dict:
        return scopes.build(self.tree_data, self.ancestry_of(node) if node else [], self.runtime_vars)

    def _criar_automatico(self, editor: RequestEditor, nomes: list) -> None:
        """Cria variavel sozinho so quando a aba tem edicao sua.

        Abrir um request que usa {{algo}} de outro ambiente nao pode escrever no
        ambiente ativo por conta propria: trocar de ambiente encheria os dois de nome
        vazio sem ninguem ter pedido. Com edicao na aba, foi voce que escreveu.
        """
        if self._sujo(editor):
            self.criar_variaveis(nomes)

    def criar_variaveis(self, nomes: list) -> None:
        """Escrever {{algo}} que nao existe cria a variavel, vazia, no ambiente ativo.

        Sem ambiente ativo ela nasce nas globais do workspace, que e o unico escopo que
        vale sempre. Nasce vazia de proposito: o app nao tem como inventar o valor, mas
        tem como deixar o campo pronto pra receber.
        """
        if not nomes:
            return
        env = scopes.active_env(self.tree_data)
        if env is not None:
            destino = env.setdefault("values", [])
            onde = f"ambiente {env.get('name')}"
        else:
            destino = self.tree_data.setdefault("globals", [])
            onde = "globais do workspace"

        existentes = {(v.get("key") or "").strip() for v in destino}
        criadas = []
        for nome in nomes:
            if nome in existentes:
                continue
            destino.append({"key": nome, "value": "", "enabled": True})
            existentes.add(nome)
            criadas.append(nome)
        if not criadas:
            return

        aberto = self.env_editors.get(env.get("id") if env is not None else GLOBAIS)
        if aberto is not None:
            aberto.tabela.reload()
            aberto.atualizar()
        self.env_panel.refresh()
        self._reload_envs()
        self.mark_dirty()
        self.statusBar().showMessage(
            f"{', '.join(criadas)} criada no {onde}, falta o valor", 9000
        )

    def abrir_variavel(self, nome: str) -> None:
        """Leva ate onde essa variavel se resolve, com o cursor ja no valor."""
        if not nome:
            return
        mapa = self.variables_for(self.current_node())
        info = mapa.get(nome)
        if info is None:
            self.criar_variaveis([nome])
            info = self.variables_for(self.current_node()).get(nome)
            if info is None:
                return

        if info.scope == "ambiente":
            env = scopes.active_env(self.tree_data)
            if env is not None:
                self.open_environment(env.get("id"))
                editor = self.env_editors.get(env.get("id"))
                if editor is not None:
                    editor.focar(nome)
                return
        if info.scope == "globais":
            self.open_environment(GLOBAIS)
            editor = self.env_editors.get(GLOBAIS)
            if editor is not None:
                editor.focar(nome)
            return
        # collection e pasta moram na tela de variaveis, que mostra os cinco escopos
        self.open_variables(info.scope)

    def on_variables_changed(self) -> None:
        self._reload_envs()
        self.mark_dirty()

    def open_variables(self, aba: str = "") -> None:
        node = self.current_node()
        dialog = VariablesDialog(
            self.tree_data,
            self.ancestry_of(node) if node else [],
            self.runtime_vars,
            self,
            aba if isinstance(aba, str) else "",
        )
        dialog.exec()
        self._reload_envs()
        self.mark_dirty()

    def _montar_menu_ambientes(self, menu) -> None:
        """Lista os ambientes no proprio menu, com marca no ativo."""
        while len(menu.actions()) > 2:
            menu.removeAction(menu.actions()[-1])

        ambientes = self.tree_data.get("environments") or []
        if not ambientes:
            return
        menu.addSeparator()
        ativo = self.tree_data.get("activeEnv")
        for env in ambientes:
            acao = QAction(env.get("name") or "sem nome", self)
            acao.setCheckable(True)
            acao.setChecked(env.get("id") == ativo)
            acao.triggered.connect(lambda _=False, e=env: self._usar_ambiente(e["id"]))
            menu.addAction(acao)

    def _usar_ambiente(self, env_id: str) -> None:
        self.tree_data["activeEnv"] = env_id
        self._reload_envs()
        self.env_panel.refresh()
        for outro_id, editor in self.env_editors.items():
            editor.atualizar(ativo=outro_id == env_id)
        self.mark_dirty()
        nome = next(
            (e.get("name") for e in self.tree_data.get("environments") or [] if e.get("id") == env_id),
            "",
        )
        self.statusBar().showMessage(f"ambiente ativo agora e {nome}", 4000)

    def _refresh_var_hints(self) -> None:
        for node_id, editor in self.editors.items():
            editor.set_variables(self.variables_for(editor.request))

        atual = self.current_node()
        mapa = self.variables_for(atual)
        secretas = sum(1 for info in mapa.values() if info.secret)
        env = self.env_combo.currentText()
        partes = [f"{len(mapa)} variaveis"]
        if secretas:
            partes.append(f"{secretas} secretas")
        partes.append(f"ambiente {env}")
        self.status_right.setText("   |   ".join(partes))

        if hasattr(self, "btn_peek"):
            self.btn_peek.setText(f"{len(mapa)} vars")

    # ------------------------------------------------------------------ abas

    def open_request(self, node: dict) -> None:
        node_id = node.get("id")
        if node_id in self.editors:
            self.tabs.setCurrentWidget(self.editors[node_id])
            return

        # A aba trabalha numa copia. Assim editar nao mexe no que esta gravado ate voce
        # mandar salvar, o ponto laranja da aba tem o que significar, e fechar sem salvar
        # volta pro que estava. O que voce envia e sempre a copia, ou seja, o que esta
        # na tela.
        rascunho = copy.deepcopy(node)
        guardado = self.rascunhos.get(node_id)
        if guardado:
            for campo in CAMPOS_EDITAVEIS:
                if campo in guardado:
                    rascunho[campo] = copy.deepcopy(guardado[campo])

        editor = RequestEditor(rascunho)
        editor.no_real = node
        editor.changed.connect(lambda n=rascunho: self._on_editor_changed(n))
        editor.send_requested.connect(self.send_current)
        editor.curl_pedido.connect(lambda texto, n=rascunho: self.importar_curl(texto, n))
        editor.salvar_pedido.connect(lambda e=None: self.salvar_aba())
        editor.exemplos.abrir.connect(self.mostrar_exemplo)
        editor.exemplos.renomear.connect(lambda ex, n=node: self.renomear_exemplo(n, ex))
        editor.exemplos.excluir.connect(lambda ex, n=node: self.excluir_exemplo(n, ex))
        editor.pedir_variavel.connect(self.abrir_variavel)
        editor.criar_variaveis.connect(lambda nomes, e=editor: self._criar_automatico(e, nomes))
        editor.set_variables(self.variables_for(rascunho))
        config, origem = auth.efetiva(rascunho, self.ancestry_of(rascunho))
        editor.set_heranca_auth(
            "" if origem == "deste request" else f"vem de {origem}: {auth.TIPOS.get(config.get('type'), '')}"
        )

        editor.definir_exemplos(node.get("examples"))

        self.editors[node_id] = editor
        index = self.tabs.addTab(editor, node.get("name") or "request")
        self.tabs.setCurrentIndex(index)
        self._marcar_aba(editor)
        self._sync_tabs_visibility()
        self._refresh_var_hints()

    # ------------------------------------------------- rascunho e salvamento

    def _sujo(self, editor: RequestEditor) -> bool:
        real = getattr(editor, "no_real", None)
        return real is not None and _foto(editor.request) != _foto(real)

    def _marcar_aba(self, editor: RequestEditor) -> None:
        """Atualiza pilula, nome, dica e ponto de nao salvo da aba desse editor."""
        index = self.tabs.indexOf(editor)
        if index < 0:
            return
        real = getattr(editor, "no_real", None) or editor.request
        sujo = self._sujo(editor)
        self.tabs.setTabText(index, real.get("name") or "request")
        self.tabs.marcar(editor, "request", editor.request.get("method") or "GET", sujo)
        editor.marcar_sujo(sujo)
        metodo = editor.request.get("method") or "GET"
        dica = "{} {}".format(metodo, editor.request.get("url") or "").strip()
        if sujo:
            dica += "\nalterado, ainda nao salvo.  Ctrl+S salva"
        self.tabs.setTabToolTip(index, dica)

    def _guardar_rascunhos(self) -> None:
        """Grava as copias em aberto em .dbxman, que fica fora do git.

        Sem isso, fechar o app com aba alterada perderia a alteracao. Com isso o
        rascunho volta na proxima abertura e continua marcado como nao salvo.
        """
        atual = {}
        for node_id, editor in self.editors.items():
            if self._sujo(editor):
                atual[node_id] = {c: copy.deepcopy(editor.request.get(c)) for c in CAMPOS_EDITAVEIS}
        self.rascunhos = atual
        if not self.workspace_id:
            return
        try:
            raiz = Path(ws.get_workspace(self.workspace_id)["path"]) / ".dbxman"
            raiz.mkdir(exist_ok=True)
            alvo = raiz / "rascunhos.json"
            if atual:
                alvo.write_text(json.dumps(atual, ensure_ascii=False, indent=1), encoding="utf-8")
            elif alvo.exists():
                alvo.unlink()
        except (OSError, KeyError):
            pass

    def _caminho_janela(self):
        if not self.workspace_id:
            return None
        try:
            raiz = Path(ws.get_workspace(self.workspace_id)["path"]) / ".dbxman"
        except KeyError:
            return None
        raiz.mkdir(exist_ok=True)
        return raiz / "janela.json"

    def _guardar_janela(self) -> None:
        """Grava a largura das colunas em .dbxman, que fica fora do git."""
        alvo = self._caminho_janela()
        if alvo is None:
            return
        dados = {
            "colunas": self.splitter_principal.sizes(),
            "linhas": self.splitter_direita.sizes(),
        }
        try:
            alvo.write_text(json.dumps(dados), encoding="utf-8")
        except OSError:
            pass

    def _ler_janela(self) -> None:
        alvo = self._caminho_janela()
        if alvo is None or not alvo.exists():
            return
        try:
            dados = json.loads(alvo.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        colunas = dados.get("colunas") or []
        if len(colunas) == 2 and colunas[0] > 0:
            self.splitter_principal.setSizes(colunas)

    def _ler_rascunhos(self) -> dict:
        if not self.workspace_id:
            return {}
        try:
            alvo = Path(ws.get_workspace(self.workspace_id)["path"]) / ".dbxman" / "rascunhos.json"
            if alvo.exists():
                return json.loads(alvo.read_text(encoding="utf-8"))
        except (OSError, KeyError, json.JSONDecodeError):
            pass
        return {}

    def salvar_aba(self, index: int = -1) -> bool:
        """Passa a copia da aba pro item de verdade e grava no disco."""
        if index < 0:
            index = self.tabs.currentIndex()
        widget = self.tabs.widget(index)
        if not isinstance(widget, RequestEditor):
            self._save_now()
            return True
        real = getattr(widget, "no_real", None)
        if real is None:
            return True
        if not self._sujo(widget):
            self.statusBar().showMessage("nada mudou nesse request", 3000)
            return True

        for campo in CAMPOS_EDITAVEIS:
            if campo in widget.request:
                real[campo] = copy.deepcopy(widget.request[campo])
        self.tree_panel.refresh_icon(real)
        self.fav_panel.refresh()
        self._marcar_aba(widget)
        self._guardar_janela()
        self._guardar_rascunhos()
        self._save_now()
        self.statusBar().showMessage("{} salvo".format(real.get("name")), 3000)
        return True

    def salvar_todas(self) -> None:
        quantas = 0
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if isinstance(widget, RequestEditor) and self._sujo(widget):
                self.salvar_aba(index)
                quantas += 1
        self._save_now()
        self.statusBar().showMessage(
            "{} request salvos".format(quantas) if quantas else "nenhuma aba tinha alteracao", 4000
        )

    def reverter_aba(self) -> None:
        """Joga fora a copia da aba e volta pro que esta gravado."""
        widget = self.tabs.currentWidget()
        if not isinstance(widget, RequestEditor) or not self._sujo(widget):
            self.statusBar().showMessage("nada pra reverter nessa aba", 3000)
            return
        real = getattr(widget, "no_real", None)
        resposta = QMessageBox.question(
            self,
            "Reverter",
            "Descartar as alteracoes de {} e voltar pro que esta salvo?".format(real.get("name")),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resposta != QMessageBox.StandardButton.Yes:
            return
        for campo in CAMPOS_EDITAVEIS:
            if campo in real:
                widget.request[campo] = copy.deepcopy(real[campo])
            else:
                widget.request.pop(campo, None)
        widget.recarregar_do_modelo()
        self._marcar_aba(widget)
        self._guardar_rascunhos()
        self.statusBar().showMessage("alteracoes descartadas", 3000)

    # ------------------------------------------------------- fechar as abas

    def pedir_fechar(self, index: int) -> None:
        if self._confirmar_fechar(index):
            self.close_tab(index)

    def _confirmar_fechar(self, index: int) -> bool:
        """Devolve se pode fechar. Aba com alteracao pergunta antes."""
        widget = self.tabs.widget(index)
        if not isinstance(widget, RequestEditor) or not self._sujo(widget):
            return True
        real = getattr(widget, "no_real", None) or widget.request
        caixa = QMessageBox(self)
        caixa.setWindowTitle("Alteracoes sem salvar")
        caixa.setText("{} tem alteracoes que ainda nao foram salvas.".format(real.get("name")))
        caixa.setInformativeText("Salvar antes de fechar?")
        salvar = caixa.addButton("Salvar", QMessageBox.ButtonRole.AcceptRole)
        descartar = caixa.addButton("Descartar", QMessageBox.ButtonRole.DestructiveRole)
        caixa.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        caixa.setDefaultButton(salvar)
        caixa.exec()
        if caixa.clickedButton() is salvar:
            self.salvar_aba(index)
            return True
        return caixa.clickedButton() is descartar

    def _fechar_muitas(self, indices) -> None:
        for index in sorted(indices, reverse=True):
            if not self._confirmar_fechar(index):
                return
            self.close_tab(index)

    def _fechar_outras(self, index: int) -> None:
        alvo = self.tabs.widget(index)
        self._fechar_muitas([i for i in range(self.tabs.count()) if self.tabs.widget(i) is not alvo])

    def _fechar_direita(self, index: int) -> None:
        self._fechar_muitas(range(index + 1, self.tabs.count()))

    def _duplicar_aba(self, index: int) -> None:
        widget = self.tabs.widget(index)
        real = getattr(widget, "no_real", None) if isinstance(widget, RequestEditor) else None
        if real is None:
            return
        self.side.setCurrentIndex(0)
        self.tree_panel.duplicate(real)

    def _curl_da_aba(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if isinstance(widget, RequestEditor):
            self.copiar_curl(widget.request)

    def fechar_aba_atual(self) -> None:
        if self.tabs.count():
            self.pedir_fechar(self.tabs.currentIndex())

    def close_tab(self, index: int) -> None:
        widget = self.tabs.widget(index)
        node_id_fechado = None
        for node_id, editor in list(self.editors.items()):
            if editor is widget:
                node_id_fechado = node_id
                del self.editors[node_id]
                break
        for env_id, editor in list(self.env_editors.items()):
            if editor is widget:
                del self.env_editors[env_id]
                break
        self.tabs.removeTab(index)
        self.respostas.pop(node_id_fechado, None)
        self._guardar_rascunhos()
        self._sync_tabs_visibility()

    # ------------------------------------------------------------- ambientes

    def _env_por_id(self, env_id: str) -> dict | None:
        for env in self.tree_data.get("environments") or []:
            if env.get("id") == env_id:
                return env
        return None

    def open_environment(self, env_id: str) -> None:
        if env_id in self.env_editors:
            self.tabs.setCurrentWidget(self.env_editors[env_id])
            return

        if env_id == GLOBAIS:
            self.tree_data.setdefault("globals", [])
            alvo = {"id": GLOBAIS, "name": "Globais", "values": self.tree_data["globals"]}
            editor = EnvEditor(alvo, e_global=True)
            rotulo = "Globais"
        else:
            env = self._env_por_id(env_id)
            if env is None:
                return
            editor = EnvEditor(env)
            editor.atualizar(ativo=env.get("id") == self.tree_data.get("activeEnv"))
            rotulo = env.get("name") or "ambiente"

        editor.changed.connect(self._ambiente_mudou)
        editor.ativar_pedido.connect(self._usar_ambiente)
        self.env_editors[env_id] = editor
        indice = self.tabs.addTab(editor, rotulo)
        self.tabs.marcar(editor, "env")
        self.tabs.setTabToolTip(indice, f"ambiente {rotulo}")
        self.tabs.setCurrentIndex(indice)
        self._sync_tabs_visibility()
        self.response.setVisible(False)

    def _ambiente_mudou(self) -> None:
        self.env_panel.refresh()
        self._reload_envs()
        self.mark_dirty()

    def rename_environment(self, env_id: str) -> None:
        env = self._env_por_id(env_id)
        if not env:
            return
        nome, ok = QInputDialog.getText(self, "Renomear ambiente", "Nome", text=env.get("name") or "")
        if not ok or not nome.strip():
            return
        env["name"] = nome.strip()
        editor = self.env_editors.get(env_id)
        if editor:
            editor.atualizar()
            self.tabs.setTabText(self.tabs.indexOf(editor), env["name"])
        self._ambiente_mudou()

    def duplicate_environment(self, env_id: str) -> None:
        import copy

        env = self._env_por_id(env_id)
        if not env:
            return
        clone = copy.deepcopy(env)
        clone["id"] = ws.new_id("env")
        clone["name"] = f"{env.get('name')} copia"
        self.tree_data["environments"].append(clone)
        self._ambiente_mudou()
        self.open_environment(clone["id"])

    def delete_environment(self, env_id: str) -> None:
        env = self._env_por_id(env_id)
        if not env:
            return
        resposta = QMessageBox.question(
            self,
            "Excluir ambiente",
            f"Excluir o ambiente {env.get('name')} e todos os valores dele?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resposta != QMessageBox.StandardButton.Yes:
            return
        editor = self.env_editors.get(env_id)
        if editor:
            self.close_tab(self.tabs.indexOf(editor))
        self.tree_data["environments"].remove(env)
        if self.tree_data.get("activeEnv") == env_id:
            self.tree_data["activeEnv"] = None
        self._ambiente_mudou()

    def _sync_tabs_visibility(self) -> None:
        has_tabs = self.tabs.count() > 0
        self.tabs.setVisible(has_tabs)
        self.empty.setVisible(not has_tabs)

    def _on_tab_changed(self, _index: int) -> None:
        # aba de ambiente nao tem resposta pra mostrar, entao o painel some
        atual = self.tabs.currentWidget()
        e_request = isinstance(atual, RequestEditor)
        self.response.setVisible(e_request or atual is None)
        self._mostrar_resposta_da_aba()
        self._refresh_var_hints()

    def _mostrar_resposta_da_aba(self) -> None:
        """Cada aba tem a resposta dela. Voltar pra uma aba traz de volta o que veio nela.

        O painel de resposta e um so, entao sem guardar por request trocar de aba
        apagaria o resultado anterior, e comparar duas chamadas viraria refazer as duas.
        """
        atual = self.tabs.currentWidget()
        if not isinstance(atual, RequestEditor):
            self.response.clear()
            return
        node_id = next((k for k, v in self.editors.items() if v is atual), None)
        if node_id in self.pending:
            self.response.show_pending()
            return
        guardado = self.respostas.get(node_id)
        if guardado is None:
            self.response.clear()
            return
        self.response.show_response(guardado[0], guardado[1])

    def _on_editor_changed(self, node: dict) -> None:
        editor = self.editors.get(node.get("id"))
        if editor is None:
            return
        self._marcar_aba(editor)
        # o rascunho vai pro disco sozinho, mas a arvore so muda quando voce salva
        self.rascunho_timer.start()

    def path_of(self, target: dict) -> str:
        trilha: list[str] = []

        alvo_id = target.get("id")

        def buscar(items, prefixo):
            for node in items or []:
                caminho = prefixo + [node.get("name") or ""]
                if node is target or (alvo_id and node.get("id") == alvo_id):
                    trilha.extend(caminho)
                    return True
                if buscar(node.get("items"), caminho):
                    return True
            return False

        buscar(self.tree_data.get("collections"), [])
        return " / ".join(trilha)

    def current_node(self) -> dict | None:
        widget = self.tabs.currentWidget()
        if not isinstance(widget, RequestEditor):
            return None
        for node_id, editor in self.editors.items():
            if editor is widget:
                return editor.request
        return None

    # --------------------------------------------------------------- arvore

    def new_collection(self) -> None:
        name, ok = QInputDialog.getText(self, "Nova collection", "Nome da collection")
        if ok and name.strip():
            self.tree_panel.add_collection(name.strip())

    def _aplicar_ordem(self) -> None:
        mensagem = self.tree_panel.aplicar_ordenacao()
        self.mark_dirty()
        self.statusBar().showMessage(mensagem, 6000)

    def undo_tree(self) -> None:
        """Desfaz a ultima mudanca de estrutura: mover, criar, duplicar ou excluir.

        As abas abertas sao fechadas porque elas apontam pros dicionarios antigos, e
        depois de restaurar a foto esses objetos nao sao mais os que estao na arvore.
        """
        rotulo = self.tree_panel.pode_desfazer()
        if not rotulo:
            self.statusBar().showMessage("nada pra desfazer na arvore", 3000)
            return

        for indice in reversed(range(self.tabs.count())):
            if isinstance(self.tabs.widget(indice), RequestEditor):
                self.close_tab(indice)

        self.tree_panel.desfazer()
        self.fav_panel.refresh()
        self.mark_dirty()
        self.statusBar().showMessage(f"desfeito: {rotulo}", 5000)

    def _destino_para_novo(self) -> dict | None:
        """Onde criar: o item selecionado, a pasta dele, ou a unica collection que existe."""
        node = self.tree_panel.current_node()
        if node and node.get("type") == "example":
            node = node.get("_pai")
        if node:
            return node if node.get("type") != "request" else self.tree_panel.find_parent(node)
        colecoes = self.tree_data.get("collections") or []
        if len(colecoes) == 1:
            return colecoes[0]
        return None

    def new_request(self) -> None:
        destino = self._destino_para_novo()
        if destino is None:
            self.statusBar().showMessage(
                "selecione a collection ou a pasta onde o request deve nascer", 5000
            )
            self.side.setCurrentIndex(0)
            return
        self.side.setCurrentIndex(0)
        self.tree_panel.add_child(destino, "request")

    def new_folder(self) -> None:
        destino = self._destino_para_novo()
        if destino is None:
            self.statusBar().showMessage(
                "selecione a collection ou a pasta que vai conter a nova pasta", 5000
            )
            self.side.setCurrentIndex(0)
            return
        self.side.setCurrentIndex(0)
        novo = self.tree_panel.add_child(destino, "folder")
        self.statusBar().showMessage(
            f"pasta criada dentro de {destino.get('name')}, digite o nome", 5000
        )
        return novo

    def toggle_favorite(self) -> None:
        """Marca o request aberto na aba, ou o selecionado na arvore."""
        node = self.current_node() or self.tree_panel.current_node()
        if not node or node.get("type") != "request":
            self.statusBar().showMessage("selecione ou abra um request pra favoritar", 4000)
            return
        # a aba edita uma copia, e favorito e da arvore, entao marca no item de verdade
        editor = self.editors.get(node.get("id"))
        if editor is not None and getattr(editor, "no_real", None) is not None:
            node = editor.no_real
        self.tree_panel.alternar_favorito(node)
        marcado = bool(node.get("favorite"))
        self.statusBar().showMessage(
            f"{node.get('name')} {'entrou nos favoritos' if marcado else 'saiu dos favoritos'}", 4000
        )

    def _desfavoritar(self, request_id: str) -> None:
        for node in self.tree_panel._iter_nodes():
            if node.get("id") == request_id:
                node["favorite"] = False
                break
        self.fav_panel.refresh()
        self.tree_panel.tree.viewport().update()
        self.mark_dirty()

    def rename_selected(self) -> None:
        node = self.tree_panel.current_node()
        if node:
            self.tree_panel.rename(node)

    def duplicate_selected(self) -> None:
        node = self.tree_panel.current_node()
        if node and node.get("type") == "example":
            self.statusBar().showMessage("exemplo nao duplica, so o request", 4000)
            return
        if node:
            self.tree_panel.duplicate(node)

    def delete_selected(self) -> None:
        node = self.tree_panel.current_node()
        if not node:
            return
        if node.get("type") == "example":
            self.excluir_exemplo(node.get("_pai") or {}, node.get("_exemplo") or {})
            return
        answer = QMessageBox.question(
            self,
            "Excluir",
            f"Excluir {node.get('name')} em definitivo?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        editor = self.editors.get(node.get("id"))
        if editor:
            self.close_tab(self.tabs.indexOf(editor))
        self.tree_panel.remove(node)

    # ---------------------------------------------------------------- envio

    def focus_url(self) -> None:
        widget = self.tabs.currentWidget()
        if isinstance(widget, RequestEditor):
            widget.focus_url()

    def send_current(self) -> None:
        node = self.current_node()
        if not node:
            return
        node_id = node.get("id")
        if node_id in self.pending:
            return

        prepared = engine.prepare(
            node,
            scopes.as_plain(self.variables_for(node)),
            ancestry=self.ancestry_of(node),
            tree=self.tree_data,
            cofre=ws.cofre(self.workspace_id) if self.workspace_id else None,
        )
        prepared.ca_arquivo = self.tree_data.get("caFile") or ""
        if self.jar is not None:
            prepared.cookies = self.jar.para_url(prepared.url)
        if prepared.missing:
            self.statusBar().showMessage(
                f"variavel sem valor: {', '.join(prepared.missing)}", 6000
            )

        self.pending.add(node_id)
        editor = self.editors.get(node_id)
        if editor:
            editor.set_sending(True)
        self.response.show_pending()
        self.registrar(f"{prepared.method} {prepared.url}", "envio", 0)
        self.statusBar().showMessage(f"enviando {prepared.method} {prepared.url}")

        task = SendTask(prepared, node)
        self._tasks.add(task)
        task.signals.done.connect(
            lambda result, item, p=prepared, t=task: self._finish_send(result, item, p, t)
        )
        self.pool.start(task)

    @staticmethod
    def _sent_view(prepared) -> dict | None:
        if prepared is None:
            return None
        return {
            "method": getattr(prepared, "method", ""),
            "url": getattr(prepared, "url", ""),
            "headers": dict(getattr(prepared, "headers", {}) or {}),
            "body": getattr(prepared, "body", "") or "",
        }

    def _finish_send(self, result: dict, node: dict, prepared, task) -> None:
        self._tasks.discard(task)
        self._on_response(result, node, prepared)

    def _on_response(self, result: dict, node: dict, prepared=None) -> None:
        node_id = node.get("id")
        self.pending.discard(node_id)
        editor = self.editors.get(node_id)
        if editor:
            editor.set_sending(False)
        if result.get("error"):
            self.registrar(f"falhou: {result.get('error')}", "erro", 0)
        else:
            self.registrar(
                f"{result.get('status')} {result.get('reason') or ''}".strip()
                + f"   {result.get('elapsedMs')} ms   {node.get('name')}",
                "ok" if result.get("ok") else "aviso",
                0,
            )

        enviado = self._sent_view(prepared)
        if node_id:
            # o ledger vai junto porque e ele que sabe trocar o valor do segredo de volta
            # por {{nome}} na hora de salvar um exemplo
            self.respostas[node_id] = (result, enviado, list(getattr(prepared, "secrets", []) or []))
        if self.current_node() is node:
            self.response.show_response(result, enviado)

        if self.jar is not None and prepared is not None and result.get("cookies"):
            self.jar.guardar(prepared.url, result["cookies"])

        if self.history and prepared is not None:
            try:
                self.history.record(
                    request=node,
                    prepared=prepared,
                    result=result,
                    request_path=self.path_of(node),
                    env_name=self.env_combo.currentText(),
                )
                self.history_panel.reload()
                self.tree_panel.uso = self.history.uso_por_request()
                if self.tree_panel.ordenacao in ("usado", "recente"):
                    self.tree_panel.refresh()
            except Exception as exc:  # noqa: BLE001
                self.statusBar().showMessage(f"nao gravou no historico: {exc}", 6000)
        if result.get("ok"):
            self.statusBar().showMessage(
                f"{result['status']} em {result['elapsedMs']} ms", 5000
            )
        else:
            self.statusBar().showMessage(result.get("error") or "falhou", 8000)

    # --------------------------------------------------------------- navegacao

    def _passo_aba(self, passo: int) -> None:
        total = self.tabs.count()
        if total:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + passo) % total)

    def _ir_para_aba(self, indice: int) -> None:
        if 0 <= indice < self.tabs.count():
            self.tabs.setCurrentIndex(indice)

    def _alternar_lateral(self) -> None:
        self.side.setVisible(not self.side.isVisible())

    def _todos_requests(self) -> list[tuple[dict, str]]:
        saida = []

        def andar(items, prefixo):
            for node in items or []:
                caminho = prefixo + [node.get("name") or ""]
                if node.get("type") == "request":
                    saida.append((node, " / ".join(caminho[:-1])))
                else:
                    andar(node.get("items"), caminho)

        andar(self.tree_data.get("collections"), [])
        return saida

    def goto_request(self) -> None:
        itens = [
            PaletteItem(
                label=node.get("name") or "sem nome",
                sub=f"{caminho}   {node.get('url') or ''}",
                badge=(node.get("method") or "GET"),
                badge_color=theme.METHOD_COLORS.get(node.get("method") or "GET", theme.DIM),
                payload=node,
            )
            for node, caminho in self._todos_requests()
        ]
        if not itens:
            self.statusBar().showMessage("nenhum request neste workspace", 4000)
            return
        escolhido = Palette.escolher(itens, "Ir para request", self)
        if escolhido is not None:
            self.side.setCurrentIndex(0)
            self.tree_panel.select(escolhido.payload.get("id"))
            self.open_request(escolhido.payload)

    def command_palette(self) -> None:
        comandos = [
            ("Enviar o request aberto", "Ctrl+Enter", self.send_current),
            ("Gerar codigo do request", "Ctrl+G", self.open_codegen),
            ("Importar de curl", "Ctrl+Shift+V", self.importar_curl),
            ("Copiar como curl", "Ctrl+Shift+C", lambda: self.copiar_curl()),
            ("Salvar a resposta como exemplo", "", self.salvar_exemplo),
            ("Importar de Postman, Insomnia, Bruno ou OpenAPI", "Ctrl+I", self.importar_arquivo),
            ("Exportar collections", "Ctrl+Shift+E", self.exportar_arquivo),
            ("Ir para request", "Ctrl+P", self.goto_request),
            ("Variaveis", "Ctrl+E", self.open_variables),
            ("Ver historico", "Ctrl+H", lambda: self.side.setCurrentIndex(3)),
            ("Ver ambientes", "", lambda: self.side.setCurrentIndex(2)),
            ("Ver favoritos", "", lambda: self.side.setCurrentIndex(1)),
            ("Favoritar o request aberto", "Ctrl+Shift+F", self.toggle_favorite),
            ("Novo request na selecao", "Ctrl+N", self.new_request),
            ("Desfazer a ultima mudanca na arvore", "Ctrl+Z", self.undo_tree),
            ("Nova collection", "Ctrl+Shift+N", self.new_collection),
            ("Nova pasta na selecao", "Ctrl+Alt+N", self.new_folder),
            ("Novo workspace", "", self.new_workspace),
            ("Gerenciar workspaces", "", self.manage_workspaces),
            ("Renomear item selecionado", "F2", self.rename_selected),
            ("Duplicar item selecionado", "Ctrl+D", self.duplicate_selected),
            ("Excluir item selecionado", "Del", self.delete_selected),
            ("Salvar o request aberto", "Ctrl+S", lambda: self.salvar_aba()),
            ("Salvar todos os requests abertos", "Ctrl+Shift+S", self.salvar_todas),
            ("Reverter o request aberto", "", self.reverter_aba),
            ("Abrir a pasta do workspace", "", self.open_workspace_folder),
            ("Buscar na arvore", "Ctrl+F", lambda: self.search.setFocus()),
            ("Focar na URL", "Ctrl+L", self.focus_url),
            ("Fechar a aba atual", "Ctrl+W", self.fechar_aba_atual),
            ("Mostrar ou esconder a lateral", "Ctrl+B", self._alternar_lateral),
            ("Reconstruir o indice do historico", "", self.rebuild_history_index),
            ("Expurgar historico antigo", "", self.purge_history),
            ("Limpar todo o historico", "", self.clear_history),
            ("Atalhos de teclado", "F1", self.show_shortcuts),
        ]
        for entrada in self.registry["workspaces"]:
            comandos.append(
                (f"Trocar para o workspace {entrada['name']}", "", lambda wid=entrada["id"]: self.load_workspace(wid))
            )

        itens = [PaletteItem(label=rotulo, sub=atalho, action=alvo) for rotulo, atalho, alvo in comandos]
        escolhido = Palette.escolher(itens, "Comando", self)
        if escolhido is not None and escolhido.action is not None:
            escolhido.action()

    def editar_auth_do_grupo(self, node: dict) -> None:
        """Auth da collection ou da pasta, que os requests dentro dela herdam."""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout

        from .auth_editor import AuthEditor

        dialog = QDialog(self)
        e_collection = node.get("type") == "collection"
        dialog.setWindowTitle(f"Auth de {node.get('name')}")
        dialog.resize(620, 460)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 12, 14, 12)

        editor = AuthEditor(node, mostrar_heranca=not e_collection)
        editor.set_variables(self.variables_for(None))
        if not e_collection:
            config, origem = auth.efetiva({}, self.ancestry_of(node))
            editor.set_heranca(
                "" if origem == "nenhum" else f"herdando de {origem}: {auth.TIPOS.get(config.get('type'), '')}"
            )
        layout.addWidget(editor, 1)

        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        botoes.rejected.connect(dialog.accept)
        botoes.accepted.connect(dialog.accept)
        layout.addWidget(botoes)
        dialog.exec()

        self.mark_dirty()
        self._refresh_var_hints()
        for node_id, ed in self.editors.items():
            config, origem = auth.efetiva(ed.request, self.ancestry_of(ed.request))
            ed.set_heranca_auth(
                "" if origem == "deste request"
                else f"vem de {origem}: {auth.TIPOS.get(config.get('type'), '')}"
            )

    def open_certs(self) -> None:
        from .certs_dialog import CertsDialog

        if not self.workspace_id:
            return
        dialog = CertsDialog(self.tree_data, ws.cofre(self.workspace_id), self)
        dialog.exec()
        self.mark_dirty()

    def open_cookies(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        if self.jar is None:
            return
        tudo = self.jar.tudo()
        if not tudo:
            QMessageBox.information(self, "Cookies", "Nenhum cookie guardado neste workspace.")
            return

        linhas = []
        for host, cookies in sorted(tudo.items()):
            linhas.append(f"{host}: {', '.join(sorted(cookies))}")

        caixa = QMessageBox(self)
        caixa.setWindowTitle("Cookies guardados")
        caixa.setText(f"{len(tudo)} dominios, {sum(len(c) for c in tudo.values())} cookies")
        caixa.setDetailedText("\n".join(linhas))
        limpar = caixa.addButton("Limpar tudo", QMessageBox.ButtonRole.DestructiveRole)
        caixa.addButton("Fechar", QMessageBox.ButtonRole.AcceptRole)
        caixa.exec()
        if caixa.clickedButton() is limpar:
            quantos = self.jar.limpar()
            self.statusBar().showMessage(f"{quantos} cookies apagados", 4000)

    def limpar_tokens(self) -> None:
        if not self.workspace_id:
            return
        quantos = auth.limpar_cache(ws.cofre(self.workspace_id))
        self.statusBar().showMessage(
            f"{quantos} tokens do OAuth2 esquecidos, o proximo envio pede um novo", 5000
        )

    def importar_arquivo(self) -> None:
        """Traz collection de Postman, Insomnia, Bruno ou OpenAPI pro workspace aberto."""
        from PySide6.QtWidgets import QDialog, QMessageBox

        from ..core import importer
        from .transfer_dialogs import ImportDialog

        if not self.workspace_id:
            return

        dialogo = ImportDialog(self)
        if dialogo.exec() != QDialog.DialogCode.Accepted or dialogo.resultado is None:
            return

        self.tree_panel.guardar_estado("importar")
        contagem = importer.aplicar(self.tree_data, dialogo.resultado)

        self.tree_panel.refresh()
        self.fav_panel.refresh()
        self.env_panel.refresh()
        self._reload_envs()
        self.mark_dirty()

        recado = (
            f"{dialogo.resultado.formato}: {contagem['collections']} collections e "
            f"{contagem['ambientes']} ambientes entraram"
        )
        if contagem["renomeados"]:
            recado += f", {contagem['renomeados']} renomeados por nome repetido"
        self.statusBar().showMessage(recado, 9000)

        if dialogo.resultado.avisos:
            QMessageBox.information(
                self,
                "Importado, com ressalvas",
                f"{dialogo.resultado.resumo()}\n\n" + "\n\n".join(dialogo.resultado.avisos),
            )

    def exportar_arquivo(self) -> None:
        from PySide6.QtWidgets import QDialog, QMessageBox

        from ..core import importer
        from .transfer_dialogs import ExportDialog

        if not self.workspace_id:
            return

        dialogo = ExportDialog(self.tree_data, self)
        if dialogo.exec() != QDialog.DialogCode.Accepted or dialogo.destino is None:
            return

        colecoes = dialogo.escolhidas()
        if not colecoes:
            self.statusBar().showMessage("nenhuma collection marcada", 4000)
            return

        try:
            saida = importer.exportar(
                self.tree_data,
                colecoes,
                dialogo.combo.currentData(),
                dialogo.destino,
                dialogo.com_segredo.isChecked(),
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Exportar", f"{type(exc).__name__}: {exc}")
            return

        aviso = ""
        if dialogo.com_segredo.isChecked():
            aviso = "  Atencao: este arquivo contem credencial de verdade."
        self.statusBar().showMessage(
            f"{len(colecoes)} collections exportadas para {saida}.{aviso}", 12000
        )

    def importar_curl(self, texto: str = "", node: dict | None = None) -> None:
        """Cola um curl e monta o request inteiro por cima do que estava."""
        from .curl_dialog import CurlDialog

        alvo = node or self.current_node()
        if alvo is None:
            # sem request aberto, cria um novo pra receber o comando
            destino = self._destino_para_novo()
            if destino is None:
                self.statusBar().showMessage(
                    "abra um request ou selecione a collection onde ele deve nascer", 5000
                )
                return
            alvo = self.tree_panel.add_child(destino, "request")
            self.open_request(alvo)

        dados = CurlDialog.pedir(texto, alvo.get("name") or "", self)
        if dados is None:
            return

        self.tree_panel.guardar_estado(f"importar curl em {alvo.get('name')}")
        from ..core import curl_import

        curl_import.aplicar(alvo, dados)

        editor = self.editors.get(alvo.get("id"))
        if editor is not None:
            editor.recarregar_do_modelo()
        self.tree_panel.refresh_icon(alvo)
        self.mark_dirty()

        recado = f"curl importado: {dados.resumo()}"
        if dados.ignorados:
            recado += f".  Ficou de fora: {', '.join(dados.ignorados)}"
        self.statusBar().showMessage(recado, 9000)

    # ------------------------------------------------------------- exemplos

    def _aba_e_no(self) -> tuple:
        """A aba de request aberta e o item de verdade dela, ou (None, None)."""
        widget = self.tabs.currentWidget()
        if not isinstance(widget, RequestEditor):
            return None, None
        return widget, getattr(widget, "no_real", None)

    def salvar_exemplo(self) -> None:
        """Guarda a resposta que esta na tela como exemplo do request."""
        editor, real = self._aba_e_no()
        if editor is None or real is None:
            self.statusBar().showMessage("abra um request pra salvar um exemplo", 4000)
            return
        guardado = self.respostas.get(real.get("id"))
        if not guardado:
            self.statusBar().showMessage("envie o request antes de salvar a resposta", 4000)
            return

        resultado, enviado, ledger = (list(guardado) + [None, None])[:3]
        padrao = f"{resultado.get('status') or ''} {resultado.get('reason') or ''}".strip()
        nome, ok = QInputDialog.getText(
            self, "Salvar como exemplo", "Nome do exemplo", text=padrao or "exemplo"
        )
        nome = (nome or "").strip()
        if not ok or not nome:
            return

        exemplo = examples.montar(nome, resultado, enviado, ledger)
        real.setdefault("examples", []).append(exemplo)
        editor.definir_exemplos(real["examples"])
        # o exemplo tambem vira filho do request na arvore, entao ela precisa remontar
        self.tree_panel.refresh(keep_selection=real.get("id"))
        self.tree_panel.expandir(real.get("id"))
        self.mark_dirty()
        self._save_now()
        self.statusBar().showMessage(
            f"exemplo {nome} salvo dentro de {real.get('name')}, com o segredo trocado por "
            f"{{{{nome}}}}", 9000
        )

    def _exemplo_da_arvore(self, involucro: dict) -> None:
        """Clicar no exemplo abre o request dono e mostra a resposta guardada."""
        pai = involucro.get("_pai")
        if pai is not None:
            self.open_request(pai)
        self.mostrar_exemplo(involucro.get("_exemplo") or {})

    def mostrar_exemplo(self, exemplo: dict) -> None:
        dados, enviado = examples.para_resposta(exemplo)
        self.response.setVisible(True)
        self.response.show_response(dados, enviado)
        self.statusBar().showMessage(f"exemplo {exemplo.get('name')}, so leitura", 5000)

    def renomear_exemplo(self, node: dict, exemplo: dict) -> None:
        editor, real = self._aba_e_no()
        alvo = node if node.get("examples") is not None else real
        if alvo is None:
            alvo = real if real is not None else node
        nome, ok = QInputDialog.getText(
            self, "Renomear exemplo", "Nome", text=exemplo.get("name") or ""
        )
        if not ok or not nome.strip():
            return
        for item in alvo.get("examples") or []:
            if item.get("id") == exemplo.get("id"):
                item["name"] = nome.strip()
                break
        if editor is not None:
            editor.definir_exemplos(alvo.get("examples"))
        self.tree_panel.refresh()
        self.mark_dirty()

    def excluir_exemplo(self, node: dict, exemplo: dict) -> None:
        editor, real = self._aba_e_no()
        alvo = real if real is not None else node
        resposta = QMessageBox.question(
            self,
            "Excluir exemplo",
            f"Excluir o exemplo {exemplo.get('name')}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resposta != QMessageBox.StandardButton.Yes:
            return
        alvo["examples"] = [
            item for item in alvo.get("examples") or [] if item.get("id") != exemplo.get("id")
        ]
        if editor is not None:
            editor.definir_exemplos(alvo["examples"])
        self.tree_panel.refresh()
        self.mark_dirty()

    # ----------------------------------------------------------- codigo pronto

    def copiar_curl(self, node: dict | None = None) -> None:
        """Poe na area de transferencia o curl equivalente ao request.

        Segredo nao vai junto: sai como {{nome}}, igual ao padrao da tela de codigo.
        Curl copiado costuma acabar colado em ticket e em conversa.
        """
        alvo = node or self.current_node()
        if alvo is None:
            self.statusBar().showMessage("abra ou selecione um request primeiro", 4000)
            return
        mapa = self.variables_for(alvo)
        plano = {
            nome: {"value": info.value, "secret": info.secret}
            for nome, info in mapa.items()
            if not info.secret
        }
        preparado = engine.prepare(alvo, plano)
        texto = codegen.generate(
            "curl", preparado.method, preparado.url, preparado.headers, preparado.body
        )
        QGuiApplication.clipboard().setText(texto)
        segredos = [nome for nome, info in mapa.items() if info.secret]
        extra = ", com o segredo como {{nome}}" if segredos else ""
        self.statusBar().showMessage(f"curl de {alvo.get('name')} copiado{extra}", 7000)

    def _codigo_do_no(self, node: dict) -> None:
        self.open_request(node)
        self.open_codegen()

    def open_codegen(self) -> None:
        node = self.current_node()
        if not node:
            self.statusBar().showMessage("abra um request primeiro", 4000)
            return

        mapa = self.variables_for(node)
        editor = self.editors.get(node.get("id"))
        usadas = editor.used_vars() if editor else list(mapa)
        tem_segredo = any(mapa.get(nome) is not None and mapa[nome].secret for nome in usadas)

        def construir(revelar: bool):
            plano = {}
            for nome, info in mapa.items():
                if info.secret and not revelar:
                    continue  # fica como {{nome}} no codigo, que e o padrao seguro
                plano[nome] = {"value": info.value, "secret": info.secret}
            preparado = engine.prepare(node, plano)
            return preparado.method, preparado.url, preparado.headers, preparado.body

        CodegenDialog(construir, tem_segredo, self).exec()

    def show_shortcuts(self) -> None:
        linhas = [
            ("Ctrl+P", "ir para qualquer request"),
            ("Ctrl+K", "paleta de comandos"),
            ("Ctrl+Enter", "enviar"),
            ("Ctrl+G", "gerar codigo"),
            ("Ctrl+Shift+C", "copiar como curl"),
            ("Ctrl+E", "variaveis"),
            ("Ctrl+H", "historico"),
            ("Ctrl+L", "focar na url"),
            ("Ctrl+F", "buscar na arvore"),
            ("Ctrl+N", "novo request"),
            ("Ctrl+Shift+N", "nova collection"),
            ("Ctrl+D", "duplicar"),
            ("F2", "renomear"),
            ("Del", "excluir"),
            ("Ctrl+S", "salvar o request aberto"),
            ("Ctrl+Shift+S", "salvar todos os abertos"),
            ("Ctrl+W", "fechar aba"),
            ("Ctrl+Tab", "proxima aba"),
            ("Ctrl+1 ate Ctrl+9", "ir direto para a aba"),
            ("Ctrl+B", "mostrar ou esconder a lateral"),
            ("Ctrl+`", "console"),
            ("F1", "esta lista"),
        ]
        corpo = "<table cellspacing='6'>" + "".join(
            f"<tr><td><b style='color:{theme.ACCENT};font-family:Consolas'>{tecla}</b></td>"
            f"<td style='color:{theme.TEXT}'>&nbsp;&nbsp;{texto}</td></tr>"
            for tecla, texto in linhas
        ) + "</table>"
        QMessageBox.information(self, "Atalhos de teclado", corpo)

    # ------------------------------------------------------------- historico

    def show_history_response(self, entry: dict) -> None:
        """Mostra a resposta gravada no mesmo viewer, sem reenviar nada."""
        response = entry.get("response") or {}
        self.response.show_response(
            {
                "ok": response.get("ok"),
                "status": response.get("status"),
                "reason": response.get("reason"),
                "headers": response.get("headers") or [],
                "body": response.get("body") or "",
                "sizeBytes": response.get("sizeBytes"),
                "elapsedMs": response.get("elapsedMs"),
                "error": response.get("error"),
            },
            {
                "method": (entry.get("request") or {}).get("method", ""),
                "url": (entry.get("request") or {}).get("url", ""),
                "headers": dict((entry.get("request") or {}).get("headers") or []),
                "body": (entry.get("request") or {}).get("body", ""),
            },
        )
        self.statusBar().showMessage(f"execucao de {entry.get('ts', '')}, so leitura", 5000)

    def reveal_request(self, request_id: str) -> None:
        alvo = None
        for node in self.tree_panel._iter_nodes():
            if node.get("id") == request_id:
                alvo = node
                break
        if not alvo:
            self.statusBar().showMessage("esse request nao existe mais na arvore", 5000)
            return
        self.side.setCurrentIndex(0)
        self.tree_panel.select(request_id)
        self.open_request(alvo)

    def replay_entry(self, entry_id: str) -> None:
        if not self.history:
            return
        entry = self.history.get(entry_id)
        if not entry:
            return

        alvo = None
        if entry.get("requestId"):
            for node in self.tree_panel._iter_nodes():
                if node.get("id") == entry["requestId"]:
                    alvo = node
                    break

        if alvo is not None:
            self.open_request(alvo)
            self.send_current()
            return

        # o request original sumiu, entao reenvia a partir do que ficou gravado
        gravado = entry.get("request") or {}
        headers = []
        mascarados = []
        for key, value in gravado.get("headers") or []:
            if "***" in str(value):
                mascarados.append(key)
                continue
            headers.append({"key": key, "value": value, "enabled": True})

        avulso = {
            "id": f"replay-{entry_id}",
            "type": "request",
            "name": entry.get("name") or "reenvio",
            "method": gravado.get("method") or "GET",
            "url": gravado.get("url") or "",
            "params": [],
            "headers": headers,
            "body": {"mode": "raw" if gravado.get("body") else "none", "raw": gravado.get("body") or ""},
        }
        prepared = engine.prepare(avulso, scopes.as_plain(self.variables_for(None)))
        aviso = f", sem os headers {', '.join(mascarados)}" if mascarados else ""
        self.statusBar().showMessage(f"reenviando execucao antiga{aviso}")

        task = SendTask(prepared, avulso)
        self._tasks.add(task)
        task.signals.done.connect(
            lambda result, item, p=prepared, t=task: self._finish_replay(result, item, p, t)
        )
        self.pool.start(task)

    def _finish_replay(self, result: dict, node: dict, prepared, task) -> None:
        self._tasks.discard(task)
        self._on_replay_done(result, node, prepared)

    def _on_replay_done(self, result: dict, node: dict, prepared) -> None:
        self.response.show_response(result, self._sent_view(prepared))
        if self.history:
            self.history.record(
                request=node,
                prepared=prepared,
                result=result,
                request_path="reenvio a partir do historico",
                env_name=self.env_combo.currentText(),
            )
            self.history_panel.reload()

    def rebuild_history_index(self) -> None:
        if not self.history:
            return
        total = self.history.rebuild_index()
        self.history_panel.reload()
        self.statusBar().showMessage(f"indice reconstruido com {total} execucoes", 6000)

    def purge_history(self) -> None:
        if not self.history:
            return
        resultado = self.history.purge()
        self.history_panel.reload()
        self.statusBar().showMessage(
            f"expurgo: {resultado['arquivos']} arquivos de log e {resultado['registros']} registros",
            6000,
        )

    def clear_history(self) -> None:
        if not self.history:
            return
        resposta = QMessageBox.question(
            self,
            "Limpar historico",
            "Apagar todo o historico deste workspace, log e indice?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resposta == QMessageBox.StandardButton.Yes:
            self.history.clear()
            self.history_panel.reload()
            self.statusBar().showMessage("historico limpo", 4000)

    # ------------------------------------------------------------ salvamento

    def mark_dirty(self) -> None:
        self.statusBar().showMessage("alterado")
        self.save_timer.start()

    def _save_now(self) -> None:
        if not self.workspace_id:
            return
        self.save_timer.stop()
        try:
            resumo = ws.write_tree(self.workspace_id, self.tree_data, self._assinatura)
            self._assinatura = ws.assinatura(self.workspace_id)
        except OSError as exc:
            self.statusBar().showMessage(f"falha ao salvar: {exc}", 8000)
            return

        conflitos = resumo.get("conflitos") or []
        if conflitos:
            quantos = len(conflitos)
            self.statusBar().showMessage(
                f"salvo, mas {quantos} arquivo(s) tinham mudado por fora. "
                f"Copia guardada em .dbxman/conflitos", 12000
            )
            QMessageBox.warning(
                self,
                "Alteracao vinda de fora",
                f"{quantos} arquivo(s) deste workspace mudaram fora do app desde que ele foi "
                f"aberto, e acabaram de ser sobrescritos.\n\n"
                f"Uma copia do que estava no disco ficou em .dbxman/conflitos, dentro da pasta "
                f"do workspace.\n\n"
                + "\n".join(conflitos[:10]),
            )
            return

        self.registrar("workspace salvo no disco", "info", 2)

    def closeEvent(self, event):  # noqa: N802
        sujas = [
            i
            for i in range(self.tabs.count())
            if isinstance(self.tabs.widget(i), RequestEditor) and self._sujo(self.tabs.widget(i))
        ]
        if sujas:
            caixa = QMessageBox(self)
            caixa.setWindowTitle("Alteracoes sem salvar")
            caixa.setText(f"{len(sujas)} request com alteracao que ainda nao foi salva.")
            caixa.setInformativeText(
                "Salvar tudo antes de sair?  Sair sem salvar guarda o rascunho e "
                "devolve ele na proxima abertura."
            )
            salvar = caixa.addButton("Salvar tudo", QMessageBox.ButtonRole.AcceptRole)
            sair = caixa.addButton("Sair assim", QMessageBox.ButtonRole.DestructiveRole)
            caixa.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
            caixa.setDefaultButton(salvar)
            caixa.exec()
            if caixa.clickedButton() is salvar:
                self.salvar_todas()
            elif caixa.clickedButton() is not sair:
                event.ignore()
                return

        self._guardar_rascunhos()
        self._save_now()
        if self.history:
            self.history.close()
        super().closeEvent(event)

    # ------------------------------------------------------------------ sobre

    def show_about(self) -> None:
        from .icon import render

        dialog = QDialog(self)
        dialog.setWindowTitle("Sobre")
        dialog.setFixedWidth(460)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)

        topo = QHBoxLayout()
        marca = QLabel()
        marca.setPixmap(render(64))
        topo.addWidget(marca)

        coluna = QVBoxLayout()
        coluna.setSpacing(2)
        title = QLabel(APP_NAME)
        title.setStyleSheet("font-size: 17pt; font-weight: 700;")
        coluna.addWidget(title)
        versao = QLabel(f"versao {VERSION_LABEL}")
        versao.setObjectName("hint")
        coluna.addWidget(versao)
        coluna.addStretch(1)
        topo.addLayout(coluna, 1)
        layout.addLayout(topo)

        texto = QLabel(
            "Cliente de API local. Nada sai da maquina sem voce mandar, nao existe conta "
            "e nao existe nuvem."
        )
        texto.setWordWrap(True)
        layout.addWidget(texto)

        caminho = QLabel(f"workspaces em {ws.WORKSPACES_DIR}")
        caminho.setObjectName("hint")
        caminho.setWordWrap(True)
        layout.addWidget(caminho)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()

    def show_changelog(self) -> None:
        """Le o CHANGELOG.md do repo. Versao que ninguem le nao serve pra nada."""
        from pathlib import Path

        arquivo = Path(__file__).resolve().parents[2] / "CHANGELOG.md"
        if not arquivo.exists():
            QMessageBox.information(self, "Novidades", "CHANGELOG.md nao encontrado.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Novidades do {APP_NAME}")
        dialog.resize(760, 640)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 14, 16, 14)

        from PySide6.QtWidgets import QTextBrowser

        visor = QTextBrowser()
        visor.setMarkdown(arquivo.read_text(encoding="utf-8"))
        visor.setOpenExternalLinks(False)
        layout.addWidget(visor, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()
