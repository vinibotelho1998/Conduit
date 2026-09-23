"""Janela principal do Conduit."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
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
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, VERSION_LABEL, __version__
from ..core import auth, codegen, dinamicas, engine, examples, scopes, workspaces as ws
from ..core.history import DIAS_CORPO, DIAS_RESUMO, History
from . import icons, theme
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
from .sftp_panel import SftpPanel
from .splitter import Divisor
from .tabbar import AbaTabs
from .tree_panel import TreePanel
from .widgets import Elastico, conta, dica_de_fora


class SendSignals(QObject):
    done = Signal(dict, object)


class SendTask(QRunnable):
    """Envio fora da thread da interface, pra janela nunca congelar.

    O autoDelete fica desligado de proposito. Com ele ligado o Qt destroi o runnable
    assim que run termina, o objeto de sinal morre junto, e a resposta enfileirada pra
    thread da interface se perde antes de ser entregue. Quem segura a referencia e a
    janela, que a solta no _finish_send.
    """

    def __init__(self, prepared, node, geracao: int = 0):
        super().__init__()
        self.setAutoDelete(False)
        self.prepared = prepared
        self.node = node
        # numero do envio: cancelado ou abandonado, o resultado que chegar depois e
        # jogado fora em vez de ir pra tela, pro historico e pros cookies
        self.geracao = geracao
        self.signals = SendSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = engine.send(self.prepared)
        except Exception as exc:  # noqa: BLE001
            # sem resultado o sinal nao sai, e a aba ficava em Enviando pra sempre
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "elapsedMs": 0}
        self.signals.done.emit(result, self.node)


# O que a aba edita e, portanto, o que entra na comparacao de salvo contra alterado.
# Nome, favorito e posicao na arvore nao estao aqui de proposito: quem manda nisso e a
# arvore, e renomear com a aba aberta nao pode virar alteracao pendente do request.
CAMPOS_EDITAVEIS = ("method", "url", "params", "headers", "body", "auth", "docs", "settings")


def _ajustes(no: dict) -> dict:
    """Tempo limite, certificado e redirect, com o padrao do envio no que faltar.

    Request antigo sem settings e um com os valores de fabrica escritos sao o mesmo
    request: sem normalizar, todo request antigo abriria com o ponto de nao salvo aceso.
    """
    bruto = no.get("settings") if isinstance(no.get("settings"), dict) else {}
    try:
        tempo = float(bruto.get("timeout") or 0)
    except (TypeError, ValueError):
        tempo = 0.0
    return {
        "timeout": tempo,
        "verifyTls": bruto.get("verifyTls", True) is not False,
        "followRedirects": bruto.get("followRedirects", True) is not False,
    }


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
        # maiusculo como o envio manda, e como o seletor da aba mostra
        "method": (no.get("method") or "GET").upper(),
        "url": base,
        "params": [ligados, desligados],
        "headers": [
            [h.get("key"), h.get("value") or "", h.get("enabled") is not False]
            for h in no.get("headers") or []
        ],
        "body": {"mode": corpo.get("mode") or "none", "raw": corpo.get("raw") or ""},
        "auth": autenticacao,
        "docs": no.get("docs") or "",
        "settings": _ajustes(no),
    }
    return json.dumps(dados, sort_keys=True, ensure_ascii=False, default=str)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # com a versao no titulo, a barra de tarefas ja diz qual Conduit esta aberto
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1360, 860)

        self.pool = QThreadPool.globalInstance()
        self.workspace_id: str | None = None
        self.tree_data: dict = {"collections": [], "environments": []}
        self.editors: dict[str, RequestEditor] = {}
        self.env_editors: dict[str, EnvEditor] = {}
        self.pending: set[str] = set()
        # geracao do envio em curso de cada request, ver SendTask
        self._geracao: dict[str, int] = {}
        self._contador_envio = 0
        # pasta em que cada servidor SFTP estava quando a sessao caiu, pra reconectar
        self._sftp_voltar: dict[str, str] = {}
        # url de cada envio em curso, pra faixa continuar mostrando o alvo quando
        # a aba sai e volta no meio da espera
        self.enviando_para: dict[str, str] = {}
        self.history: History | None = None
        # navegador de cada servidor SFTP aberto, por id do perfil
        self.sftp_abas: dict = {}
        self._tasks: set = set()
        self._assinatura: dict = {}
        self._recarregando = False
        # alteracao da arvore que ainda nao chegou ao disco, e o motivo da ultima falha
        self._falta_gravar = False
        self._erro_gravar = ""
        # servidores SFTP com conexao a caminho, ver sftp_abrir
        self._sftp_conectando: set = set()
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

        # quem edita o workspace por fora, um script ou o terminal, aparece na tela sem
        # precisar fechar e abrir o app. Do outro lado o gravar_workspace ja protege o
        # trabalho de quem editou por fora, entao os dois sentidos ficam cobertos.
        self.disco_timer = QTimer(self)
        self.disco_timer.setInterval(1500)
        self.disco_timer.timeout.connect(self._checar_disco)

        self._build_toolbar()
        self._build_central()
        self._build_menu()
        self._build_status()

        self._load_registry()

        # O foco nasce na arvore. Sem dizer nada, o Qt entrega o teclado ao primeiro
        # widget focavel da janela, que e o seletor de workspace na barra de cima: ele
        # abria com o anel de foco aceso, parecendo um campo de texto ativo, e um Enter
        # distraido escancarava a lista de workspaces.
        self.tree_panel.tree.setFocus()


    def _build_toolbar(self) -> None:
        bar = QToolBar()
        bar.setMovable(False)
        bar.setFloatable(False)
        self.addToolBar(bar)

        self.ws_button = QToolButton()
        self.ws_button.setObjectName("workspace")
        self.ws_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.ws_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.ws_button.setIconSize(QSize(13, 13))
        self.ws_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ws_menu = QMenu(self)
        self.ws_button.setMenu(self.ws_menu)
        bar.addWidget(self.ws_button)

        # A busca fica logo depois do workspace, do lado esquerdo, porque quem ela
        # filtra e a arvore, que mora embaixo dela. No canto direito, colada no seletor
        # de ambiente, ela parecia buscar a resposta ou o ambiente.
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar request, url ou pasta")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(292)
        self.search.textChanged.connect(self._buscar_na_arvore)
        bar.addWidget(self.search)

        # Espacador. Fica transparente pela regra `QToolBar > .QWidget` da folha: um
        # QWidget comum herda o `background` do app, que e a cor de fundo da janela, e
        # como a barra e mais clara ele pintava uma laje escura de mil pixels nela.
        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().horizontalPolicy().Expanding, spacer.sizePolicy().verticalPolicy())
        bar.addWidget(spacer)

        label = QLabel("Ambiente")
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
        self.peek.segredo_alterado.connect(self._peek_segredo)

    def _build_central(self) -> None:
        self.tree_panel = TreePanel()
        self.tree_panel.request_opened.connect(self.open_request)
        self.tree_panel.tree_changed.connect(self._arvore_mudou)
        self.tree_panel.variaveis_pedidas.connect(self.variaveis_do_grupo)
        self.tree_panel.request_criado.connect(self._abrir_request_novo)
        self.tree_panel.nova_collection_pedida.connect(self.new_collection)
        self.tree_panel.importar_pedido.connect(self.importar_arquivo)
        # Sem atalho aqui de proposito: o menu Arquivo e o Editar ja tem Ctrl+Shift+N,
        # Ctrl+Alt+N e Ctrl+N nestas mesmas tres acoes. Repetir o mesmo atalho numa
        # segunda QAction faz o Qt marcar as duas como ambiguas, e nenhuma das duas
        # dispara mais pelo teclado, so pelo clique. Aqui o botao + ja e clique.
        self.tree_panel.menu_novo.addAction(self._action("Nova collection", self.new_collection))
        self.tree_panel.menu_novo.addAction(self._action("Nova pasta", self.new_folder))
        self.tree_panel.menu_novo.addAction(self._action("Novo request", self.new_request))
        self.tree_panel.favorito_mudou.connect(lambda: self.fav_panel.refresh())
        self.tree_panel.ordem_aplicada.connect(self._aplicar_ordem)
        self.tree_panel.auth_pedida.connect(self.editar_auth_do_grupo)
        self.tree_panel.exemplo_aberto.connect(self._exemplo_da_arvore)
        self.tree_panel.curl_pedido.connect(self.copiar_curl)
        self.tree_panel.codigo_pedido.connect(self._codigo_do_no)
        self.tree_panel.exclusao_pedida.connect(self._excluir_no)
        self.tree_panel.exemplo_exclusao_pedida.connect(self._excluir_exemplo_da_arvore)

        self.history_panel = HistoryPanel()
        self.history_panel.replay_requested.connect(self.replay_entry)
        self.history_panel.open_request_requested.connect(self.reveal_request)
        self.history_panel.load_response_requested.connect(self.show_history_response)
        self.history_panel.recado.connect(lambda texto: self.statusBar().showMessage(texto, 8000))

        self.env_panel = EnvPanel()
        self.env_panel.abrir.connect(self.open_environment)
        self.env_panel.criar.connect(self.new_environment)
        self.env_panel.ativar.connect(self._usar_ambiente)
        self.env_panel.renomear.connect(self.rename_environment)
        self.env_panel.duplicar.connect(self.duplicate_environment)
        self.env_panel.excluir.connect(self.delete_environment)

        self.fav_panel = FavoritesPanel()
        self.fav_panel.abrir.connect(self._abrir_favorito)
        self.fav_panel.desfavoritar.connect(self._desfavoritar)

        self.side = QTabWidget()
        self.side.setObjectName("sideTabs")
        self.side.setDocumentMode(True)
        self.side.addTab(self.tree_panel, "Collections")
        self.side.addTab(self.fav_panel, "Favoritos")
        self.side.addTab(self.env_panel, "Ambientes")
        self.sftp_panel = SftpPanel()
        self.sftp_panel.conectar.connect(self.sftp_abrir)
        self.sftp_panel.criar.connect(self.sftp_novo)
        self.sftp_panel.editar.connect(self.sftp_editar)
        self.sftp_panel.duplicar.connect(self.sftp_duplicar)
        self.sftp_panel.excluir.connect(self.sftp_excluir)
        self.sftp_panel.desconectar.connect(self.sftp_desconectar)

        self.side.addTab(self.history_panel, "Historico")
        self.side.addTab(self.sftp_panel, "SFTP")

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
        self.response.copiar_curl_completo.connect(lambda: self.copiar_curl_completo())

        self.console = ConsolePanel()
        self.console.fechar_pedido.connect(lambda: self.alternar_console(False))
        self.console.hide()

        right = Divisor(Qt.Orientation.Vertical)
        right.addWidget(center)
        right.addWidget(self.response)
        right.addWidget(self.console)
        # Meio a meio. Antes o request nascia com 520 e a resposta com 320, entao um
        # request sem params abria com quase quatrocentos pixels de grade vazia em cima
        # da resposta, que e justamente o que a pessoa acabou de pedir pra ler.
        right.setSizes([440, 440, 0])
        right.setChildrenCollapsible(False)
        self.splitter_direita = right

        # A coluna da esquerda tem tamanho proprio: sem fator de esticar, o Qt
        # reparte qualquer sobra entre os dois lados e a arvore anda sozinha toda vez
        # que a janela muda de tamanho.
        # abaixo de uns 290 as cinco abas da lateral viravam setas, e os botoes de
        # Ambientes e do Historico viravam pedacos de palavra
        self.side.setMinimumWidth(290)
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
        editar.addAction(self._acao_da_arvore("Desfazer na arvore", self.undo_tree, "Ctrl+Z"))
        editar.addSeparator()
        editar.addAction(self._action("Novo request na selecao", self.new_request, "Ctrl+N"))
        editar.addAction(self._action("Nova pasta na selecao", self.new_folder, "Ctrl+Alt+N"))
        editar.addAction(self._acao_da_arvore("Renomear", self.rename_selected, "F2"))
        editar.addAction(self._acao_da_arvore("Duplicar", self.duplicate_selected, "Ctrl+D"))
        editar.addAction(self._acao_da_arvore("Excluir", self.delete_selected, "Del"))
        editar.addSeparator()
        editar.addAction(self._action("Favoritar ou desfavoritar", self.toggle_favorite, "Ctrl+Shift+F"))
        editar.addSeparator()
        acao_buscar = self._action("Buscar", self._focar_busca, QKeySequence.StandardKey.Find)
        # sem isso, Ctrl+F dentro da resposta virava atalho ambiguo com a busca na
        # resposta, que tambem escuta Ctrl+F: nenhum dos dois disparava direito. Preso
        # so a lateral, este so responde quando o foco esta ali.
        acao_buscar.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.side.addAction(acao_buscar)
        editar.addAction(acao_buscar)
        editar.addSeparator()
        editar.addAction(self._action("Variaveis", self.open_variables, "Ctrl+E"))

        ambientes = editar.addMenu("Ambientes")
        # Ctrl+Shift+E colidia com Exportar, no menu Arquivo: as duas acoes tinham o
        # mesmo atalho, e o Qt nao dispara nenhuma quando duas ficam ambiguas assim
        ambientes.addAction(self._action("Novo ambiente", self.new_environment, "Ctrl+Alt+E"))
        ambientes.addAction(self._action("Gerenciar ambientes", self._gerenciar_ambientes))
        ambientes.aboutToShow.connect(lambda: self._montar_menu_ambientes(ambientes))

        ver = menu.addMenu("&Ver")
        tema_menu = ver.addMenu("Tema")
        self._acao_tema = {}
        for valor, rotulo in (("escuro", "Escuro"), ("claro", "Claro")):
            acao = QAction(rotulo, self, checkable=True)
            acao.triggered.connect(lambda _=False, v=valor: self._trocar_tema(v))
            tema_menu.addAction(acao)
            self._acao_tema[valor] = acao
        densidade_menu = ver.addMenu("Densidade")
        self._acao_densidade = {}
        for valor, rotulo in (("confortavel", "Confortavel"), ("compacta", "Compacta")):
            acao = QAction(rotulo, self, checkable=True)
            acao.triggered.connect(lambda _=False, v=valor: self._trocar_densidade(v))
            densidade_menu.addAction(acao)
            self._acao_densidade[valor] = acao
        self._marcar_tema_no_menu()
        ver.aboutToShow.connect(self._marcar_tema_no_menu)

        executar = menu.addMenu("E&xecutar")
        executar.addAction(self._action("Enviar", self.send_current, "Ctrl+Return"))
        executar.addAction(self._action("Focar na URL", self.focus_url, "Ctrl+L"))
        executar.addSeparator()
        executar.addAction(self._action("Gerar codigo", self.open_codegen, "Ctrl+G"))
        # sem atalho aqui: o menu Arquivo ja registra Ctrl+Shift+V nesta mesma acao, e
        # duas QAction com o mesmo atalho ficam ambiguas pro Qt e nenhuma dispara mais
        executar.addAction(self._action("Importar de curl", self.importar_curl))
        executar.addSeparator()
        executar.addAction(self._action("Servidores SFTP", lambda: self._ir_para_lateral(4)))
        executar.addAction(self._action("Certificados e CA", self.open_certs))
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
        ir.addAction(
            self._action(
                "Copiar curl completo, com segredo em claro",
                lambda: self.copiar_curl_completo(),
            )
        )
        ir.addAction(self._action("Copiar a url resolvida", lambda: self.copiar_url()))
        ir.addAction(self._action("Console", lambda: self.alternar_console(), "Ctrl+`"))
        ir.addAction(self._action("Salvar resposta como exemplo", self.salvar_exemplo))
        ir.addSeparator()
        ir.addAction(self._action("Mostrar ou esconder a lateral", self._alternar_lateral, "Ctrl+B"))

        historico = menu.addMenu("&Historico")
        historico.addAction(self._action("Ver historico", lambda: self._ir_para_lateral(3), "Ctrl+H"))
        historico.addAction(self._action("Enviar o request de novo", self.history_panel._replay))
        historico.addSeparator()
        historico.addAction(self._action("Reconstruir indice", self.rebuild_history_index))
        historico.addAction(
            self._action(f"Apagar corpos com mais de {DIAS_CORPO} dias", self.purge_history)
        )
        historico.addAction(self._action("Limpar tudo", self.clear_history))

        ajuda = menu.addMenu("A&juda")
        ajuda.addAction(self._action("Atalhos de teclado", self.show_shortcuts, "F1"))
        ajuda.addAction(self._action("Novidades desta versao", self.show_changelog))
        ajuda.addAction(self._action(f"Sobre o {APP_NAME}", self.show_about))

        # A versao mora no canto da barra de menus, que sobra vazio depois do Ajuda ate
        # na janela mais estreita. No rodape ela dividia a direita com ambiente e
        # variaveis e passava batido.
        self.versao = QLabel(f"v{__version__}")
        self.versao.setObjectName("versao")
        self.versao.setToolTip(f"{APP_NAME} {VERSION_LABEL}. Ajuda, Novidades mostra o que mudou.")
        # o Qt poe o canto no alto da barra com a altura do proprio texto, entao ele
        # ganha a altura de um menu pra ficar na mesma linha dos nomes
        self.versao.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.versao.setMinimumHeight(menu.actionGeometry(menu.actions()[0]).height())
        menu.setCornerWidget(self.versao, Qt.Corner.TopRightCorner)

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

    def _acao_da_arvore(self, text: str, slot, shortcut) -> QAction:
        """Acao cujo atalho so vale com o foco na arvore; o clique no menu vale sempre.

        F2, Del, Ctrl+D e Ctrl+Z eram atalhos de janela barrados por uma guarda de foco,
        e a guarda barrava tambem o clique no menu e a paleta: com o cursor na url,
        Editar, Renomear nao fazia nada e nao dizia nada. Preso a arvore, o atalho deixa
        Del, F2 e Enter livres pra grade e pro navegador SFTP.
        """
        action = self._action(text, slot, shortcut)
        action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.tree_panel.addAction(action)
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
            "", "mostrar ou esconder a lateral,  Ctrl+B", self._alternar_lateral
        )
        self.btn_lateral.setIconSize(QSize(16, 16))
        theme.ao_trocar_widget(self.btn_lateral, lambda b: b.setIcon(icons.icone_lateral()))
        barra.addWidget(self.btn_lateral)

        self.btn_console = self._rodape_botao(
            "Console", "o que o app fez nesta sessao,  Ctrl+`", lambda: self.alternar_console()
        )
        self.btn_console.setCheckable(True)
        barra.addWidget(self.btn_console)

        self.btn_historico_rodape = self._rodape_botao(
            "Historico", "execucoes gravadas,  Ctrl+H", lambda: self._ir_para_lateral(3)
        )
        barra.addWidget(self.btn_historico_rodape)

        self.btn_pasta_rodape = self._rodape_botao(
            "Pasta do workspace", "abrir a pasta no explorador", self.open_workspace_folder
        )
        barra.addWidget(self.btn_pasta_rodape)
        barra.separador()

        # Elastico pelo mesmo motivo da mensagem: nome de ambiente comprido nao alarga a janela
        self.status_right = Elastico()
        self.status_right.setObjectName("hint")
        self.statusBar().addPermanentWidget(self.status_right)

        self.statusBar().showMessage("pronto")


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

    def _marcar_tema_no_menu(self) -> None:
        for valor, acao in self._acao_tema.items():
            acao.setChecked(valor == theme.NOME)
        for valor, acao in self._acao_densidade.items():
            acao.setChecked(valor == theme.DENSIDADE)

    def _trocar_tema(self, nome: str) -> None:
        if nome == theme.NOME:
            return
        theme.aplicar(QApplication.instance(), nome=nome)
        ws.write_preferences(tema=nome)
        self._marcar_tema_no_menu()
        self.registrar(f"tema {nome}", "info", 3)

    def _trocar_densidade(self, densidade: str) -> None:
        if densidade == theme.DENSIDADE:
            return
        theme.aplicar(QApplication.instance(), densidade=densidade)
        ws.write_preferences(densidade=densidade)
        self._marcar_tema_no_menu()
        self.registrar(f"densidade {densidade}", "info", 3)
        self.registrar("reabra o Conduit pra grade e arvore usarem a nova altura de linha por completo", "info", 6)

    def _load_registry(self) -> None:
        registry = ws.list_workspaces()
        self.registry = registry
        self.ws_menu.clear()

        ativo = registry.get("active")

        titulo = QAction("Trocar de workspace", self)
        titulo.setEnabled(False)
        self.ws_menu.addAction(titulo)

        for entry in registry["workspaces"]:
            aberto = entry["id"] == ativo
            action = QAction(entry["name"], self)
            # Ponto na cor do workspace, com anel em volta no que esta aberto. Antes
            # isto era setCheckable numa acao que tambem tinha icone: o Qt desenha o
            # visto e o icone na mesma coluna, entao a lista inteira parecia igual e
            # nao dava pra saber qual estava aberto.
            action.setIcon(icons.ponto_cor(entry.get("color") or theme.DIM, atual=aberto))
            if aberto:
                fonte = action.font()
                fonte.setBold(True)
                action.setFont(fonte)
                action.setToolTip("este ja esta aberto")
            else:
                action.setToolTip(entry["path"])
                # so quem nao esta aberto responde ao clique: recarregar o que ja esta
                # na tela fecha aba e refaz arvore a toa
                action.triggered.connect(
                    lambda _=False, wid=entry["id"]: self.load_workspace(wid)
                )
            self.ws_menu.addAction(action)

        self.ws_menu.addSeparator()
        self.ws_menu.addAction(self._action("Novo workspace", self.new_workspace))
        self.ws_menu.addAction(self._action("Gerenciar workspaces", self.manage_workspaces))

        target = registry.get("active") or (registry["workspaces"][0]["id"] if registry["workspaces"] else None)
        if target:
            self.load_workspace(target)

    def load_workspace(self, wid: str) -> None:
        if self.workspace_id and self._falta_gravar and not self._save_now():
            # Trocar descarta a arvore da memoria. Com o disco recusando a gravacao, era
            # la que estava a unica copia do que mudou, e ela sumia sem aviso.
            if not self._seguir_sem_gravar("Trocar de workspace"):
                return
        if self.workspace_id and self.rascunho_timer.isActive():
            # a ultima tecla da aba ainda nao tinha ido pro rascunho, e as abas fecham aqui
            self._guardar_rascunhos()
        self.rascunho_timer.stop()
        # Envio pendurado do workspace que sai e abandonado: a resposta que chegasse depois
        # ia pro historico do workspace novo, que promete que nada vaza entre eles.
        self.pending.clear()
        self.enviando_para.clear()
        self._geracao.clear()

        entry = ws.get_workspace(wid)
        self.workspace_id = wid
        self.tree_data = ws.read_tree(wid)
        # a arvore agora e a do disco, entao nada esta pendente. Trocando depois de aceitar
        # perder o que nao gravou, a marca ficava ligada e o timer do disco parava de ver
        # o que mudava por fora no workspace novo ate o proximo salvar
        self._falta_gravar = False
        self._erro_gravar = ""
        self._assinatura = ws.assinatura(wid)
        ws.set_active(wid)

        self._pintar_botao_workspace(entry)

        # trocar de workspace derruba as conexoes: cofre, known_hosts e perfis sao de
        # um workspace so, e uma sessao aberta apontando pro anterior nao faz sentido
        for navegador in list(self.sftp_abas.values()):
            navegador.encerrar()
        self.sftp_abas.clear()

        paginas = [self.tabs.widget(i) for i in range(self.tabs.count())]
        self.tabs.clear()
        for pagina in paginas:
            self._descartar_pagina(pagina)
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
        self.sftp_panel.load(self.tree_data)
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
        self.disco_timer.start()

    def _checar_disco(self) -> None:
        """Ve se alguem mexeu no workspace por fora e traz pra tela."""
        if not self.workspace_id or self.save_timer.isActive():
            return
        if self._falta_gravar:
            # Salvar falhou e o que mudou so existe na memoria. Reler o disco agora
            # trocava a arvore da memoria pela do disco: um salvar que gravou metade dos
            # arquivos e parou muda a assinatura. A proxima edicao grava de novo, e trocar
            # de workspace ou fechar o app pergunta antes de perder.
            return
        if QApplication.activeModalWidget() is not None:
            # O timer continua batendo com um dialogo aberto. Variaveis, certificados e
            # auth da pasta editam a arvore que receberam ao abrir, e trocar a arvore por
            # baixo deles fazia o que se digitou ali sumir no salvar seguinte. Fechado o
            # dialogo, o salvar ja guarda em .conduit/conflitos o que mudou por fora.
            return
        try:
            atual = ws.assinatura(self.workspace_id)
        except (OSError, KeyError):
            # KeyError e o workspace aberto saindo do registro, pela tela de gerenciar.
            # Sem pegar aqui, o timer estourava a cada segundo e meio, e cada estouro
            # abria mais uma caixa de erro por cima da anterior.
            return
        if atual != self._assinatura:
            self._recarregar_do_disco(atual)
        self._aplicar_rascunho_de_fora()

    def _aplicar_rascunho_de_fora(self) -> None:
        """Rascunho escrito por fora entra como alteracao pendente, e nao como salvo.

        Editar o yaml da collection por fora chega na aba ja como conteudo gravado, e
        ai nao ha o que desfazer. Escrevendo em .conduit/rascunhos.json a alteracao
        chega marcada como nao salva: da pra ver a bolinha, comparar, salvar com Ctrl+S
        ou descartar fechando a aba.
        """
        # nao da pra sair quando o rascunho_timer esta ativo: recarregar a aba mexe no
        # editor e liga esse timer, entao a guarda barrava exatamente o caso que
        # interessa. O que protege aqui e comparar conteudo, nao data de arquivo.
        do_disco = self._ler_rascunhos()
        if do_disco == self.rascunhos:
            return

        mudou = 0
        self._recarregando = True
        try:
            for node_id, campos in do_disco.items():
                editor = self.editors.get(node_id)
                if editor is None or campos == self.rascunhos.get(node_id):
                    continue
                for campo in CAMPOS_EDITAVEIS:
                    if campo in campos:
                        editor.request[campo] = copy.deepcopy(campos[campo])
                editor.recarregar_do_modelo()
                self._marcar_aba(editor)
                mudou += 1
        finally:
            self._recarregando = False

        self.rascunhos = do_disco
        if mudou:
            self.statusBar().showMessage(
                f"{conta(mudou, 'aba recebeu', 'abas receberam')} alteracao de fora, ainda nao salva",
                6000,
            )

    def _recarregar_do_disco(self, atual: dict | None = None) -> None:
        """Relê a arvore do disco sem fechar aba nem perder o que voce esta editando.

        As abas com alteracao pendente ficam como estao, so passam a apontar pro node
        novo. Quem nao tem alteracao pendente e redesenhado com o que veio do disco.
        """
        preservadas = 0
        self._recarregando = True
        try:
            self.tree_data = ws.read_tree(self.workspace_id)
            self._assinatura = atual or ws.assinatura(self.workspace_id)

            por_id: dict = {}

            def indexar(nos):
                for no in nos or []:
                    if no.get("id"):
                        por_id[no["id"]] = no
                    indexar(no.get("items"))

            indexar(self.tree_data.get("collections"))

            for node_id, editor in self.editors.items():
                novo = por_id.get(node_id)
                if novo is None:
                    continue
                # o sujo compara a aba com o node que ela tinha, entao ele tem que ser
                # medido antes de trocar a referencia pelo que acabou de vir do disco
                tinha_alteracao = self._sujo(editor)
                editor.no_real = novo
                if tinha_alteracao:
                    preservadas += 1
                    continue
                editor.request.clear()
                editor.request.update(copy.deepcopy(novo))
                editor.recarregar_do_modelo()
                editor.definir_exemplos(novo.get("examples"))
                self._marcar_aba(editor)

            # A aba de ambiente segurava o dicionario da arvore antiga. O que se digitava
            # nela depois de recarregar ia pra um ambiente que ja nao estava na arvore, e o
            # salvar seguinte gravava sem a edicao, calado. A edicao feita antes daqui ja
            # foi pro disco: o recarregar nao roda com salvamento pendente.
            for env_id, aba_env in list(self.env_editors.items()):
                if env_id == GLOBAIS:
                    valores = self.tree_data.setdefault("globals", [])
                    aba_env.env["values"] = valores
                else:
                    novo_env = self._env_por_id(env_id)
                    if novo_env is None:
                        self.close_tab(self.tabs.indexOf(aba_env))
                        continue
                    aba_env.env = novo_env
                    valores = novo_env.setdefault("values", [])
                    self.tabs.setTabText(self.tabs.indexOf(aba_env), novo_env.get("name") or "ambiente")
                aba_env.tabela.rows = valores
                aba_env.tabela.reload()
                aba_env.atualizar(ativo=env_id == self.tree_data.get("activeEnv"))

            self.tree_panel.load(self.tree_data)
            self.tree_panel.definir_ordenacao(self.tree_data.get("sortMode") or "manual")
            self.fav_panel.load(self.tree_data)
            self.env_panel.load(self.tree_data)
            self.sftp_panel.load(self.tree_data)
            self._reload_envs()
            self._refresh_var_hints()
        finally:
            self._recarregando = False

        aviso = "recarregado do disco"
        if preservadas:
            aviso += (
                f", {conta(preservadas, 'aba com alteracao sua ficou', 'abas com alteracao sua ficaram')}"
                " como estava" + ("" if preservadas == 1 else "m")
            )
        self.statusBar().showMessage(aviso, 5000)

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
        from .workspaces_dialog import criar_workspace

        name, ok = QInputDialog.getText(self, "Novo workspace", "Nome do workspace")
        if not ok or not name.strip():
            return
        entry = criar_workspace(self, name.strip())
        if entry is None:
            return
        self._load_registry()
        self.load_workspace(entry["id"])

    def manage_workspaces(self) -> None:
        """Renomear, trocar cor, duplicar, abrir a pasta e excluir."""
        from .workspaces_dialog import WorkspacesDialog

        # o que estava pra gravar grava agora: dentro do dialogo o workspace aberto pode
        # sair do registro, e ai nao haveria mais onde gravar
        if self.workspace_id and self._falta_gravar:
            self._save_now()
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
            self._pintar_botao_workspace(ws.get_workspace(self.workspace_id))

    def _pintar_botao_workspace(self, entrada: dict) -> None:
        """Nome, ponto na cor do workspace e a dica que diz o que aquilo e.

        O nome sozinho na barra nao dizia a que se referia, e quem abre o programa pela
        primeira vez le "Exemplos" e nao tem como saber que aquilo e um seletor.
        """
        self.ws_button.setText(entrada["name"])
        cor = entrada.get("color") or theme.DIM
        theme.ao_trocar_widget(
            self.ws_button,
            lambda alvo, c=cor: alvo.setIcon(icons.ponto_cor(c)),
        )
        self.ws_button.setToolTip(
            f"Workspace aberto: {entrada['name']}\n"
            f"{entrada['path']}\n\n"
            "Clique pra trocar, criar ou gerenciar."
        )

    def open_workspace_folder(self) -> None:
        import os

        if self.workspace_id:
            os.startfile(ws.get_workspace(self.workspace_id)["path"])  # noqa: S606


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

    def _peek_segredo(self, nome: str, secreta: bool) -> None:
        """Marca ou desmarca a variavel como secreta, no escopo de onde ela veio.

        Desmarcar traz o valor de volta pro arquivo versionado, entao vale um aviso: o
        que estava so no cofre passa a poder aparecer no git.
        """
        info = self.variables_for(self.current_node()).get(nome)
        if info is None:
            return
        if info.scope == "execucao":
            self.statusBar().showMessage(
                "variavel de execucao nao vai pro cofre, ela morre ao fechar", 5000
            )
            return
        lista = self._lista_do_escopo(info)
        if lista is None:
            self.statusBar().showMessage(f"nao achei onde {nome} esta definida", 5000)
            return
        for item in lista:
            if (item.get("key") or "").strip() == nome:
                item["secret"] = secreta
                break
        else:
            return

        for editor in self.env_editors.values():
            editor.tabela.reload()
            editor.atualizar()
        self.env_panel.refresh()
        self._reload_envs()
        self.mark_dirty()
        self._espiar_variaveis()
        self.peek.focar(nome)
        onde = f"{scopes.SCOPE_LABEL.get(info.scope, info.scope)} {info.origin}".strip()
        if secreta:
            self.statusBar().showMessage(f"{nome} agora e secreta em {onde}", 4000)
        else:
            self.statusBar().showMessage(
                f"{nome} deixou de ser secreta em {onde}, o valor volta pro arquivo", 6000
            )

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
        self._ir_para_lateral(2)
        if not alvo:
            return
        self.env_panel.selecionar(alvo)
        self.open_environment(alvo)

    def _gerenciar_ambientes(self) -> None:
        """Os ambientes moram na lateral. Antes este item abria a tela de variaveis, que
        nao tem mais aba de ambiente, e caia na aba Collection sem ambiente nenhum."""
        self._ir_para_lateral(2)
        self.env_panel.selecionar(self.tree_data.get("activeEnv"))

    def _on_env_changed(self, _index: int) -> None:
        # O mesmo que Usar este na lateral: trocar so o dado deixava a lista e a aba do
        # ambiente marcando o antigo como ativo, com o envio ja usando o novo.
        env_id = self.env_combo.currentData()
        self.tree_data["activeEnv"] = env_id
        self.env_panel.refresh()
        for outro_id, editor in self.env_editors.items():
            editor.atualizar(ativo=outro_id == env_id)
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
        self._ir_para_lateral(2)
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

    def criar_variaveis(self, nomes: list) -> None:
        """Cria a variavel, vazia, no ambiente ativo. Vem do criar da faixa e do cartao.

        Sem ambiente ativo ela nasce nas globais do workspace, que e o unico escopo que
        vale sempre. Nasce vazia de proposito: o app nao tem como inventar o valor, mas
        tem como deixar o campo pronto pra receber.
        """
        # Nome com cifrao e gerado na hora do envio e nunca vira variavel gravada.
        # Segunda barreira de proposito: o editor ja filtra, mas esta funcao tambem e
        # chamada de outros caminhos, e foi por um deles que um $guid vazio acabou
        # gravado no ambiente de producao.
        nomes = [n for n in (nomes or []) if not dinamicas.eh_dinamica(n)]
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
        # collection e pasta moram na tela de variaveis; a origem escolhe a pasta certa
        # quando ha pasta dentro de pasta
        self.open_variables(info.scope, info.origin)

    def on_variables_changed(self) -> None:
        self._reload_envs()
        self.mark_dirty()

    def open_variables(self, aba: str = "", origem: str = "", linhagem: list | None = None) -> None:
        if linhagem is None:
            node = self.current_node()
            linhagem = self.ancestry_of(node) if node else []
        dialog = VariablesDialog(
            self.tree_data,
            linhagem,
            self.runtime_vars,
            self,
            aba if isinstance(aba, str) else "",
            origem if isinstance(origem, str) else "",
        )
        dialog.exec()
        self._reload_envs()
        self.mark_dirty()

    def variaveis_do_grupo(self, node: dict) -> None:
        """Variaveis de uma collection ou pasta pelo botao direito, sem request aberto."""
        e_colecao = node.get("type") == "collection"
        self.open_variables(
            "collection" if e_colecao else "pasta",
            node.get("name") or "",
            self.ancestry_of(node) + [node],
        )

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
        partes = [conta(len(mapa), "variavel", "variaveis")]
        if secretas:
            partes.append(conta(secretas, "secreta", "secretas"))
        # sem ambiente, o rodape dizia "ambiente sem ambiente"
        partes.append(
            f"ambiente {self.env_combo.currentText()}" if self.env_combo.currentData()
            else "sem ambiente ativo"
        )
        self.status_right.setText("   |   ".join(partes))

        if hasattr(self, "btn_peek"):
            self.btn_peek.setText(conta(len(mapa), "variavel", "variaveis"))


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
        editor.copiar_curl_pedido.connect(
            lambda claro, n=rascunho: (
                self.copiar_curl_completo(n) if claro else self.copiar_curl(n)
            )
        )
        editor.copiar_url_pedido.connect(lambda n=rascunho: self.copiar_url(n))
        editor.codigo_pedido.connect(self.open_codegen)
        editor.exemplos.abrir.connect(self.mostrar_exemplo)
        editor.exemplos.renomear.connect(lambda ex, n=node: self.renomear_exemplo(n, ex))
        editor.exemplos.excluir.connect(lambda ex, n=node: self.excluir_exemplo(n, ex))
        editor.pedir_variavel.connect(self.abrir_variavel)
        editor.cancelar_pedido.connect(lambda i=node_id: self.cancelar_envio(i))
        editor.set_variables(self.variables_for(rascunho))
        editor.set_heranca_auth(self._texto_heranca(rascunho))
        # fechar e reabrir a aba no meio do envio mostrava Enviar aceso que nao fazia nada
        editor.set_sending(node_id in self.pending)

        editor.definir_exemplos(node.get("examples"))

        self.editors[node_id] = editor
        index = self.tabs.addTab(editor, node.get("name") or "request")
        self.tabs.setCurrentIndex(index)
        self._marcar_aba(editor)
        self._sync_tabs_visibility()
        self._refresh_var_hints()


    def _texto_heranca(self, request: dict) -> str:
        config, origem = auth.efetiva(request, self.ancestry_of(request))
        if origem == "deste request":
            return ""
        if origem == "nenhum":
            return "nenhuma pasta nem a collection define auth, sai sem credencial"
        return f"vem de {origem}: {auth.TIPOS.get(config.get('type'), '')}"

    def _abrir_request_novo(self, node: dict) -> None:
        """Request recem criado abre na aba, com o cursor na url, assim que ganha nome."""
        self.open_request(node)
        editor = self.editors.get(node.get("id"))
        if editor is not None:
            editor.focus_url()

    def _arvore_mudou(self) -> None:
        """Renomear, mover ou desfazer na arvore chega nas abas e nos favoritos.

        Antes so marcava pra gravar: a aba seguia com o nome antigo, e depois de arrastar
        pra outra collection a aba Auth e as cores das variaveis ficavam no escopo antigo
        enquanto o envio ja usava o novo.
        """
        self.mark_dirty()
        self.fav_panel.refresh()
        for editor in self.editors.values():
            self._marcar_aba(editor)
            editor.set_heranca_auth(self._texto_heranca(editor.request))
        self._refresh_var_hints()

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
        # a url pode vir de collection importada, ver widgets.dica_de_fora
        self.tabs.setTabToolTip(index, dica_de_fora(dica))

    def _guardar_rascunhos(self) -> None:
        """Grava as copias em aberto em .conduit, que fica fora do git.

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
            raiz = Path(ws.get_workspace(self.workspace_id)["path"]) / ".conduit"
            raiz.mkdir(exist_ok=True)
            alvo = raiz / "rascunhos.json"
            if atual:
                # temporario e troca, como o resto do app grava: escrito direto, um
                # desligamento no meio deixava o JSON cortado, e ler JSON cortado devolve
                # vazio. Todo rascunho de toda aba ia embora de uma vez.
                temporario = alvo.with_suffix(".json.tmp")
                temporario.write_text(json.dumps(atual, ensure_ascii=False, indent=1), encoding="utf-8")
                temporario.replace(alvo)
            elif alvo.exists():
                alvo.unlink()
        except (OSError, KeyError):
            pass

    def _caminho_janela(self):
        if not self.workspace_id:
            return None
        try:
            raiz = Path(ws.get_workspace(self.workspace_id)["path"]) / ".conduit"
        except KeyError:
            return None
        raiz.mkdir(exist_ok=True)
        return raiz / "janela.json"

    def _guardar_janela(self) -> None:
        """Grava a largura das colunas em .conduit, que fica fora do git."""
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
        # a altura entre request, resposta e console era gravada e nunca lida de volta:
        # o divisor voltava sempre no lugar de fabrica
        linhas = dados.get("linhas") or []
        if len(linhas) == 3 and sum(linhas) > 0:
            self.splitter_direita.setSizes(linhas)
            self.alternar_console(linhas[2] > 0)

    def _ler_rascunhos(self) -> dict:
        if not self.workspace_id:
            return {}
        try:
            alvo = Path(ws.get_workspace(self.workspace_id)["path"]) / ".conduit" / "rascunhos.json"
            if alvo.exists():
                dados = json.loads(alvo.read_text(encoding="utf-8"))
                # o arquivo tambem chega escrito por fora, e so mapa de mapa e rascunho
                if isinstance(dados, dict):
                    return {k: v for k, v in dados.items() if isinstance(v, dict)}
        except (OSError, KeyError, ValueError):
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
        if not any(no is real for no in self.tree_panel._iter_nodes()):
            # O request saiu da arvore por fora, num git checkout ou num arquivo apagado,
            # com a aba aberta e alterada. Gravar no item solto dizia salvo e nao gravava
            # nada: ele nao estava mais em arvore nenhuma, e o rascunho era apagado junto.
            self.statusBar().showMessage(
                "{} nao existe mais no workspace, a alteracao continua so nesta aba".format(
                    real.get("name")
                ),
                9000,
            )
            return False

        for campo in CAMPOS_EDITAVEIS:
            if campo in widget.request:
                real[campo] = copy.deepcopy(widget.request[campo])
        self.tree_panel.refresh_icon(real)
        self.fav_panel.refresh()
        self._marcar_aba(widget)
        self._guardar_janela()
        self._guardar_rascunhos()
        if self._save_now():
            # na falha fica a mensagem do _save_now, e nao um salvo que nao aconteceu
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
            conta(quantas, "request salvo", "requests salvos") if quantas
            else "nenhuma aba tinha alteracao",
            4000,
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
            # salvar recusado deixa a aba aberta, senao a alteracao ia embora com ela
            return self.salvar_aba(index)
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
        self._ir_para_lateral(0)
        # com edicao na aba, a copia leva o que esta na tela, e nao o que esta no arquivo:
        # quem duplica pra guardar duas variantes perdia justamente a variante nova
        campos = None
        if self._sujo(widget):
            campos = {c: copy.deepcopy(widget.request[c]) for c in CAMPOS_EDITAVEIS if c in widget.request}
        self.tree_panel.duplicate(real, campos)

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
        for perfil_id, navegador in list(self.sftp_abas.items()):
            if navegador is widget:
                navegador.encerrar()
                del self.sftp_abas[perfil_id]
                self.sftp_panel.marcar_ligado(perfil_id, False)
                break
        self.tabs.removeTab(index)
        self._descartar_pagina(widget)
        self.respostas.pop(node_id_fechado, None)
        self._guardar_rascunhos()
        self._sync_tabs_visibility()

    @staticmethod
    def _descartar_pagina(widget) -> None:
        """Apaga a pagina que saiu das abas.

        removeTab e clear so tiram a pagina da vista: ela continuava filha da area de
        abas, viva, com grade, realce e folha de estilo registrada na troca de tema. Cada
        aba aberta e fechada ficava na memoria ate o app fechar, e trocar de tema ia
        ficando mais lento. O navegador SFTP fica de fora: a tarefa que ainda esta no
        pool responde nele depois de fechado.
        """
        if isinstance(widget, (RequestEditor, EnvEditor)):
            widget.deleteLater()


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
        if not has_tabs:
            # sem request aberto, a metade de baixo repetia outro estado vazio
            self.response.setVisible(False)

    def _on_tab_changed(self, _index: int) -> None:
        # aba de ambiente nao tem resposta pra mostrar, entao o painel some
        atual = self.tabs.currentWidget()
        e_request = isinstance(atual, RequestEditor)
        self.response.setVisible(e_request)
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
            self.response.show_pending(self.enviando_para.get(node_id, ''))
            return
        guardado = self.respostas.get(node_id)
        if guardado is None:
            self.response.clear()
            return
        self.response.show_response(guardado[0], guardado[1], "vivo", guardado[2], node_id)

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

        A foto restaurada traz dicionarios novos, entao cada aba aberta passa a apontar
        pro item de mesmo id, como no recarregar do disco. Antes todas as abas de request
        fechavam, inclusive as sem relacao com o que se desfazia, e cancelar a pergunta
        de uma delas cancelava o desfazer.
        """
        rotulo = self.tree_panel.pode_desfazer()
        if not rotulo:
            self.statusBar().showMessage("nada pra desfazer na arvore", 3000)
            return

        # o sujo compara com o item antigo, entao e medido antes da troca
        sujos = {node_id for node_id, editor in self.editors.items() if self._sujo(editor)}
        self._recarregando = True
        try:
            self.tree_panel.desfazer()
        finally:
            self._recarregando = False
        por_id = {no.get("id"): no for no in self.tree_panel._iter_nodes()}
        fechadas = 0
        for node_id, editor in list(self.editors.items()):
            novo = por_id.get(node_id)
            if novo is None:
                if node_id not in sujos:
                    # o request nao existe na foto, como o que acabou de ser criado
                    self.close_tab(self.tabs.indexOf(editor))
                    fechadas += 1
                # com rascunho, a aba fica: salvar avisa que o request saiu do workspace
                continue
            editor.no_real = novo
            if node_id not in sujos:
                self._recarregando = True
                try:
                    editor.request.clear()
                    editor.request.update(copy.deepcopy(novo))
                    editor.recarregar_do_modelo()
                finally:
                    self._recarregando = False
            editor.definir_exemplos(novo.get("examples"))
        self._arvore_mudou()
        recado = f"desfeito: {rotulo}"
        if fechadas:
            recado += f", {conta(fechadas, 'aba fechou', 'abas fecharam')} junto"
        self.statusBar().showMessage(recado, 5000)

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

    def _destino_ou_colecao_nova(self) -> dict | None:
        """Como _destino_para_novo, e sem collection nenhuma pergunta o nome da primeira.

        Workspace recem criado mandava selecionar a collection, sem nenhuma pra selecionar.
        """
        if not self.tree_data.get("collections"):
            nome, ok = QInputDialog.getText(
                self, "Nova collection", "O workspace ainda nao tem collection. Nome da primeira"
            )
            if not ok or not nome.strip():
                return None
            return self.tree_panel.add_collection(nome.strip())
        return self._destino_para_novo()

    def new_request(self) -> None:
        # a lateral aparece antes: com ela escondida por Ctrl+B, o request nascia numa
        # arvore invisivel e a tela nao mudava nada
        self._ir_para_lateral(0)
        destino = self._destino_ou_colecao_nova()
        if destino is None:
            if self.tree_data.get("collections"):
                self.statusBar().showMessage(
                    "selecione a collection ou a pasta onde o request deve nascer", 5000
                )
            return
        novo = self.tree_panel.add_child(destino, "request")
        if self.tree_panel.tree.state() != QAbstractItemView.State.EditingState:
            # sem a edicao do nome aberta, nao ha fim de edicao pra esperar
            self.tree_panel._nomeando = None
            self._abrir_request_novo(novo)

    def new_folder(self) -> None:
        self._ir_para_lateral(0)
        destino = self._destino_ou_colecao_nova()
        if destino is None:
            if self.tree_data.get("collections"):
                self.statusBar().showMessage(
                    "selecione a collection ou a pasta que vai conter a nova pasta", 5000
                )
            return
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
            self._ir_para_lateral(0)
            self.tree_panel.rename(node)
        else:
            self.statusBar().showMessage("selecione na arvore o item a renomear", 4000)

    def duplicate_selected(self) -> None:
        node = self.tree_panel.current_node()
        if node and node.get("type") == "example":
            self.statusBar().showMessage("exemplo nao duplica, so o request", 4000)
            return
        if node:
            self.tree_panel.duplicate(node)

    def delete_selected(self) -> None:
        node = self.tree_panel.current_node()
        if node:
            self._excluir_no(node)
        else:
            self.statusBar().showMessage("selecione na arvore o item a excluir", 4000)

    def _excluir_exemplo_da_arvore(self, involucro: dict) -> None:
        """Botao direito, Excluir exemplo, na propria arvore.

        Passa pela mesma confirmacao e pelo mesmo aviso ao editor aberto que o botao de
        excluir do painel Exemplos ja usava. Excluir direto da arvore, sem isso, apagava
        sem perguntar e deixava a aba do request com a contagem de exemplos desatualizada.
        """
        self.excluir_exemplo(involucro.get("_pai") or {}, involucro.get("_exemplo") or {})

    def _excluir_no(self, node: dict) -> None:
        """Confirma, fecha a aba se o request excluido estiver aberta, e so entao remove.

        Usado tanto pelo Del do teclado quanto pelo Excluir do menu de contexto da
        arvore: os dois caminhos precisam da mesma seguranca, senao o botao direito
        apaga sem perguntar e deixa a aba aberta apontando pro que nao existe mais.
        """
        if node.get("type") == "example":
            self.excluir_exemplo(node.get("_pai") or {}, node.get("_exemplo") or {})
            return
        # diz o tipo e o que vai junto, e nao promete definitivo: Ctrl+Z na arvore desfaz
        tipo = {"collection": "a collection", "folder": "a pasta"}.get(node.get("type"), "o request")
        juntos = ""
        if node.get("type") != "request":
            pastas = sum(1 for n in self.tree_panel._iter_nodes(node.get("items") or [])
                         if n.get("type") == "folder")
            requests = len(self._ids_de_requests(node))
            partes = ([conta(pastas, "pasta", "pastas")] if pastas else []) + [
                conta(requests, "request", "requests")
            ]
            juntos = f", com {' e '.join(partes)}"
        answer = QMessageBox.question(
            self,
            "Excluir",
            f"Excluir {tipo} {node.get('name')}{juntos}?\n\n"
            "Ctrl+Z na arvore desfaz enquanto o app estiver aberto.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        # exclui a aba de cada request que morre junto, nao so a do proprio no: apagar
        # uma pasta ou collection inteira deixava aba orfa de tudo que estava dentro
        for filho_id in self._ids_de_requests(node):
            editor = self.editors.get(filho_id)
            if editor:
                self.close_tab(self.tabs.indexOf(editor))
        self.tree_panel.remove(node)

    def _ids_de_requests(self, node: dict) -> list[str]:
        if node.get("type") == "request":
            return [node.get("id")]
        saida = []
        for filho in node.get("items") or []:
            saida.extend(self._ids_de_requests(filho))
        return saida


    def focus_url(self) -> None:
        from .sftp_browser import SftpBrowser

        widget = self.tabs.currentWidget()
        if isinstance(widget, RequestEditor):
            widget.focus_url()
        elif isinstance(widget, SftpBrowser):
            # com a aba SFTP na frente, Ctrl+L e o campo de caminho do navegador
            widget._editar_caminho()

    def _buscar_na_arvore(self, texto: str) -> None:
        # digitar na busca com a lateral em outra aba filtrava a arvore escondida
        if texto and (not self.side.isVisible() or self.side.currentIndex() != 0):
            self._ir_para_lateral(0)
        self.tree_panel.apply_filter(texto)

    def _focar_busca(self) -> None:
        """Ctrl+F busca o que esta na frente, e nao sempre a arvore de collections.

        Antes ele focava a busca da arvore mesmo com o Historico na tela: a pessoa
        digitava e nada mudava, porque o campo que respondia estava numa aba escondida.
        """
        if self.side.isVisible() and self.side.currentIndex() == 3:  # Historico tem busca propria
            self.history_panel.search.setFocus()
            self.history_panel.search.selectAll()
            return
        self._ir_para_lateral(0)
        self.search.setFocus()
        self.search.selectAll()

    def send_current(self) -> None:
        node = self.current_node()
        if not node:
            return
        node_id = node.get("id")
        if node_id in self.pending:
            self.statusBar().showMessage(
                "este request ja tem um envio em curso. Cancelar, ou Esc, abandona a espera", 5000
            )
            return

        # rede desligada: token do OAuth2 que nao esta no cofre e pedido pelo send, ja na
        # thread do pool. Pedido daqui, a janela congelava ate o provedor responder.
        prepared = engine.prepare(
            node,
            scopes.as_plain(self.variables_for(node)),
            ancestry=self.ancestry_of(node),
            tree=self.tree_data,
            cofre=ws.cofre(self.workspace_id) if self.workspace_id else None,
            rede=False,
        )
        prepared.ca_arquivo = self.tree_data.get("caFile") or ""
        if self.jar is not None:
            prepared.cookies = self.jar.para_url(prepared.url)
        if prepared.missing:
            self.statusBar().showMessage(
                f"variavel sem valor: {', '.join(prepared.missing)}", 6000
            )

        self._contador_envio += 1
        geracao = self._contador_envio
        self._geracao[node_id] = geracao
        self.pending.add(node_id)
        editor = self.editors.get(node_id)
        if editor:
            editor.set_sending(True)
        self.enviando_para[node_id] = prepared.url
        self.response.show_pending(prepared.url)
        self.registrar(f"{prepared.method} {prepared.url}", "envio", 0)
        if prepared.esquema_suposto:
            self.statusBar().showMessage(
                f"a url veio sem http, enviando como {prepared.url}", 6000
            )
        else:
            self.statusBar().showMessage(f"enviando {prepared.method} {prepared.url}")

        task = SendTask(prepared, node, geracao)
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

    def cancelar_envio(self, node_id: str) -> None:
        """Abandona a espera. A thread segue presa ate o servidor responder ou cair,
        mas o que chegar depois nao vai pra tela, pro historico nem pros cookies."""
        if node_id not in self.pending:
            return
        self.pending.discard(node_id)
        self.enviando_para.pop(node_id, None)
        self._geracao.pop(node_id, None)
        editor = self.editors.get(node_id)
        if editor is not None:
            editor.set_sending(False)
        if self.current_node() is not None and self.current_node().get("id") == node_id:
            self.response.clear()
            self.response.pretty.edit.setPlaceholderText(
                "envio cancelado, nada foi gravado no historico"
            )
        self.registrar("envio cancelado por voce", "aviso", 5)

    def _finish_send(self, result: dict, node: dict, prepared, task) -> None:
        self._tasks.discard(task)
        node_id = node.get("id")
        if self._geracao.get(node_id) != task.geracao:
            # cancelado, ou de um workspace que ja foi fechado
            return
        self._geracao.pop(node_id, None)
        self._on_response(result, node, prepared)

    def _on_response(self, result: dict, node: dict, prepared=None) -> None:
        node_id = node.get("id")
        self.pending.discard(node_id)
        self.enviando_para.pop(node_id, None)
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
            self.response.show_response(
                result, enviado, "vivo", self.respostas[node_id][2] if node_id else None, node_id
            )

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
            erro = result.get("error") or "falhou"
            self.statusBar().showMessage(
                engine.explicar_erro(erro, getattr(prepared, "url", "")) or erro, 9000
            )


    def _passo_aba(self, passo: int) -> None:
        total = self.tabs.count()
        if total:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + passo) % total)

    def _ir_para_aba(self, indice: int) -> None:
        if 0 <= indice < self.tabs.count():
            self.tabs.setCurrentIndex(indice)

    def _alternar_lateral(self) -> None:
        self.side.setVisible(not self.side.isVisible())

    def _ir_para_lateral(self, indice: int) -> None:
        """Mostra a lateral se estiver escondida e abre a aba pedida.

        Ctrl+H e Ctrl+F trocavam a aba interna sem checar se a lateral inteira estava
        escondida por Ctrl+B: a tecla parecia nao fazer nada, porque a troca acontecia
        atras de um painel invisivel.
        """
        if not self.side.isVisible():
            self.side.setVisible(True)
        self.side.setCurrentIndex(indice)

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
            self._ir_para_lateral(0)
            self.tree_panel.select(escolhido.payload.get("id"))
            self.open_request(escolhido.payload)

    def command_palette(self) -> None:
        comandos = [
            ("Enviar o request aberto", "Ctrl+Enter", self.send_current),
            ("Gerar codigo do request", "Ctrl+G", self.open_codegen),
            ("Importar de curl", "Ctrl+Shift+V", self.importar_curl),
            ("Copiar como curl", "Ctrl+Shift+C", lambda: self.copiar_curl()),
            ("Copiar curl completo, com segredo em claro", "", lambda: self.copiar_curl_completo()),
            ("Copiar a url resolvida", "", lambda: self.copiar_url()),
            ("Salvar a resposta como exemplo", "", self.salvar_exemplo),
            ("Importar de Postman, Insomnia, Bruno ou OpenAPI", "Ctrl+I", self.importar_arquivo),
            ("Exportar collections", "Ctrl+Shift+E", self.exportar_arquivo),
            ("Ir para request", "Ctrl+P", self.goto_request),
            ("Variaveis", "Ctrl+E", self.open_variables),
            ("Ver historico", "Ctrl+H", lambda: self._ir_para_lateral(3)),
            ("Ver ambientes", "", lambda: self._ir_para_lateral(2)),
            ("Ver favoritos", "", lambda: self._ir_para_lateral(1)),
            ("Ver servidores SFTP", "", lambda: self._ir_para_lateral(4)),
            ("Cadastrar servidor SFTP", "", self.sftp_novo),
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
            ("Buscar", "Ctrl+F", self._focar_busca),
            ("Focar na URL", "Ctrl+L", self.focus_url),
            ("Fechar a aba atual", "Ctrl+W", self.fechar_aba_atual),
            ("Mostrar ou esconder a lateral", "Ctrl+B", self._alternar_lateral),
            ("Reconstruir o indice do historico", "", self.rebuild_history_index),
            (f"Apagar corpos do historico com mais de {DIAS_CORPO} dias", "", self.purge_history),
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
        for ed in self.editors.values():
            ed.set_heranca_auth(self._texto_heranca(ed.request))

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

        entraram = "entrou" if contagem["collections"] + contagem["ambientes"] == 1 else "entraram"
        recado = (
            f"{dialogo.resultado.formato}: {conta(contagem['collections'], 'collection', 'collections')} e "
            f"{conta(contagem['ambientes'], 'ambiente', 'ambientes')} {entraram}"
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
        # no Postman os ambientes saem em arquivos proprios ao lado da collection, e sem
        # esta parte ninguem sabia que a pasta tinha ganho mais arquivos
        ambientes = len(self.tree_data.get("environments") or [])
        junto = ""
        if ambientes and dialogo.formato == "postman":
            junto = f", com {conta(ambientes, 'ambiente', 'ambientes')} na mesma pasta"
        self.statusBar().showMessage(
            f"{conta(len(colecoes), 'collection exportada', 'collections exportadas')} "
            f"para {saida}{junto}.{aviso}",
            12000,
        )

    def importar_curl(self, texto: str = "", node: dict | None = None) -> None:
        """Cola um curl e monta o request inteiro por cima do que estava."""
        from .curl_dialog import CurlDialog

        from ..core import curl_import

        alvo = node or self.current_node()
        destino = None
        if alvo is None:
            # sem request aberto, o request novo so nasce depois do curl aceito: criado
            # antes, cancelar deixava um Novo request vazio na arvore
            destino = self._destino_ou_colecao_nova()
            if destino is None:
                if self.tree_data.get("collections"):
                    self.statusBar().showMessage(
                        "abra um request ou selecione a collection onde ele deve nascer", 5000
                    )
                return

        dados = CurlDialog.pedir(texto, (alvo or {}).get("name") or "", self)
        if dados is None:
            return

        if alvo is None:
            self._ir_para_lateral(0)
            alvo = self.tree_panel.add_child(destino, "request")
            self.tree_panel._nomeando = None
            # o curl entra no item antes de a aba tirar a copia dela; aplicado depois, a
            # aba abria vazia e o Ctrl+S gravava a copia vazia por cima do importado
            curl_import.aplicar(alvo, dados)
            caminho = urlsplit(alvo.get("url") or "").path.rstrip("/")
            alvo["name"] = f"{alvo.get('method') or 'GET'} {caminho or '/'}"
            self.tree_panel.refresh(keep_selection=alvo.get("id"))
            self.open_request(alvo)
            self.mark_dirty()
            self.statusBar().showMessage(
                f"curl importado num request novo: {dados.resumo()}"
                + (f".  Ficou de fora: {', '.join(dados.ignorados)}" if dados.ignorados else ""),
                9000,
            )
            return

        self.tree_panel.guardar_estado(f"importar curl em {alvo.get('name')}")
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
        # O que esta na tela, e nao a ultima resposta ao vivo: com uma execucao do
        # historico aberta, o exemplo gravado era o envio de agora.
        exibido = self.response.exibido
        if exibido and exibido.get("origem") == "exemplo":
            self.statusBar().showMessage("isto ja e um exemplo guardado", 4000)
            return
        if not exibido:
            self.statusBar().showMessage("envie o request antes de salvar a resposta", 4000)
            return
        if exibido.get("dono") != real.get("id"):
            # Execucao de outro request aberta pelo historico, ou reenvio de um request que
            # ja saiu da arvore: cair na ultima resposta desta aba gravava o que nao estava
            # na tela.
            self.statusBar().showMessage(
                "a resposta na tela e de outro request. Abra a aba dele pra guardar o exemplo", 5000
            )
            return
        guardado = (exibido["dados"], exibido["enviado"], exibido["ledger"])

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
        if self._save_now():
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

    def _dono_do_exemplo(self, exemplo: dict, *candidatos) -> dict | None:
        """O request que guarda esse exemplo de verdade, ja na arvore de agora.

        O pedido chega por dois caminhos: o painel Exemplos da aba e o menu da arvore. O
        da arvore pode vir com a aba de outro request na frente, e decidir pela aba aberta
        mexia no request errado: excluir nao excluia nada, e renomear trocava a lista de
        exemplos da aba da frente pela do outro request. Pelo id, e nao pelo objeto, porque
        depois de recarregar do disco o node que a aba guardou ja nao e o da arvore.
        """
        vivos = []
        for no in candidatos:
            if no:
                vivos.append(self.tree_panel._by_id.get(no.get("id")) or no)
        for no in vivos:
            if any(i.get("id") == exemplo.get("id") for i in no.get("examples") or []):
                return no
        return vivos[0] if vivos else None

    def renomear_exemplo(self, node: dict, exemplo: dict) -> None:
        _, real = self._aba_e_no()
        alvo = self._dono_do_exemplo(exemplo, node, real)
        if alvo is None:
            return
        nome, ok = QInputDialog.getText(
            self, "Renomear exemplo", "Nome", text=exemplo.get("name") or ""
        )
        if not ok or not nome.strip():
            return
        for item in alvo.get("examples") or []:
            if item.get("id") == exemplo.get("id"):
                item["name"] = nome.strip()
                break
        editor = self.editors.get(alvo.get("id"))
        if editor is not None:
            editor.definir_exemplos(alvo.get("examples"))
        self.tree_panel.refresh()
        self.mark_dirty()

    def excluir_exemplo(self, node: dict, exemplo: dict) -> None:
        _, real = self._aba_e_no()
        alvo = self._dono_do_exemplo(exemplo, node, real)
        if alvo is None:
            return
        editor = self.editors.get(alvo.get("id"))
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
        # sem rede e sem cofre: o token do OAuth2 sai como {{oauth2_token}}. Antes o
        # copiar pedia um token novo ao provedor com a janela parada, e o token vivo ia
        # em claro justo na copia que promete trocar segredo por {{nome}}. A linhagem
        # vai junto porque sem ela a auth herdada da pasta ou da collection ficava de fora
        preparado = engine.prepare(alvo, plano, ancestry=self.ancestry_of(alvo), rede=False)
        texto = codegen.generate(
            "curl", preparado.method, preparado.url, preparado.headers, preparado.body
        )
        QGuiApplication.clipboard().setText(texto)
        segredos = [nome for nome, info in mapa.items() if info.secret]
        extra = ", com o segredo como {{nome}}" if segredos else ""
        self.statusBar().showMessage(f"curl de {alvo.get('name')} copiado{extra}", 7000)

    def copiar_url(self, node: dict | None = None) -> None:
        """Poe na area de transferencia a url final, com variavel e query resolvidas.

        Segue a regra do resto do app: segredo sai como {{nome}}. Url com token na query
        e justamente o caso em que colar num chat vaza credencial sem ninguem perceber.
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
        preparado = engine.prepare(alvo, plano, ancestry=self.ancestry_of(alvo), rede=False)
        QGuiApplication.clipboard().setText(preparado.url)
        self.statusBar().showMessage(f"url de {alvo.get('name')} copiada", 6000)

    def copiar_curl_completo(self, node: dict | None = None) -> None:
        """O curl com tudo resolvido: variavel, credencial e segredo em texto puro.

        E o irmao perigoso do copiar_curl. Existe porque colar um curl com {{nome}} num
        terminal nao roda, e reproduzir uma chamada fora do app e justamente o momento
        em que voce precisa dela exatamente como o servidor recebeu.

        Nao pergunta nada antes: o botao ja diz completo e o rodape avisa o que foi
        parar na area de transferencia. Perguntar toda vez viraria ruido numa acao que
        so se usa de proposito.
        """
        alvo = node or self.current_node()
        if alvo is None:
            self.statusBar().showMessage("abra ou selecione um request primeiro", 4000)
            return

        mapa = self.variables_for(alvo)
        # o token do OAuth2 vem do cofre quando ja existe um valido. Sem ele, fica o
        # {{oauth2_token}}: pedir um novo daqui travaria a janela esperando o provedor
        preparado = engine.prepare(
            alvo,
            scopes.as_plain(mapa),
            ancestry=self.ancestry_of(alvo),
            cofre=ws.cofre(self.workspace_id) if self.workspace_id else None,
            rede=False,
        )
        texto = codegen.generate(
            "curl", preparado.method, preparado.url, preparado.headers, preparado.body
        )
        QGuiApplication.clipboard().setText(texto)

        segredos = len([1 for info in mapa.values() if info.secret and info.value])
        aviso = f", com {segredos} segredo em claro" if segredos else ""
        if segredos > 1:
            aviso = f", com {segredos} segredos em claro"
        self.registrar(
            f"curl completo de {alvo.get('name')} copiado{aviso}",
            "aviso" if segredos else "info",
            9,
        )

    def _codigo_do_no(self, node: dict) -> None:
        self.open_request(node)
        self.open_codegen()

    def open_codegen(self) -> None:
        node = self.current_node()
        if not node:
            self.statusBar().showMessage("abra um request primeiro", 4000)
            return

        mapa = self.variables_for(node)
        linhagem = self.ancestry_of(node)
        # Pelo proprio envio, com o mapa inteiro e sem rede: olhar so url, params, headers
        # e corpo deixava de fora a Auth, propria ou herdada, e a tela dizia que nao havia
        # segredo com um Bearer {{token}} secreto logo ali.
        teste = engine.prepare(node, scopes.as_plain(mapa), ancestry=linhagem, rede=False)
        tem_segredo = bool(teste.secrets)

        def construir(revelar: bool):
            plano = {}
            for nome, info in mapa.items():
                if info.secret and not revelar:
                    continue  # fica como {{nome}} no codigo, que e o padrao seguro
                plano[nome] = {"value": info.value, "secret": info.secret}
            preparado = engine.prepare(node, plano, ancestry=linhagem, rede=False)
            return preparado.method, preparado.url, preparado.headers, preparado.body

        CodegenDialog(construir, tem_segredo, self).exec()

    def _atalhos_da_janela(self) -> list[tuple[str, str]]:
        """Le o atalho de cada acao direto do menu, em vez de uma lista escrita a mao.

        Existiam tres listas separadas: esta, a paleta de comandos e o texto de cada
        item de menu. Toda vez que um atalho mudava, precisava lembrar de atualizar as
        tres, e pelo menos esta ficava sempre pra tras. Lendo do proprio QMenu, a lista
        nunca desatualiza: e o mesmo QAction que responde ao teclado.
        """
        vistos: set[str] = set()
        linhas: list[tuple[str, str]] = []

        def andar(menu: QMenu) -> None:
            for acao in menu.actions():
                submenu = acao.menu()
                if submenu is not None:
                    andar(submenu)
                    continue
                if acao.isSeparator() or not acao.text():
                    continue
                tecla = acao.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
                if not tecla or tecla in vistos:
                    continue
                vistos.add(tecla)
                rotulo = acao.text().replace("&", "").split("\t")[0]
                linhas.append((tecla, rotulo.lower()))
            return

        for menu_acao in self.menuBar().actions():
            submenu = menu_acao.menu()
            if submenu is not None:
                andar(submenu)

        # Ctrl+1 a Ctrl+9 nascem num laco sem texto de menu, entao nao aparecem na
        # varredura acima. Sao a unica excecao acrescentada a mao.
        linhas.append(("Ctrl+1 ate Ctrl+9", "ir direto para a aba"))
        return linhas

    def show_shortcuts(self) -> None:
        # Em duas colunas: numa so, as trinta e poucas linhas davam uma caixa de 800
        # pixels, e num notebook de 768 o OK ficava fora da tela.
        atalhos = self._atalhos_da_janela()
        metade = (len(atalhos) + 1) // 2

        def celulas(par) -> str:
            if par is None:
                return "<td></td><td></td>"
            tecla, texto = par
            return (
                f"<td><b style='color:{theme.ACCENT};font-family:Consolas'>{tecla}</b></td>"
                f"<td style='color:{theme.TEXT}'>&nbsp;&nbsp;{texto}&nbsp;&nbsp;&nbsp;&nbsp;</td>"
            )

        corpo = "<table cellspacing='5'>" + "".join(
            "<tr>" + celulas(atalhos[i])
            + celulas(atalhos[i + metade] if i + metade < len(atalhos) else None) + "</tr>"
            for i in range(metade)
        ) + "</table>"
        QMessageBox.information(self, "Atalhos de teclado", corpo)


    def show_history_response(self, entry: dict) -> None:
        """Mostra a resposta gravada no mesmo viewer, sem reenviar nada."""
        response = entry.get("response") or {}
        # com aba de ambiente ou de SFTP na frente o painel estava escondido, e clicar
        # numa linha do historico nao mostrava nada
        self.response.setVisible(True)
        ts = entry.get("ts") or ""
        rotulo = f"historico: {ts[8:10]}/{ts[5:7]} {ts[11:16]}" if len(ts) >= 16 else "historico"
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
            "historico",
            [],
            entry.get("requestId"),
            rotulo,
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
        self._ir_para_lateral(0)
        self.tree_panel.select(request_id)
        self.open_request(alvo)

    def _abrir_favorito(self, request_id: str) -> None:
        """Favorito abre sem levar a lateral embora: a lista serve de atalho pro proximo."""
        alvo = next((n for n in self.tree_panel._iter_nodes() if n.get("id") == request_id), None)
        if alvo is None:
            self.statusBar().showMessage("esse request nao existe mais na arvore", 5000)
            return
        self.tree_panel.select(request_id)
        self.open_request(alvo)

    def replay_entry(self, entry_id: str) -> None:
        if not self.history:
            return
        entry = self.history.get(entry_id)
        if not entry:
            # o corpo ja foi expurgado, mas metodo e url continuam no indice
            resumo = self.history.resumo(entry_id)
            if resumo is None:
                return
            from .history_panel import entrada_do_resumo

            entry = entrada_do_resumo(resumo)

        # O envio usa o ambiente ativo de agora. Execucao de ontem em hml, reenviada com
        # prd ativo hoje, ia pra producao sem ninguem perceber.
        gravado_env = entry.get("env") or ""
        atual_env = self.env_combo.currentText() if self.env_combo.currentData() else ""
        if gravado_env and gravado_env != "sem ambiente" and gravado_env != atual_env:
            caixa = QMessageBox(self)
            caixa.setWindowTitle("Enviar de novo")
            caixa.setText(
                f"Essa execucao foi no ambiente {gravado_env} e o ativo agora e "
                f"{atual_env or 'nenhum'}."
            )
            indice_env = self.env_combo.findText(gravado_env)
            trocar = None
            if indice_env > 0:
                trocar = caixa.addButton(
                    f"Trocar pra {gravado_env} e enviar", QMessageBox.ButtonRole.AcceptRole
                )
            ficar = caixa.addButton(
                f"Enviar em {atual_env or 'nenhum ambiente'}", QMessageBox.ButtonRole.DestructiveRole
            )
            cancelar = caixa.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
            caixa.setDefaultButton(cancelar)
            caixa.exec()
            clicado = caixa.clickedButton()
            if clicado is trocar and trocar is not None:
                self.env_combo.setCurrentIndex(indice_env)
            elif clicado is not ficar:
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
        metodo_gravado = (gravado.get("method") or "GET").upper()
        if entry.get("semCorpo") and metodo_gravado not in ("GET", "HEAD"):
            # Do expurgado sobrou metodo e url. Um POST ou PUT sem o corpo e sem os headers
            # de antes nao repete a chamada, manda outra coisa pro mesmo endereco.
            self.statusBar().showMessage(
                f"corpo e headers desta execucao foram apagados depois de {DIAS_CORPO} dias, e "
                f"o request dela saiu da arvore: um {metodo_gravado} so com a url nao seria a "
                "mesma chamada",
                8000,
            )
            return
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
        if entry.get("semCorpo"):
            aviso += ", so com metodo e url: os headers dela ja foram apagados"
        self.statusBar().showMessage(f"reenviando execucao antiga{aviso}")

        task = SendTask(prepared, avulso)
        task.workspace = self.workspace_id
        self._tasks.add(task)
        task.signals.done.connect(
            lambda result, item, p=prepared, t=task: self._finish_replay(result, item, p, t)
        )
        self.pool.start(task)

    def _finish_replay(self, result: dict, node: dict, prepared, task) -> None:
        self._tasks.discard(task)
        if getattr(task, "workspace", self.workspace_id) != self.workspace_id:
            # o workspace trocou no meio da espera: a resposta iria pro historico do outro
            return
        self._on_replay_done(result, node, prepared)

    def _on_replay_done(self, result: dict, node: dict, prepared) -> None:
        self.response.setVisible(True)
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
            f"apagados {conta(resultado['arquivos'], 'dia de corpo', 'dias de corpo')} com mais de "
            f"{DIAS_CORPO} dias e {conta(resultado['registros'], 'resumo', 'resumos')} com mais "
            f"de {DIAS_RESUMO} dias",
            8000,
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


    def mark_dirty(self) -> None:
        # repintar a arvore com o que veio do disco nao e alteracao sua, e se contasse
        # como tal o app gravaria de volta e o proximo ciclo leria isso como mudanca
        if self._recarregando:
            return
        self._falta_gravar = True
        self.statusBar().showMessage("alterado")
        self.save_timer.start()

    def _save_now(self) -> bool:
        """Grava a arvore. Devolve se ela chegou ao disco.

        Falhando, a alteracao continua marcada como pendente: o timer do disco para de
        reler o disco por cima dela, e trocar de workspace ou fechar o app pergunta antes
        de jogar ela fora.
        """
        if not self.workspace_id:
            return True
        self.save_timer.stop()
        try:
            resumo = ws.write_tree(self.workspace_id, self.tree_data, self._assinatura)
            self._assinatura = ws.assinatura(self.workspace_id)
        except (OSError, KeyError) as exc:
            self._falta_gravar = True
            self._erro_gravar = f"{type(exc).__name__}: {exc}"
            self.statusBar().showMessage(f"falha ao salvar: {exc}", 8000)
            return False
        self._falta_gravar = False
        self._erro_gravar = ""

        erro_cofre = resumo.get("erro_cofre")
        if erro_cofre:
            # O storage ja nao apaga nada quando o cofre falha, mas o valor novo so existe
            # na memoria ate o cofre voltar. Calado, isso so aparecia ao reabrir o app. A
            # caixa sai uma vez por erro: o salvar automatico repetiria a mesma a cada tecla.
            self.registrar(f"o cofre nao gravou: {erro_cofre}", "erro", 8)
            if getattr(self, "_cofre_avisado", None) != erro_cofre:
                self._cofre_avisado = erro_cofre
                QMessageBox.warning(
                    self,
                    "Cofre",
                    "O valor das variaveis secretas nao foi gravado no cofre deste "
                    "workspace, e os arquivos de ambiente ficaram como estavam no disco.\n\n"
                    f"{erro_cofre}",
                )

        conflitos = resumo.get("conflitos") or []
        if conflitos:
            quantos = len(conflitos)
            self.statusBar().showMessage(
                f"salvo, mas {conta(quantos, 'arquivo tinha', 'arquivos tinham')} mudado por fora. "
                f"Copia guardada em .conduit/conflitos", 12000
            )
            QMessageBox.warning(
                self,
                "Alteracao vinda de fora",
                f"{quantos} arquivo(s) deste workspace mudaram fora do app desde que ele foi "
                f"aberto, ou nao eram um YAML que ele consegue ler, e acabaram de ser "
                f"sobrescritos.\n\n"
                f"Uma copia do que estava no disco ficou em .conduit/conflitos, dentro da pasta "
                f"do workspace.\n\n"
                + "\n".join(conflitos[:10]),
            )
            return True

        self.registrar("workspace salvo no disco", "info", 2)
        return True

    def _seguir_sem_gravar(self, acao: str) -> bool:
        """Pergunta se segue mesmo com alteracao da arvore que o disco recusou."""
        resposta = QMessageBox.question(
            self,
            acao,
            "As ultimas alteracoes deste workspace nao chegaram ao disco.\n\n"
            f"{self._erro_gravar}\n\n"
            f"{acao} mesmo assim e perder o que nao foi gravado?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return resposta == QMessageBox.StandardButton.Yes

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
        if not self._save_now() and not self._seguir_sem_gravar("Sair"):
            # a falha ja foi mostrada: fechar assim mesmo levava junto a unica copia do
            # que mudou na arvore, e o rascunho das abas nao cobre renomear, mover nem
            # variavel de ambiente
            event.ignore()
            return
        for navegador in list(self.sftp_abas.values()):
            navegador.encerrar()
        self.sftp_abas.clear()
        if self.history:
            self.history.close()
        super().closeEvent(event)


    def _sftp_perfil(self, perfil_id: str):
        from ..core import sftp

        for perfil in sftp.listar_perfis(self.tree_data):
            if perfil.id == perfil_id:
                return perfil
        return None

    def _sftp_known_hosts(self):
        """Fica junto do cofre, e por isso ja esta fora do git pelo .gitignore do
        workspace. Chave de servidor conhecida e do ambiente, nao do contrato."""
        return Path(ws.get_workspace(self.workspace_id)["path"]) / ".secrets" / "known_hosts"

    def sftp_novo(self) -> None:
        from ..core import sftp
        from .sftp_dialog import PerfilDialog

        if not self.workspace_id:
            return
        dialogo = PerfilDialog.pedir(None, self)
        if dialogo is None:
            return
        perfis = sftp.listar_perfis(self.tree_data)
        perfis.append(dialogo.perfil)
        sftp.gravar_perfis(self.tree_data, perfis)
        self._sftp_guardar_segredo(dialogo)
        self.sftp_panel.refresh()
        self.mark_dirty()
        self._ir_para_lateral(4)
        self.statusBar().showMessage(
            f"{dialogo.perfil.nome} cadastrado. Duplo clique na lista conecta.", 6000
        )

    def sftp_editar(self, perfil_id: str) -> None:
        from ..core import sftp
        from .sftp_dialog import PerfilDialog

        perfil = self._sftp_perfil(perfil_id)
        if perfil is None:
            return
        guardada = False
        if self.workspace_id:
            cofre = ws.cofre(self.workspace_id)
            guardada = bool(cofre.get(sftp.CHAVE_SENHA.format(id=perfil_id))
                            or cofre.get(sftp.CHAVE_FRASE.format(id=perfil_id)))
        dialogo = PerfilDialog.pedir(perfil, self, guardada)
        if dialogo is None:
            return
        perfis = [dialogo.perfil if p.id == perfil_id else p for p in sftp.listar_perfis(self.tree_data)]
        sftp.gravar_perfis(self.tree_data, perfis)
        self._sftp_guardar_segredo(dialogo)
        self.sftp_panel.refresh()
        self.mark_dirty()

    def _sftp_guardar_segredo(self, dialogo) -> None:
        from ..core import sftp

        if not self.workspace_id:
            return
        cofre = ws.cofre(self.workspace_id)
        try:
            if dialogo.senha_nova is not None:
                cofre.set(sftp.CHAVE_SENHA.format(id=dialogo.perfil.id), dialogo.senha_nova)
            if dialogo.frase_nova is not None:
                cofre.set(sftp.CHAVE_FRASE.format(id=dialogo.perfil.id), dialogo.frase_nova)
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(f"nao guardei a credencial no cofre: {exc}", 8000)

    def sftp_duplicar(self, perfil_id: str) -> None:
        import copy as copiar

        from ..core import sftp

        perfil = self._sftp_perfil(perfil_id)
        if perfil is None:
            return
        clone = copiar.deepcopy(perfil)
        clone.id = sftp.novo_id()
        clone.nome = f"{perfil.nome} copia"
        perfis = sftp.listar_perfis(self.tree_data)
        perfis.append(clone)
        sftp.gravar_perfis(self.tree_data, perfis)
        # a credencial NAO vem junto: copiar um servidor pra apontar noutro lugar nao e
        # motivo pra espalhar segredo por perfil que ninguem revisou
        self.sftp_panel.refresh()
        self.mark_dirty()
        self.statusBar().showMessage(
            f"{clone.nome} criado. A credencial nao foi copiada, informe de novo.", 7000
        )

    def sftp_excluir(self, perfil_id: str) -> None:
        from ..core import sftp

        perfil = self._sftp_perfil(perfil_id)
        if perfil is None:
            return
        resposta = QMessageBox.question(
            self,
            "Excluir servidor",
            f"Tirar {perfil.nome} da lista?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resposta != QMessageBox.StandardButton.Yes:
            return

        self.sftp_desconectar(perfil_id)
        sftp.gravar_perfis(
            self.tree_data, [p for p in sftp.listar_perfis(self.tree_data) if p.id != perfil_id]
        )
        if self.workspace_id:
            try:
                cofre = ws.cofre(self.workspace_id)
                cofre.set(sftp.CHAVE_SENHA.format(id=perfil_id), "")
                cofre.set(sftp.CHAVE_FRASE.format(id=perfil_id), "")
            except Exception:  # noqa: BLE001
                pass
        self.sftp_panel.refresh()
        self.mark_dirty()
        self.statusBar().showMessage(f"{perfil.nome} saiu da lista", 4000)

    def sftp_desconectar(self, perfil_id: str) -> None:
        navegador = self.sftp_abas.get(perfil_id)
        if navegador is None:
            return
        indice = self.tabs.indexOf(navegador)
        if indice >= 0:
            self.close_tab(indice)
        else:
            navegador.encerrar()
            self.sftp_abas.pop(perfil_id, None)
            self.sftp_panel.marcar_ligado(perfil_id, False)

    def sftp_abrir(self, perfil_id: str, senha: str = "", frase: str = "", confiar: bool = False) -> None:
        """Conecta e abre a aba do navegador. Reentrante: cada pergunta chama de volta.

        Conectar e uma chamada de rede que pode levar segundos e pode fazer duas
        perguntas no meio, a credencial e a chave do servidor. Em vez de um la\u00e7o com
        dialogo dentro da thread, cada resposta chama este mesmo metodo de novo com mais
        um pedaco resolvido. A janela nunca trava e o fluxo continua legivel de cima
        pra baixo.
        """
        from ..core import sftp
        from .sftp_browser import Tarefa
        from .sftp_dialog import ChaveDialog, SenhaDialog

        if not self.workspace_id:
            return

        aberto = self.sftp_abas.get(perfil_id)
        if aberto is not None:
            self.tabs.setCurrentWidget(aberto)
            return
        if perfil_id in self._sftp_conectando:
            # Duplo clique repetido num servidor lento abria duas conexoes. A segunda
            # aba tomava o lugar da primeira no registro, e a primeira ficava orfa: fechar
            # ela nao encerrava a sessao, que seguia viva ate o app fechar.
            self.statusBar().showMessage("a conexao com esse servidor ja esta a caminho", 4000)
            return

        perfil = self._sftp_perfil(perfil_id)
        if perfil is None:
            return
        problema = perfil.problema()
        if problema:
            self.statusBar().showMessage(f"{perfil.nome}: {problema}", 7000)
            self.sftp_editar(perfil_id)
            return

        cofre = ws.cofre(self.workspace_id)
        guardar_senha = guardar_frase = False
        senha_do_cofre = False
        if getattr(self, "_sftp_senha_pendente", False) and senha:
            # a senha nova veio da pergunta depois de a guardada ser recusada
            guardar_senha = True
            self._sftp_senha_pendente = False
        if perfil.auth == "senha" and not senha:
            senha = cofre.get(sftp.CHAVE_SENHA.format(id=perfil.id))
            senha_do_cofre = bool(senha)
            if not senha:
                senha, guardar_senha = SenhaDialog.pedir(perfil, frase=False, parent=self)
                if not senha:
                    return
        if perfil.auth == "chave" and not frase:
            frase = cofre.get(sftp.CHAVE_FRASE.format(id=perfil.id))

        conexao = sftp.Conexao(perfil, self._sftp_known_hosts())
        self.statusBar().showMessage(f"conectando em {perfil.rotulo()}")
        workspace = self.workspace_id

        def deu_certo(_=None) -> None:
            self._sftp_conectando.discard(perfil_id)
            if self.workspace_id != workspace or perfil_id in self.sftp_abas:
                # a conexao chegou depois de trocar de workspace, ou alguem ja abriu a aba
                conexao.fechar()
                return
            if guardar_senha:
                cofre.set(sftp.CHAVE_SENHA.format(id=perfil.id), senha)
            if guardar_frase:
                cofre.set(sftp.CHAVE_FRASE.format(id=perfil.id), frase)
            self._sftp_montar_aba(perfil, conexao)

        def deu_errado(erro) -> None:
            self._sftp_conectando.discard(perfil_id)
            # a senha que veio do cofre nao segue adiante: relida la na volta, ela continua
            # marcada como guardada, e a recusa dela pergunta de novo
            senha_seguinte = "" if senha_do_cofre else senha
            if isinstance(erro, (sftp.ChaveDesconhecida, sftp.ChaveTrocada)):
                if ChaveDialog.confia(erro, self):
                    self.sftp_abrir(perfil_id, senha_seguinte, frase, confiar=True)
                else:
                    self.statusBar().showMessage("conexao cancelada, chave nao aceita", 6000)
                return
            if isinstance(erro, sftp.ErroSftp) and "frase secreta" in str(erro):
                nova, guardar = SenhaDialog.pedir(perfil, frase=True, parent=self)
                if nova:
                    self._sftp_frase_pendente = guardar
                    self.sftp_abrir(perfil_id, senha_seguinte, nova, confiar)
                return
            if senha_do_cofre and isinstance(erro, sftp.ErroSftp) and "recusad" in str(erro):
                # A senha guardada mudou no servidor. Sem perguntar de novo, cada duplo
                # clique repetia a mesma senha recusada. So pergunta em falha de credencial:
                # host fora do ar nao e motivo pra pedir senha.
                self.statusBar().showMessage(f"{perfil.nome}: a senha guardada foi recusada", 6000)
                nova, guardar = SenhaDialog.pedir(perfil, frase=False, parent=self)
                if nova:
                    self._sftp_senha_pendente = guardar
                    self.sftp_abrir(perfil_id, nova, frase, confiar)
                return
            self.statusBar().showMessage(f"{perfil.nome}: {erro}", 9000)
            self.registrar(f"sftp {perfil.rotulo()}: {erro}", "erro", 0)

        if getattr(self, "_sftp_frase_pendente", False) and frase:
            guardar_frase = True
            self._sftp_frase_pendente = False

        tarefa = Tarefa(conexao.abrir, senha=senha, frase=frase, confiar=confiar)
        tarefa.sinais.pronto.connect(deu_certo)
        tarefa.sinais.estourou.connect(deu_errado)
        self._sftp_conectando.add(perfil_id)
        self._tasks.add(tarefa)
        for sinal in (tarefa.sinais.pronto, tarefa.sinais.estourou):
            sinal.connect(lambda *_, t=tarefa: self._tasks.discard(t))
        self.pool.start(tarefa)

    def _sftp_montar_aba(self, perfil, conexao) -> None:
        from .sftp_browser import SftpBrowser

        navegador = SftpBrowser(conexao)
        navegador.recado.connect(lambda texto, ms: self.statusBar().showMessage(texto, ms))
        navegador.caiu.connect(lambda i=perfil.id: self.sftp_panel.marcar_ligado(i, False))
        navegador.reconectar_pedido.connect(
            lambda caminho, i=perfil.id: self._sftp_reconectar(i, caminho)
        )
        self.sftp_abas[perfil.id] = navegador

        indice = self.tabs.addTab(navegador, perfil.nome)
        self.tabs.marcar(navegador, "sftp")
        self.tabs.setTabToolTip(indice, perfil.rotulo())
        self.tabs.setCurrentIndex(indice)
        self._sync_tabs_visibility()
        self.response.setVisible(False)

        self.sftp_panel.marcar_ligado(perfil.id, True)
        navegador.comecar(self._sftp_voltar.pop(perfil.id, ""))
        self.registrar(f"sftp conectado em {perfil.rotulo()}", "ok", 0)
        self.statusBar().showMessage(f"conectado em {perfil.rotulo()}", 5000)

    def _sftp_reconectar(self, perfil_id: str, caminho: str) -> None:
        """Fecha a aba da sessao que caiu e conecta de novo, voltando pra mesma pasta."""
        self._sftp_voltar[perfil_id] = caminho
        self.sftp_desconectar(perfil_id)
        self.sftp_abrir(perfil_id)

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
        """Le o CHANGELOG.md que veio junto. Versao que ninguem le nao serve pra nada."""
        from .. import recursos

        arquivo = recursos.arquivo("CHANGELOG.md")
        if arquivo is None:
            QMessageBox.information(
                self,
                "Novidades",
                "Esta copia do programa veio sem o CHANGELOG.md.\n\n"
                "O historico de versoes fica em github.com/vinibotelho1998/conduit.",
            )
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
