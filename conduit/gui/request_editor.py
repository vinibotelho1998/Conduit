"""Editor de um request: barra de url mais abas de Params, Headers, Body, Auth e Docs."""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qsl, quote_plus

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent, QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core import dinamicas
from . import icons, theme, tokens
from .highlight import CodeHighlighter, VarTooltip
from .examples_panel import ExamplesPanel
from .kvtable import KvTable
from .numeros import EditorNumerado
from .widgets import BadgeTabs, Faixa, so_a_pagina_aberta

METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
BODY_MODES = [("none", "none"), ("json", "json"), ("raw", "raw"), ("form", "form urlencoded")]
BODY_LANGUAGE = {"json": "json", "raw": "none", "form": "none", "none": "none"}
VAR_NAMES = re.compile(r"\{\{\s*([\w.$-]+)\s*\}\}")


def mono(size: int = 10) -> QFont:
    """Fonte de largura fixa, com a cadeia inteira de alternativas.

    Pedir so "Cascadia Code" era pedir uma fonte que a maioria das maquinas nao tem:
    o Qt nao cai na proxima da lista sozinho, ele substitui pela fonte de interface, e
    o app inteiro mostrava url, corpo e tabela de variaveis em Tahoma, que nem largura
    fixa tem. Com setFamilies o Qt percorre a lista ate achar uma instalada.
    """
    font = QFont()
    font.setFamilies([nome.strip() for nome in tokens.FAMILIA_MONO.split(",")])
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFixedPitch(True)
    font.setPointSize(size)
    return font


class UrlEdit(QPlainTextEdit):
    """Campo de uma linha que aceita realce de sintaxe, que QLineEdit nao aceita."""

    returnPressed = Signal()
    curl_colado = Signal(str)

    def insertFromMimeData(self, fonte):  # noqa: N802
        """Colar um curl aqui nao vira url, vira o request inteiro.

        E o gesto mais natural: a pessoa copia o comando do Chrome ou de um ticket e
        cola onde o endereco vai. Transformar isso em texto solto na url seria jogar
        fora tudo que o comando ja diz.
        """
        texto = fonte.text() if fonte.hasText() else ""
        from ..core.curl_import import parece_curl

        if texto and parece_curl(texto):
            self.curl_colado.emit(texto)
            return
        # Endereco copiado de documento ou de e-mail vem com o fim de linha junto. Colado
        # como veio, o campo ganhava uma segunda linha invisivel e o envio falhava com
        # caractere nao imprimivel numa posicao que a tela nao mostrava.
        self.insertPlainText("".join(linha.strip() for linha in texto.splitlines()))

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedHeight(36)
        self.setTabChangesFocus(True)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.returnPressed.emit()
            return
        super().keyPressEvent(event)

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, value: str) -> None:  # noqa: N802
        self.setPlainText(value)


class RequestEditor(QWidget):
    changed = Signal()
    send_requested = Signal()
    curl_pedido = Signal(str)
    pedir_variavel = Signal(str)
    salvar_pedido = Signal()
    cancelar_pedido = Signal()
    # True pede o curl com o segredo em claro, False troca por {{nome}}
    copiar_curl_pedido = Signal(bool)
    copiar_url_pedido = Signal()
    codigo_pedido = Signal()

    def __init__(self, request: dict, parent=None):
        super().__init__(parent)
        self.request = request
        self._variables: dict = {}
        self._loading = True
        self._syncing = False
        self._alvo_aviso = ""
        self._enviando = False
        # Variavel que nao existe nao nasce mais sozinha: cada pausa na digitacao
        # criava um nome no ambiente ativo, e corrigir {{tokn}} pra {{token}} deixava
        # os dois la, as vezes no ambiente de producao. A faixa vermelha tem o criar.

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 0)
        root.setSpacing(7)

        bar = QHBoxLayout()
        bar.setSpacing(8)

        self.method = QComboBox()
        self.method.setObjectName("metodo")
        self.method.setAccessibleName("Metodo HTTP")
        self.method.addItems(METHODS)
        # cada opcao da lista ja aparece na cor do proprio metodo, e na do tema de agora
        for indice in range(len(METHODS)):
            self.method.setItemData(indice, mono(9), Qt.ItemDataRole.FontRole)
        theme.ao_trocar_widget(self.method, self._pintar_lista_de_metodos)
        self._mostrar_metodo(request.get("method"))
        # cabe OPTIONS, o maior da lista; com 112 o GET sobrava num quadro largo enquanto
        # a url, que e o que importa, era a unica coisa que encolhia em janela estreita
        self.method.setFixedWidth(96)
        self.method.setFixedHeight(36)
        self.method.setFont(mono(9))
        self.method.currentTextChanged.connect(self._on_method)

        self.url = UrlEdit(request.get("url") or "")
        self.url.setObjectName("url")
        self.url.setAccessibleName("URL do request")
        self.url.setPlaceholderText("https://exemplo.com/caminho")
        self.url.setFont(mono(9))
        self.url.textChanged.connect(self._on_url)
        self.url.returnPressed.connect(self.send_requested.emit)
        self.url.curl_colado.connect(self.curl_pedido.emit)
        self.url_hl = CodeHighlighter(self.url.document(), "none")
        VarTooltip(self.url, lambda: self._variables)

        # Metodo e endereco dentro do mesmo quadro, como no Postman. Sao duas metades do
        # mesmo dado: em molduras separadas o olho lia dois campos sem relacao, e o
        # seletor de metodo virava mais um controle solto na barra.
        self.grupo_url = QFrame()
        self.grupo_url.setObjectName("barraUrl")
        self.grupo_url.setFixedHeight(38)
        grupo = QHBoxLayout(self.grupo_url)
        grupo.setContentsMargins(0, 0, 0, 0)
        grupo.setSpacing(0)
        self.divisor_url = QFrame()
        self.divisor_url.setObjectName("divisorBarra")
        self.divisor_url.setFixedWidth(1)
        grupo.addWidget(self.method)
        grupo.addWidget(self.divisor_url)
        grupo.addWidget(self.url, 1)
        # o quadro inteiro acende quando o foco cai em qualquer uma das duas metades.
        # Sem isso so a metade focada ganhava borda e a moldura unica se desfazia.
        self.method.installEventFilter(self)
        self.url.installEventFilter(self)
        self._marcar_foco(False)

        # Copiar o request inteiro. Existia so no Ctrl+Shift+C e num item de menu fundo,
        # entao na pratica nao existia: e a acao que mais sai daqui pra um ticket ou pra
        # uma conversa, e agora mora na barra, do lado do endereco.
        self.copy_btn = QToolButton()
        self.copy_btn.setObjectName("acaoBarra")
        self.copy_btn.setText("Copiar")
        self.copy_btn.setFixedHeight(38)
        self.copy_btn.setIconSize(QSize(16, 16))
        self.copy_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.setToolTip("Copiar o request inteiro como curl.  Ctrl+Shift+C")
        # o icone segue o estado do proprio botao, e nao uma variavel do editor: assim
        # trocar de tema no meio do aviso de copiado nao volta pro icone errado
        theme.ao_trocar_widget(
            self.copy_btn,
            lambda b: b.setIcon(
                icons.icone_visto(theme.OK) if b.property("copiado") else icons.icone_copiar()
            ),
        )
        self.copy_btn.clicked.connect(lambda: self._copiar(False))

        # Area de transferencia nao tem retorno visivel nenhum. Sem um sinal aqui, a
        # unica prova de que o clique pegou era o rodape, do outro lado da tela.
        self._timer_copiado = QTimer(self)
        self._timer_copiado.setSingleShot(True)
        self._timer_copiado.setInterval(1500)
        self._timer_copiado.timeout.connect(self._desmarcar_copiado)

        menu = QMenu(self.copy_btn)
        # o texto depois do tab vira a coluna de atalho do menu. Registrar a
        # QKeySequence aqui daria dois donos pro mesmo atalho, e o Qt desliga os dois.
        menu.addAction("Copiar como curl\tCtrl+Shift+C", lambda: self._copiar(False))
        menu.addAction(
            "Copiar curl completo, com segredo em claro", lambda: self._copiar(True)
        )
        menu.addAction("Copiar a url resolvida", lambda: self._copiar(None))
        menu.addSeparator()
        menu.addAction("Gerar codigo\tCtrl+G", self.codigo_pedido.emit)
        self.copy_btn.setMenu(menu)
        self.copy_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        # largura travada na palavra maior: sem isso o botao crescia ao virar "Copiado"
        # e empurrava o Enviar por um segundo e meio, bem depois do clique
        self.copy_btn.setText("Copiado")
        self._largura_copiar = self.copy_btn.sizeHint().width()
        self.copy_btn.setMinimumWidth(self._largura_copiar)
        self.copy_btn.setText("Copiar")
        self._estreito = False

        # Mesmo lugar e mesmo desenho do painel de codigo do Postman, entao quem vem de
        # la acha sem ler a dica.
        self.code_btn = QToolButton()
        self.code_btn.setObjectName("acaoBarra")
        self.code_btn.setProperty("soIcone", True)
        self.code_btn.setFixedSize(38, 38)
        self.code_btn.setIconSize(QSize(18, 18))
        self.code_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.code_btn.setToolTip("Gerar o codigo deste request.  Ctrl+G")
        self.code_btn.setAccessibleName("Gerar codigo do request")
        theme.ao_trocar_widget(self.code_btn, lambda b: b.setIcon(icons.icone_codigo()))
        self.code_btn.clicked.connect(self.codigo_pedido.emit)

        self.send_btn = QPushButton("Enviar")
        self.send_btn.setObjectName("send")
        self.send_btn.setFixedHeight(38)
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        # enquanto envia, o mesmo botao cancela: servidor que aceita e nao responde
        # prendia a aba em Enviando sem saida nenhuma
        self.send_btn.clicked.connect(
            lambda: self.cancelar_pedido.emit() if self._enviando else self.send_requested.emit()
        )
        self.send_btn.setText("Cancelar")
        self.send_btn.setMinimumWidth(self.send_btn.sizeHint().width())
        self.send_btn.setText("Enviar")
        # Esc so vale durante o envio: ligado sempre, ele roubava o Esc da grade e dos
        # campos, que usam a tecla pra desistir da edicao
        self._atalho_cancelar = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._atalho_cancelar.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._atalho_cancelar.setEnabled(False)
        self._atalho_cancelar.activated.connect(self.cancelar_pedido.emit)

        # Salvar fica do lado de Send porque e ali que a mao ja esta. Nasce apagado e
        # so acende quando existe alteracao, entao o botao tambem serve de aviso.
        self.save_btn = QPushButton("Salvar")
        self.save_btn.setObjectName("salvar")
        self.save_btn.setFixedHeight(38)
        self.save_btn.setEnabled(False)
        self.save_btn.setToolTip("Ctrl+S")
        self.save_btn.clicked.connect(self.salvar_pedido.emit)
        # largura de Salvar tambem no Salvo: a primeira tecla na url trocava a palavra e a
        # barra inteira andava uns pixels
        self.save_btn.setMinimumWidth(self.save_btn.sizeHint().width())

        bar.addWidget(self.grupo_url, 1)
        bar.addWidget(self.copy_btn)
        bar.addWidget(self.code_btn)
        bar.addSpacing(2)
        bar.addWidget(self.send_btn)
        bar.addWidget(self.save_btn)
        root.addLayout(bar)

        # faixa de aviso, aparece so quando tem o que dizer
        self.aviso = Faixa()
        self.aviso.acao.connect(lambda: self.pedir_variavel.emit(self._alvo_aviso))
        root.addWidget(self.aviso)

        self.tabs = BadgeTabs()

        request.setdefault("params", [])
        request.setdefault("headers", [])
        self.params = KvTable(request["params"], ("Chave", "Valor"), variaveis=lambda: self._variables)
        self.headers = KvTable(request["headers"], ("Header", "Valor"), variaveis=lambda: self._variables)
        self.params.changed.connect(self._ao_mudar_params)
        self.headers.changed.connect(self._bubble)

        self.tabs.addTab(self.params, "Params")
        self.tabs.addTab(self.headers, "Headers")
        self.tabs.addTab(self._build_body(), "Body")
        self.tabs.addTab(self._build_auth(), "Auth")
        self.tabs.addTab(self._build_docs(), "Docs")

        self.exemplos = ExamplesPanel()
        self.tabs.addTab(self.exemplos, "Exemplos")
        self.tabs.addTab(self._build_ajustes(), "Ajustes")
        so_a_pagina_aberta(self.tabs)
        root.addWidget(self.tabs, 1)

        self._loading = False
        self._on_method(self.method.currentText())
        self._normalizar_query()
        self.refresh_badges()


    def _build_body(self) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(6)

        modes = QHBoxLayout()
        modes.setContentsMargins(6, 0, 6, 0)
        modes.setSpacing(18)
        self.mode_group = QButtonGroup(self)
        body = self.request.setdefault("body", {"mode": "none", "raw": ""})
        for value, label in BODY_MODES:
            radio = QRadioButton(label)
            radio.setProperty("mode", value)
            radio.setChecked(body.get("mode", "none") == value)
            self.mode_group.addButton(radio)
            modes.addWidget(radio)
        self.mode_group.buttonClicked.connect(self._on_mode)

        modes.addStretch(1)
        self.tamanho = QLabel("")
        self.tamanho.setObjectName("hint")
        modes.addWidget(self.tamanho)
        self.prettify = QPushButton("Formatar")
        self.prettify.setObjectName("flat")
        self.prettify.clicked.connect(self._prettify)
        modes.addWidget(self.prettify)
        layout.addLayout(modes)

        self.body = EditorNumerado()
        self.body.setAccessibleName("Corpo do request")
        self.body.setPlainText(body.get("raw") or "")
        self.body.setFont(mono(9))
        self.body.setPlaceholderText("corpo da requisicao")
        self.body.setFrameShape(QFrame.Shape.NoFrame)
        self.body.textChanged.connect(self._on_body)
        self.body_hl = CodeHighlighter(
            self.body.document(), BODY_LANGUAGE.get(body.get("mode", "none"), "none")
        )
        VarTooltip(self.body, lambda: self._variables)
        layout.addWidget(self.body, 1)

        # Com o corpo escondido, sobrava um vazio sem dono e o QVBoxLayout repartia
        # ele entre os itens, o que empurrava a fila de modos pro meio da tela.
        self.sem_corpo = QLabel("este request nao envia corpo")
        self.sem_corpo.setObjectName("hint")
        self.sem_corpo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.sem_corpo, 1)

        self._apply_mode()
        return wrap

    def _build_auth(self) -> QWidget:
        """A aba de auth mora numa area rolavel de proposito.

        QTabWidget pede a altura minima da MAIOR pagina, e nao da pagina aberta. A auth
        tem formulario comprido, entao ela sozinha exigia 333 pixels e o editor inteiro
        virava um bloco de 466: o divisor entre o request e a resposta ja nascia no fim
        do curso e nao andava um pixel.
        """
        from .auth_editor import AuthEditor

        self.auth = AuthEditor(self.request, mostrar_heranca=True)
        self.auth.changed.connect(self._bubble)

        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QFrame.Shape.NoFrame)
        rolagem.setWidget(self.auth)
        # a area rolavel repassa a largura minima de quem esta dentro, e o formulario da
        # auth e largo: sem esse teto ela sozinha exigia mil e cem pixels e voltava a
        # espremer a arvore
        rolagem.setMinimumSize(320, 120)
        return rolagem

    def _build_ajustes(self) -> QWidget:
        """Tempo limite, verificacao de certificado e redirect deste request.

        Existiam no arquivo e no curl colado, mas nao na tela: um curl -k funcionava na
        sessao e, depois de salvar e reabrir, voltava o erro de certificado sem nenhum
        lugar pra ver por que.
        """
        pagina = QWidget()
        layout = QVBoxLayout(pagina)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        linha = QHBoxLayout()
        linha.setSpacing(8)
        rotulo = QLabel("Tempo limite de leitura")
        linha.addWidget(rotulo)
        self.ajuste_tempo = QSpinBox()
        self.ajuste_tempo.setRange(0, 3600)
        self.ajuste_tempo.setSuffix(" s")
        self.ajuste_tempo.setSpecialValueText("sem limite")
        self.ajuste_tempo.setFixedWidth(120)
        # sem setas: a folha do tema nao desenha as do QSpinBox, e ficavam dois quadros vazios
        self.ajuste_tempo.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.ajuste_tempo.valueChanged.connect(self._on_ajustes)
        linha.addWidget(self.ajuste_tempo)
        dica = QLabel("0 espera a resposta o tempo que ela levar")
        dica.setObjectName("hint")
        linha.addWidget(dica)
        linha.addStretch(1)
        layout.addLayout(linha)

        self.ajuste_tls = QCheckBox("Verificar o certificado do servidor")
        self.ajuste_tls.toggled.connect(self._on_ajustes)
        layout.addWidget(self.ajuste_tls)
        self.ajuste_redirect = QCheckBox("Seguir redirecionamento")
        self.ajuste_redirect.toggled.connect(self._on_ajustes)
        layout.addWidget(self.ajuste_redirect)

        nota = QLabel(
            "Desligar a verificacao aceita qualquer certificado, inclusive de quem esta no "
            "meio do caminho. Pra CA interna, prefira Executar, Certificados e CA."
        )
        nota.setObjectName("hint")
        nota.setWordWrap(True)
        layout.addWidget(nota)
        layout.addStretch(1)
        self._carregar_ajustes()
        return pagina

    def _carregar_ajustes(self) -> None:
        ajustes = self.request.get("settings") or {}
        for campo in (self.ajuste_tempo, self.ajuste_tls, self.ajuste_redirect):
            campo.blockSignals(True)
        try:
            tempo = int(float(ajustes.get("timeout") or 0))
        except (TypeError, ValueError):
            tempo = 0
        self.ajuste_tempo.setValue(max(0, min(tempo, 3600)))
        self.ajuste_tls.setChecked(ajustes.get("verifyTls", True) is not False)
        self.ajuste_redirect.setChecked(ajustes.get("followRedirects", True) is not False)
        for campo in (self.ajuste_tempo, self.ajuste_tls, self.ajuste_redirect):
            campo.blockSignals(False)

    def _on_ajustes(self, *_) -> None:
        # so nasce settings no arquivo quando voce mexe aqui: abrir e olhar nao muda nada
        ajustes = self.request.setdefault("settings", {})
        ajustes["timeout"] = self.ajuste_tempo.value()
        ajustes["verifyTls"] = self.ajuste_tls.isChecked()
        ajustes["followRedirects"] = self.ajuste_redirect.isChecked()
        self._atualizar_aviso()
        self._bubble()

    def _build_docs(self) -> QWidget:
        self.docs = QPlainTextEdit(self.request.get("docs") or "")
        self.docs.setPlaceholderText("Anotacoes sobre esse request")
        self.docs.setFrameShape(QFrame.Shape.NoFrame)
        self.docs.textChanged.connect(self._on_docs)
        return self.docs


    def _copiar(self, com_segredo: bool | None) -> None:
        """None pede so a url. True e False escolhem como o segredo sai no curl."""
        if com_segredo is None:
            self.copiar_url_pedido.emit()
        else:
            self.copiar_curl_pedido.emit(com_segredo)
        self.copy_btn.setProperty("copiado", True)
        self.copy_btn.setText("Copiado")
        self.copy_btn.setIcon(icons.icone_visto(theme.OK))
        self._timer_copiado.start()

    def _desmarcar_copiado(self) -> None:
        self.copy_btn.setProperty("copiado", False)
        self.copy_btn.setText("Copiar")
        self.copy_btn.setIcon(icons.icone_copiar())

    def _marcar_foco(self, aceso: bool) -> None:
        """Acende a moldura do quadro de url. Vale pro metodo e pro endereco.

        Passa por propriedade e nao por folha propria porque a cor vem da folha do app,
        que o tema ja remonta sozinha. Repolir e o gesto que faz o Qt reler o seletor.
        """
        if self.grupo_url.property("foco") == aceso:
            return
        self.grupo_url.setProperty("foco", aceso)
        self.grupo_url.style().unpolish(self.grupo_url)
        self.grupo_url.style().polish(self.grupo_url)

    def eventFilter(self, alvo, evento):  # noqa: N802
        if alvo in (self.method, self.url):
            if evento.type() == QEvent.Type.FocusIn:
                self._marcar_foco(True)
            elif evento.type() == QEvent.Type.FocusOut:
                self._marcar_foco(False)
        return super().eventFilter(alvo, evento)

    def _ao_mudar_params(self) -> None:
        self._params_para_url()
        self._atualizar_aviso()
        self._bubble()

    def _bubble(self) -> None:
        if not self._loading:
            self.refresh_badges()
            self.changed.emit()

    def _mostrar_metodo(self, metodo: str | None) -> None:
        """Poe o metodo do request no seletor, mesmo o que nao esta na lista.

        O seletor nao e editavel, e setCurrentText com um texto que ele nao tem nao faz
        nada: um PURGE vindo do Postman ou de um curl, ou um post minusculo escrito a mao
        no YAML, abria como o metodo que estava antes no seletor, e o request passava a
        sair com ele. Maiusculo porque e assim que o envio manda.
        """
        metodo = (metodo or "GET").upper()
        if self.method.findText(metodo) < 0:
            self.method.addItem(metodo)
            self.method.setItemData(self.method.count() - 1, mono(9), Qt.ItemDataRole.FontRole)
        self.method.setCurrentText(metodo)

    def _on_method(self, value: str) -> None:
        self.request["method"] = value
        # Pelo estilizar, e nao por setStyleSheet com a cor pronta: trocar pro tema claro
        # deixava o POST no laranja do escuro, com contraste de 2 sobre o branco
        theme.estilizar(
            self.method,
            lambda metodo=value: "QComboBox#metodo { color: "
            f"{theme.METHOD_COLORS.get(metodo, theme.TEXT)}; font-weight: 700; }}",
        )
        self._bubble()

    @staticmethod
    def _pintar_lista_de_metodos(combo) -> None:
        """A cor de cada opcao da lista, refeita a cada troca de tema.

        Estatico de proposito: o gancho do tema guarda a funcao, e um metodo ligado
        seguraria o editor inteiro na memoria depois de a aba fechar.
        """
        for indice in range(combo.count()):
            combo.setItemData(
                indice,
                QColor(theme.METHOD_COLORS.get(combo.itemText(indice), theme.TEXT)),
                Qt.ItemDataRole.ForegroundRole,
            )

    def _on_url(self) -> None:
        self.request["url"] = self.url.toPlainText()
        self._url_para_params()
        self._atualizar_aviso()
        self._bubble()

    #
    # A url e a aba Params sao duas vistas do mesmo dado, igual ao Postman. Editar
    # um lado atualiza o outro. O motor usa a lista de params como fonte na hora de
    # montar a query, entao nunca sai duplicado.

    @staticmethod
    def _quebrar(url: str) -> tuple[str, str, str]:
        endereco, marca, fragmento = url.partition("#")
        base, _, query = endereco.partition("?")
        return base, query, marca + fragmento

    @staticmethod
    def _codificar_parametro(valor) -> str:
        """Escapa delimitadores sem esconder {{variaveis}} do editor."""
        texto = "" if valor is None else str(valor)
        partes = re.split(r"(\{\{\s*[\w.$-]+\s*\}\})", texto)
        return "".join(p if VAR_NAMES.fullmatch(p) else quote_plus(p) for p in partes)

    def _url_para_params(self) -> None:
        if self._syncing or self._loading:
            return
        _, query, _ = self._quebrar(self.request.get("url") or "")

        novos = []
        for chave, valor in parse_qsl(query, keep_blank_values=True):
            if not chave:
                continue
            novos.append({"key": chave, "value": valor, "enabled": True})

        # preserva o desmarcado que nao esta na url, pra nao sumir com o que o
        # usuario desligou de proposito
        desligados = [p for p in self.request.get("params") or [] if p.get("enabled") is False]
        atuais = self.request.setdefault("params", [])
        if [(p.get("key"), p.get("value")) for p in atuais if p.get("enabled") is not False] == [
            (p["key"], p["value"]) for p in novos
        ]:
            return

        self._syncing = True
        atuais[:] = novos + desligados
        self.params.reload()
        self._syncing = False

    def _params_para_url(self) -> None:
        if self._syncing or self._loading:
            return
        base, _, fragmento = self._quebrar(self.request.get("url") or "")
        pares = [
            f"{self._codificar_parametro(p.get('key'))}={self._codificar_parametro(p.get('value'))}"
            for p in self.request.get("params") or []
            if p.get("enabled") is not False and p.get("key")
        ]
        nova = base + ("?" + "&".join(pares) if pares else "") + fragmento
        if nova == self.request.get("url"):
            return

        self._syncing = True
        self.request["url"] = nova
        posicao = self.url.textCursor().position()
        self.url.setPlainText(nova)
        cursor = self.url.textCursor()
        cursor.setPosition(min(posicao, self.url.document().characterCount() - 1))
        self.url.setTextCursor(cursor)
        self._syncing = False

    def _normalizar_query(self) -> None:
        """Na abertura, faz os dois lados baterem sem inventar mudanca."""
        _, query, _ = self._quebrar(self.request.get("url") or "")
        tem_params = bool([p for p in self.request.get("params") or [] if p.get("key")])
        if query:
            self._url_para_params()
        elif tem_params:
            self._params_para_url()

    def _on_body(self) -> None:
        self.request["body"]["raw"] = self.body.toPlainText()
        self._atualizar_aviso()
        self._bubble()

    def _on_docs(self) -> None:
        self.request["docs"] = self.docs.toPlainText()
        self._bubble()

    def _on_mode(self, button) -> None:
        self.request["body"]["mode"] = button.property("mode")
        self._apply_mode()
        self._bubble()

    def _apply_mode(self) -> None:
        mode = self.request["body"].get("mode", "none")
        self.body.setVisible(mode != "none")
        self.sem_corpo.setVisible(mode == "none")
        self.prettify.setVisible(mode == "json")
        self.tamanho.setVisible(mode != "none")
        self.body_hl.set_language(BODY_LANGUAGE.get(mode, "none"))

    def _prettify(self) -> None:
        try:
            parsed = json.loads(self.body.toPlainText())
        except (json.JSONDecodeError, ValueError):
            self.window().statusBar().showMessage("corpo nao e JSON valido", 4000)
            return
        # Pelo cursor, e nao por setPlainText, que zera a pilha de desfazer: formatar
        # vira um passo so, e Ctrl+Z volta pro texto de antes e pras edicoes anteriores.
        cursor = self.body.textCursor()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText(json.dumps(parsed, indent=2, ensure_ascii=False))
        cursor.endEditBlock()


    def set_variables(self, variables: dict) -> None:
        """Recebe o mapa efetivo, com escopo e origem de cada nome."""
        self._variables = variables or {}
        self.url_hl.set_variables(self._variables)
        self.body_hl.set_variables(self._variables)
        if hasattr(self, "auth"):
            self.auth.set_variables(self._variables)
        self._atualizar_aviso()
        # a grade tambem mostra {{variavel}} colorida, entao precisa saber que mudou
        self.params.repintar()
        self.headers.repintar()

    def set_heranca_auth(self, texto: str) -> None:
        if hasattr(self, "auth"):
            self.auth.set_heranca(texto)

    def used_vars(self) -> list[str]:
        alvos = [self.request.get("url") or ""]
        for lista in (self.request.get("params") or [], self.request.get("headers") or []):
            for item in lista:
                if item.get("enabled") is not False:
                    alvos.append(item.get("value") or "")
        corpo = self.request.get("body") or {}
        if corpo.get("mode") != "none":
            alvos.append(corpo.get("raw") or "")

        nomes: list[str] = []
        for texto in alvos:
            for nome in VAR_NAMES.findall(texto):
                # {{$guid}} e as outras geradas na hora nao entram: elas nao moram em
                # escopo nenhum, entao nao ha o que faltar nem o que preencher. Antes
                # elas caiam aqui, viravam variavel vazia no ambiente e o aviso amarelo
                # ficava aceso pra sempre num request que estava certo.
                if dinamicas.eh_dinamica(nome) and dinamicas.conhecida(nome):
                    continue
                if nome not in nomes:
                    nomes.append(nome)
        return nomes

    def missing_vars(self) -> list[str]:
        return [nome for nome in self.used_vars() if nome not in self._variables]

    def _atualizar_aviso(self) -> None:
        faltando = self.missing_vars()
        if faltando:
            self._alvo_aviso = faltando[0]
            self.aviso.mostrar(
                f"nao existe em nenhum escopo:  {', '.join(faltando)}", "erro", "criar"
            )
            return

        vazias = []
        for nome in self.used_vars():
            info = self._variables.get(nome)
            if info is not None and not info.value:
                vazias.append(nome)
        if vazias:
            self._alvo_aviso = vazias[0]
            self.aviso.mostrar(
                f"definida mas sem valor:  {', '.join(vazias)}", "aviso", "preencher"
            )
        elif (self.request.get("settings") or {}).get("verifyTls", True) is False:
            self._alvo_aviso = ""
            self.aviso.mostrar(
                "este request nao verifica o certificado do servidor, ver a aba Ajustes",
                "aviso",
            )
        else:
            self._alvo_aviso = ""
            self.aviso.esconder()

    def refresh_badges(self) -> None:
        p = self.params.active_count()
        h = self.headers.active_count()
        self.tabs.set_badge(0, str(p) if p else "", theme.ACCENT)
        self.tabs.set_badge(1, str(h) if h else "", theme.ACCENT)

        body = self.request.get("body") or {}
        bruto = body.get("raw") or ""
        tem_corpo = body.get("mode", "none") != "none" and bool(bruto)
        self.tabs.set_badge(2, ponto=tem_corpo, cor=theme.OK)

        docs = self.request.get("docs") or ""
        self.tabs.set_badge(4, ponto=bool(docs.strip()), cor=theme.DIM)

        quantos = len(self.exemplos.exemplos)
        self.tabs.set_badge(5, str(quantos) if quantos else "", theme.OK)

        tipo = (self.request.get("auth") or {}).get("type") or "inherit"
        self.tabs.set_badge(3, ponto=tipo not in ("none", "inherit"), cor=theme.WARN)

        ajustes = self.request.get("settings") or {}
        self.tabs.set_badge(6, ponto=ajustes.get("verifyTls", True) is False, cor=theme.WARN)
        if hasattr(self, "tamanho"):
            tamanho = len(bruto.encode("utf-8"))
            self.tamanho.setText(f"{tamanho} B" if tamanho else "")

    def recarregar_do_modelo(self) -> None:
        """Redesenha os campos a partir do request, depois de uma importacao."""
        self._loading = True
        self._mostrar_metodo(self.request.get("method"))
        self.url.setPlainText(self.request.get("url") or "")

        self.params.rows = self.request.setdefault("params", [])
        self.params.reload()
        self.headers.rows = self.request.setdefault("headers", [])
        self.headers.reload()

        corpo = self.request.setdefault("body", {"mode": "none", "raw": ""})
        for botao in self.mode_group.buttons():
            botao.setChecked(botao.property("mode") == corpo.get("mode", "none"))
        self.body.setPlainText(corpo.get("raw") or "")
        self._apply_mode()
        # sem isto o Docs ficava com o texto antigo depois de reverter ou de recarregar
        # do disco, e a proxima tecla ali gravava o texto velho por cima do modelo
        self.docs.setPlainText(self.request.get("docs") or "")

        if hasattr(self, "auth"):
            self.auth._carregando = True
            self.auth._carregar()
            self.auth._carregando = False
        self._carregar_ajustes()

        self._loading = False
        self._on_method(self.method.currentText())
        self.refresh_badges()
        self._atualizar_aviso()

    def definir_exemplos(self, exemplos: list | None) -> None:
        self.exemplos.definir(exemplos)
        self.refresh_badges()

    def marcar_sujo(self, sujo: bool) -> None:
        self.save_btn.setEnabled(sujo)
        self.save_btn.setText("Salvar" if sujo else "Salvo")
        self.save_btn.setVisible(sujo or not self._estreito)

    def resizeEvent(self, evento):  # noqa: N802
        """Em janela estreita a url e que ganha o espaco.

        Metodo, Copiar, codigo, Enviar e Salvo tem largura fixa, entao numa janela de
        novecentos pixels a url era a unica coisa que encolhia e sobrava {{brasilApi}}.
        Estreito, o Copiar fica so com o icone e o Salvo apagado sai: o ponto da aba ja
        diz se ha alteracao.
        """
        super().resizeEvent(evento)
        estreito = self.width() < 760
        if estreito == self._estreito:
            return
        self._estreito = estreito
        self.copy_btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonIconOnly if estreito
            else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.copy_btn.setMinimumWidth(0 if estreito else self._largura_copiar)
        self.save_btn.setVisible(self.save_btn.isEnabled() or not estreito)

    def focus_url(self) -> None:
        self.url.setFocus()
        self.url.selectAll()

    def set_sending(self, sending: bool) -> None:
        self._enviando = sending
        self._atalho_cancelar.setEnabled(sending)
        self.send_btn.setEnabled(True)
        self.send_btn.setText("Cancelar" if sending else "Enviar")
        self.send_btn.setToolTip(
            "Enviando. Clique ou Esc pra abandonar a espera" if sending else "Ctrl+Enter"
        )
