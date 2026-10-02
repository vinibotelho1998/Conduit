"""Painel de resposta: status, metricas, corpo, headers, cookies e o que foi enviado."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QGuiApplication,
    QImage,
    QKeySequence,
    QPixmap,
    QShortcut,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core import engine
from . import icons, theme, tokens
from .highlight import CodeHighlighter, guess_language
from .numeros import EditorNumerado
from .request_editor import mono
from .widgets import (
    BadgeTabs,
    Elastico,
    Faixa,
    cabecalho_a_esquerda,
    dica_de_fora,
    so_a_pagina_aberta,
)

# Acima disto o corpo aparece como veio, sem reformatar nem colorir: um JSON de 1 MB
# prendia a janela inteira por 4 segundos, e um de 5 MB por quase 20, sem aviso nenhum.
LIMITE_REALCE = 512 * 1024
# Acima disto so o comeco vai pra tela. O corpo inteiro continua no Salvar.
LIMITE_TELA = 2 * 1024 * 1024

# tipo que nao se le como texto: no Pretty ele virava uma parede de lixo
BINARIOS = ("image/", "audio/", "video/", "font/", "application/pdf", "application/zip",
            "application/octet-stream", "application/x-", "application/vnd.ms-excel",
            "application/vnd.openxmlformats")
# Marca de texto que vale mesmo com o prefixo de binario: o token do OAuth vem em
# application/x-www-form-urlencoded, a api da AWS responde application/x-amz-json-1.1 e
# o svg e image/svg+xml. Sem ela, essas respostas viravam o aviso de binario.
TEXTUAIS = ("json", "xml", "text", "javascript", "urlencoded", "yaml", "csv", "html")

# filename="nota.pdf" ou filename*=UTF-8''nota.pdf, do Content-Disposition
RE_NOME_ARQUIVO = re.compile(r"""filename\*?=(?:[\w-]+'[\w-]*')?"?([^";]+)"?""", re.I)


def eh_binario(content_type: str) -> bool:
    tipo = (content_type or "").lower()
    return tipo.startswith(BINARIOS) and not any(marca in tipo for marca in TEXTUAIS)


def human_bytes(n: int | None) -> str:
    if n is None:
        return ""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.2f} MB"


def human_ms(ms: int | None) -> str:
    if ms is None:
        return ""
    if ms < 1000:
        return f"{ms} ms"
    return f"{ms / 1000:.2f} s"


def status_tone(status, ok: bool) -> tuple[str, str]:
    """Cor do texto e do fundo da pilula de status.

    A conta mora em theme.tom_do_status. Existiam quatro copias dela no app, com tres
    azuis diferentes pro 3xx e fundos fixos que nao acompanhavam o tema.
    """
    return theme.tom_do_status(status, ok)


def header_value(headers, nome: str) -> str:
    for par in headers or []:
        if str(par[0]).lower() == nome.lower():
            return str(par[1])
    return ""


def _com_apagado(desenhar) -> QIcon:
    """O icone e, pro botao desligado, o mesmo desenho na cor de controle desligado.

    O cinza que o Qt gera sozinho pro desligado e quase o mesmo tom do icone claro, e
    sem resposta nenhuma os seis botoes pareciam prontos pra uso.
    """
    icone = QIcon(desenhar())
    apagado = desenhar(theme.cor("texto_apagado"))
    for tamanho in apagado.availableSizes():
        icone.addPixmap(apagado.pixmap(tamanho), QIcon.Mode.Disabled)
    return icone


def flat_button(texto: str, dica: str = "", icone=None) -> QToolButton:
    """Acao da barra da resposta. Com icone, o texto vira so o tooltip.

    `icone` e a funcao que desenha, e nao o desenho pronto: o icone carrega a cor do
    tema dentro dele, entao ele precisa ser refeito quando o tema muda.
    """
    btn = QToolButton()
    btn.setObjectName("silencioso")
    if icone is not None:
        btn.setIconSize(QSize(18, 18))
        btn.setAutoRaise(True)
        theme.ao_trocar_widget(btn, lambda alvo, desenhar=icone: alvo.setIcon(_com_apagado(desenhar)))
    else:
        btn.setText(texto)
    btn.setToolTip(dica or texto)
    btn.setAccessibleName(texto or dica)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


class Pill(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # A frase do status e do servidor. Lida como HTML, um "200 <img src=...>" fazia o
        # Windows abrir um caminho de rede so de a resposta chegar, sem clique nenhum.
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.hide()

    def set_status(self, texto: str, status, ok: bool) -> None:
        """Recebe o status, e nao a cor: a cor se calcula na hora de pintar.

        Passar a cor pronta congelava a pilula na paleta de quando a resposta chegou, e
        trocar de tema deixava um retangulo do tema antigo em cima do corpo novo.
        """
        self.setText(texto)

        def folha(s=status, o=ok):
            # `{cor}44` nao e RGBA no Qt, e ARGB: em todo 4xx e 5xx a borda saia numa cor
            # que nao tinha nada a ver com o status. tokens.alfa devolve rgba de verdade.
            cor, fundo = theme.tom_do_status(s, o)
            return (
                f"color: {cor}; background: {fundo};"
                f" border: 1px solid {tokens.alfa(cor, 0.30)};"
                f" border-radius: {tokens.RAIO['medio']}px; padding: 3px 12px;"
                f" font-weight: 700;"
            )

        theme.estilizar(self, folha)
        self.show()


class Espera(QWidget):
    """Ponto que pulsa ao lado da palavra enviando, no lugar da pilula de status."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._passo = 0
        self._timer = QTimer(self)
        self._timer.setInterval(90)
        self._timer.timeout.connect(self._bater)
        self.setFixedHeight(24)
        self.setMinimumWidth(86)
        self.hide()

    def start(self) -> None:
        self._passo = 0
        self.show()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def _bater(self) -> None:
        self._passo = (self._passo + 1) % 40
        self.update()

    def paintEvent(self, evento):  # noqa: N802
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        fase = abs(self._passo - 20) / 20.0
        cor = QColor(theme.ACCENT)
        cor.setAlpha(int(90 + 165 * fase))
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(cor)
        centro = self.height() / 2
        pintor.drawEllipse(QRectF(1.0, centro - 3.5, 7.0, 7.0))
        pintor.setPen(QColor(theme.DIM))
        pintor.drawText(
            QRectF(14.0, 0, self.width() - 14.0, self.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            "enviando",
        )


class BodyView(QWidget):
    """Corpo com realce, busca embutida e quebra de linha opcional."""

    fechar_busca = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.edit = EditorNumerado()
        self.edit.setReadOnly(True)
        self.edit.setAccessibleName("Corpo da resposta")
        self.edit.setFont(mono(9))
        self.edit.setFrameShape(QFrame.Shape.NoFrame)
        self.edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.highlighter = CodeHighlighter(self.edit.document(), "none")
        layout.addWidget(self.edit, 1)

        # A busca nasce fechada e vive atras da lupa da barra de cima. Aberta o tempo
        # todo, ela comia trinta pixels de altura em toda resposta so pra ficar vazia.
        barra = QWidget()
        barra.setFixedHeight(32)
        barra.hide()
        self.barra_busca = barra
        bl = QHBoxLayout(barra)
        bl.setContentsMargins(8, 0, 8, 0)
        bl.setSpacing(6)

        self.busca = QLineEdit()
        self.busca.setPlaceholderText("Procurar no corpo")
        self.busca.setAccessibleName("Procurar no corpo da resposta")
        self.busca.setClearButtonEnabled(True)
        self.busca.textChanged.connect(self._marcar)
        self.busca.returnPressed.connect(lambda: self._pular(1))
        bl.addWidget(self.busca, 1)

        self.contador = QLabel("")
        self.contador.setObjectName("hint")
        bl.addWidget(self.contador)

        self.anterior = flat_button("‹", "Ocorrencia anterior (Shift+F3)")
        self.anterior.setAccessibleName("Ocorrencia anterior")
        self.anterior.clicked.connect(lambda: self._pular(-1))
        self.proximo = flat_button("›", "Proxima ocorrencia (F3)")
        self.proximo.setAccessibleName("Proxima ocorrencia")
        self.proximo.clicked.connect(lambda: self._pular(1))
        bl.addWidget(self.anterior)
        bl.addWidget(self.proximo)
        self.anterior.setEnabled(False)
        self.proximo.setEnabled(False)
        self.btn_fechar_busca = flat_button("", "Fechar busca (Esc)", icons.icone_fechar)
        self.btn_fechar_busca.clicked.connect(self._fechar_busca)
        bl.addWidget(self.btn_fechar_busca)
        layout.addWidget(barra)

        self._ocorrencias: list[tuple[int, int]] = []
        self._atual = -1

        fechar = QShortcut(QKeySequence(Qt.Key.Key_Escape), self.busca)
        fechar.setContext(Qt.ShortcutContext.WidgetShortcut)
        fechar.activated.connect(self._fechar_busca)
        for tecla, passo in (("F3", 1), ("Shift+F3", -1), ("Shift+Return", -1)):
            atalho = QShortcut(QKeySequence(tecla), self)
            atalho.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            atalho.activated.connect(lambda p=passo: self._pular(p))

    def _fechar_busca(self) -> None:
        self.mostrar_busca(False)
        self.fechar_busca.emit()
        self.edit.setFocus()

    def mostrar_busca(self, ligado: bool, focar: bool = True) -> None:
        self.barra_busca.setVisible(ligado)
        if ligado and focar:
            self.busca.setFocus()
            self.busca.selectAll()
        elif not ligado:
            self.busca.clear()

    def set_text(self, texto: str, language: str) -> None:
        self.edit.setPlainText(texto)
        self.highlighter.set_language(language)
        self._marcar()

    def set_wrap(self, ligado: bool) -> None:
        self.edit.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth if ligado else QPlainTextEdit.LineWrapMode.NoWrap
        )

    def _marcar(self) -> None:
        termo = self.busca.text()
        self._ocorrencias = []
        self._atual = -1
        selecoes = []

        if termo:
            documento = self.edit.document()
            cursor = QTextCursor(documento)
            while True:
                cursor = documento.find(termo, cursor, QTextDocument.FindFlag(0))
                if cursor.isNull():
                    break
                # ExtraSelection mora no QTextEdit, nao no QPlainTextEdit: escrito
                # errado, a busca estourava excecao na primeira letra digitada
                selecao = QTextEdit.ExtraSelection()
                selecao.cursor = cursor
                selecao.format.setBackground(QColor(theme.CODIGO["achado"]))
                selecoes.append(selecao)
                self._ocorrencias.append((cursor.selectionStart(), cursor.selectionEnd()))

        self.edit.setExtraSelections(selecoes)
        self.anterior.setEnabled(bool(self._ocorrencias))
        self.proximo.setEnabled(bool(self._ocorrencias))
        self.contador.setText("Nenhuma ocorrencia" if termo and not self._ocorrencias else "")
        if self._ocorrencias:
            self._pular(1)

    def _pular(self, passo: int) -> None:
        if not self._ocorrencias:
            return
        self._atual = (self._atual + passo) % len(self._ocorrencias)
        cursor = self.edit.textCursor()
        inicio, fim = self._ocorrencias[self._atual]
        cursor.setPosition(inicio)
        cursor.setPosition(fim, QTextCursor.MoveMode.KeepAnchor)
        self.edit.setTextCursor(cursor)
        self.edit.ensureCursorVisible()
        self.contador.setText(f"{self._atual + 1} de {len(self._ocorrencias)}")


class Previa(QTextBrowser):
    """Previa do HTML da resposta, sem buscar nada que o HTML aponte.

    O QTextBrowser de fabrica le do disco toda imagem com caminho de arquivo. Numa
    resposta de terceiro, um <img src="file://maquina/pasta/x.png"> fazia o Windows
    abrir esse caminho de rede e entregar a credencial da conta a quem montou a pagina.
    Previa e pra ler o texto; imagem de verdade aparece na aba Imagem, pelo corpo.
    """

    def loadResource(self, tipo, nome):  # noqa: N802
        if nome.scheme().lower() == "data":
            # A imagem embutida no proprio HTML nao sai da resposta, e o documento
            # decodifica o data: sozinho antes de pensar em arquivo. Barrada junto com o
            # resto, a previa perdia o logo e o grafico que a pagina ja trazia dentro.
            return None
        # Imagem volta como um ponto transparente e o resto volta vazio. None ou imagem
        # vazia nao servem: com eles o proprio Qt tenta abrir o arquivo pelo nome.
        if getattr(tipo, "value", tipo) == QTextDocument.ResourceType.ImageResource.value:
            ponto = QImage(1, 1, QImage.Format.Format_ARGB32)
            ponto.fill(Qt.GlobalColor.transparent)
            return ponto
        return QByteArray()


def _pintar_coluna(tabela, coluna: int, papel: str) -> None:
    """Cor de um papel do tema numa coluna inteira, refeita a cada troca de tema.

    A cor pronta ficava dentro de cada celula: trocar de tema deixava os nomes dos
    headers e dos cookies na cor do tema anterior, alguns quase sem contraste.
    """

    def pintar(alvo, coluna=coluna, papel=papel):
        cor = QColor(theme.cor(papel))
        for linha in range(alvo.rowCount()):
            item = alvo.item(linha, coluna)
            if item is not None:
                item.setForeground(cor)

    theme.ao_trocar_widget(tabela, pintar)


def tabela_pares(rows, papel_chave: str = "marca", largura: int = 280) -> QTableWidget:
    tabela = QTableWidget(len(rows or []), 2)
    tabela.setHorizontalHeaderLabels(["Nome", "Valor"])
    cabecalho_a_esquerda(tabela)
    tabela.verticalHeader().setVisible(False)
    tabela.setShowGrid(False)
    tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    tabela.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    tabela.setColumnWidth(0, largura)
    tabela.setWordWrap(False)
    for indice, par in enumerate(rows or []):
        chave = QTableWidgetItem(str(par[0]))
        chave.setFont(mono(9))
        valor = QTableWidgetItem(str(par[1]))
        valor.setFont(mono(9))
        valor.setToolTip(dica_de_fora(str(par[1])))
        tabela.setItem(indice, 0, chave)
        tabela.setItem(indice, 1, valor)
        tabela.setRowHeight(indice, theme.medida("linha_tabela"))
    _pintar_coluna(tabela, 0, papel_chave)
    return tabela


def parse_cookies(headers) -> list[list[str]]:
    """Quebra cada Set-Cookie em nome, valor e atributos."""
    saida = []
    for par in headers or []:
        if str(par[0]).lower() != "set-cookie":
            continue
        bruto = str(par[1])
        partes = [p.strip() for p in bruto.split(";")]
        if not partes:
            continue
        nome, _, valor = partes[0].partition("=")
        atributos = "  ".join(partes[1:])
        saida.append([nome.strip(), valor.strip(), atributos])
    return saida


class ResponseView(QWidget):
    salvar_exemplo = Signal()
    copiar_curl_completo = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dados: dict | None = None
        # o que esta na tela agora, e de onde veio: guardar como exemplo tem que usar isto,
        # e nao a ultima resposta ao vivo do request
        self.exibido: dict | None = None
        self._corpo = ""
        self._raw_pendente: tuple | None = None
        self._grande = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        cabeca = QWidget()
        cabeca.setFixedHeight(42)
        cl = QHBoxLayout(cabeca)
        cl.setContentsMargins(12, 0, 8, 0)
        cl.setSpacing(10)

        self.pill = Pill()
        cl.addWidget(self.pill)

        self.espera = Espera()
        cl.addWidget(self.espera)

        self.metricas = Elastico()
        theme.estilizar(self.metricas, lambda: f"color: {theme.DIM};")
        cl.addWidget(self.metricas)

        # quando o que esta na tela e um exemplo salvo, e nao uma chamada de agora
        self.marca = QLabel("")
        self.marca.hide()
        cl.addWidget(self.marca)

        self.url_final = Elastico(Qt.TextElideMode.ElideMiddle)
        self.url_final.setObjectName("hint")
        self.url_final.setFont(mono(8))
        self.url_final.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        cl.addWidget(self.url_final, 1)

        self.btn_busca = flat_button("", "procurar no corpo (Ctrl+F)", icons.icone_lupa)
        self.btn_busca.setCheckable(True)
        self.btn_busca.toggled.connect(self._alternar_busca)
        self.btn_wrap = flat_button("", "quebrar linha", icons.icone_quebra)
        self.btn_wrap.setCheckable(True)
        self.btn_wrap.toggled.connect(self._alternar_wrap)
        self.btn_copiar = flat_button("", "copiar o corpo da resposta", icons.icone_copiar)
        self.btn_copiar.clicked.connect(self._copiar)
        self.btn_salvar = flat_button("", "salvar o corpo em arquivo", icons.icone_baixar)
        self.btn_salvar.clicked.connect(self._salvar)
        self.btn_exemplo = flat_button(
            "", "guardar esta resposta como exemplo do request", icons.icone_marcador
        )
        self.btn_exemplo.clicked.connect(self.salvar_exemplo.emit)

        # Curl completo, com valor de variavel e credencial em claro, pronto pra colar
        # num terminal. Fica separado do Ctrl+Shift+C, que troca o segredo por {{nome}}:
        # sao usos diferentes, e o seguro continua sendo o do atalho.
        self.btn_curl = flat_button(
            "",
            "copiar curl completo, com variaveis e credenciais resolvidas",
            icons.icone_terminal,
        )
        self.btn_curl.clicked.connect(self.copiar_curl_completo.emit)

        # Um risco separa o que muda a vista, lupa e quebra de linha, do que leva a
        # resposta pra fora do app. Sem ele eram seis icones em fila e o olho tinha que
        # ler os seis pra achar o que queria.
        divisor = QFrame()
        divisor.setFixedWidth(1)
        divisor.setFixedHeight(18)
        theme.estilizar(divisor, lambda: f"background: {theme.BORDER};")

        for b in (self.btn_busca, self.btn_wrap, divisor, self.btn_curl, self.btn_copiar,
                  self.btn_salvar, self.btn_exemplo):
            cl.addWidget(b)
        root.addWidget(cabeca)

        self.linha = QFrame()
        self.linha.setFixedHeight(1)
        theme.estilizar(self.linha, lambda: f"background: {theme.BORDER};")
        root.addWidget(self.linha)

        self.faixa = Faixa()
        self.faixa.acao.connect(self._acao_faixa)
        root.addWidget(self.faixa)

        self.tabs = BadgeTabs()

        self.pretty = BodyView()
        self.raw = BodyView()
        for corpo in (self.pretty, self.raw):
            corpo.fechar_busca.connect(lambda: self.btn_busca.setChecked(False))
        self.preview_box = QWidget()
        self.headers_box = QWidget()
        self.cookies_box = QWidget()
        self.enviado_box = QWidget()

        for widget in (self.preview_box, self.headers_box, self.cookies_box, self.enviado_box):
            QVBoxLayout(widget).setContentsMargins(0, 0, 0, 0)

        self.tabs.addTab(self.pretty, "Pretty")
        self.tabs.addTab(self.raw, "Raw")
        self.tabs.addTab(self.preview_box, "Preview")
        self.tabs.addTab(self.headers_box, "Headers")
        self.tabs.addTab(self.cookies_box, "Cookies")
        self.tabs.addTab(self.enviado_box, "Enviado")
        so_a_pagina_aberta(self.tabs)
        self.tabs.currentChanged.connect(self._preencher_raw)
        root.addWidget(self.tabs, 1)

        atalho = QShortcut(QKeySequence.StandardKey.Find, self)
        atalho.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        atalho.activated.connect(self._abrir_busca)

        self.clear()

    def _alternar_busca(self, ligado: bool) -> None:
        if ligado and not self.btn_busca.isEnabled():
            self.btn_busca.setChecked(False)
            return
        if ligado and not isinstance(self.tabs.currentWidget(), BodyView):
            self.tabs.setCurrentWidget(self.pretty)
        for corpo in (self.pretty, self.raw):
            corpo.mostrar_busca(ligado, focar=False)
        if ligado:
            atual = self.tabs.currentWidget()
            atual.mostrar_busca(True)

    def _abrir_busca(self) -> None:
        if not self.btn_busca.isEnabled():
            return
        if self.btn_busca.isChecked():
            self._alternar_busca(True)
        else:
            self.btn_busca.setChecked(True)

    def _ligar_acoes(self, ligado: bool, exemplo: bool = True) -> None:
        """Sem resposta, copiar, salvar e guardar exemplo nao tem o que fazer.

        Acesos, os icones pareciam prontos pra uso e o clique voltava calado. O de curl
        completo fica sempre ligado: ele depende do request aberto, nao da resposta.
        """
        for botao in (self.btn_copiar, self.btn_salvar, self.btn_busca, self.btn_wrap):
            botao.setEnabled(ligado)
        self.btn_exemplo.setEnabled(ligado and exemplo)
        self.btn_exemplo.setToolTip(
            "guardar esta resposta como exemplo do request" if exemplo or not ligado
            else "isto ja e um exemplo guardado"
        )

    def clear(self) -> None:
        self.espera.stop()
        self._dados = None
        self.exibido = None
        self._corpo = ""
        self._raw_pendente = None
        self._grande = False
        self.faixa.esconder()
        self.btn_busca.setChecked(False)
        self._ligar_acoes(False)
        self.marca.hide()
        self.pill.hide()
        self.metricas.setText("")
        self.metricas.setToolTip("")
        self.url_final.setText("")
        self.pretty.set_text("", "none")
        self.pretty.edit.setPlaceholderText(
            "nenhuma resposta ainda\n\n"
            "Ctrl+Enter envia o request aberto\n"
            "Ctrl+P pula pra qualquer request\n"
            "Ctrl+G gera o codigo equivalente"
        )
        self.raw.set_text("", "none")
        self._trocar(self.preview_box, QWidget())
        self._trocar(self.headers_box, QWidget())
        self._trocar(self.cookies_box, QWidget())
        self._trocar(self.enviado_box, QWidget())
        for indice, nome in enumerate(("Pretty", "Raw", "Preview", "Headers", "Cookies", "Enviado")):
            self.tabs.setTabText(indice, nome)
            self.tabs.set_badge(indice, "")
        self.tabs.setTabEnabled(2, False)

    def show_pending(self, url: str = "") -> None:
        """Enquanto espera, a faixa e a mesma faixa: ponto pulsando e o alvo.

        A pilula colorida de status nao serve aqui. Ela le como resultado, e
        enviando nao e resultado nenhum: fica um retangulo aceso no meio da tela
        dizendo nada.
        """
        # Todo o painel pertence ao envio atual. Limpar so Pretty deixava os headers,
        # cookies, Raw e a previa do envio anterior sob a etiqueta "enviando".
        self.clear()
        self.tabs.setCurrentWidget(self.pretty)
        self.espera.start()
        self.url_final.setText(url)
        self.pretty.edit.setPlaceholderText(
            "aguardando resposta\n\nCancelar no request abandona a espera"
        )

    def _marcar(self, texto: str) -> None:
        """Etiqueta de quando a tela nao mostra uma chamada de agora: exemplo ou historico."""
        self.marca.setVisible(bool(texto))
        if not texto:
            return
        self.marca.setText(texto)
        theme.estilizar(
            self.marca,
            lambda: f"color: {theme.ACCENT}; background: {tokens.alfa(theme.ACCENT, 0.15)};"
            f" border-radius: 8px; padding: 1px 9px; font-size: 8pt; font-weight: 600;",
        )

    def show_response(
        self,
        data: dict,
        sent: dict | None = None,
        origem: str = "vivo",
        ledger: list | None = None,
        dono: str | None = None,
        rotulo: str = "",
    ) -> None:
        """`origem` diz de onde veio o que esta na tela: vivo, exemplo ou historico."""
        self.espera.stop()
        self._dados = data
        if data.get("exemplo"):
            origem = "exemplo"
            rotulo = f"exemplo: {data.get('exemplo')}"
        self.exibido = {
            "dados": data, "enviado": sent, "ledger": list(ledger or []),
            "origem": origem, "dono": dono,
        }
        self._marcar(rotulo)
        self._ligar_acoes(True, exemplo=origem != "exemplo")
        self.faixa.esconder()
        ok = bool(data.get("ok"))
        status = data.get("status")
        if ok:
            self.pill.set_status(f"{status} {data.get('reason', '')}".strip(), status, True)
        else:
            self.pill.set_status("falhou", status, False)

        headers = data.get("headers") or []
        content_type = header_value(headers, "content-type").split(";")[0]
        tamanho_headers = sum(len(str(k)) + len(str(v)) + 4 for k, v in headers)

        # Na barra fica so o que se le de relance. O resto vira tooltip: com tudo
        # escrito lado a lado a faixa virava um paragrafo em cima da resposta.
        pedacos = [human_ms(data.get("elapsedMs"))]
        miudos = []
        if ok:
            pedacos.append(human_bytes(data.get("sizeBytes")))
            if content_type:
                pedacos.append(content_type)
            if tamanho_headers:
                miudos.append(f"headers {human_bytes(tamanho_headers)}")
            servidor = header_value(headers, "server")
            if servidor:
                miudos.append(f"servidor {servidor}")
            atraso = self._defasagem(header_value(headers, "date"))
            if atraso:
                miudos.append(atraso)
        self.metricas.setText("   ·   ".join(p for p in pedacos if p))
        self.metricas.setToolTip(dica_de_fora("\n".join(miudos)) if miudos else "")

        final = data.get("url") or (sent or {}).get("url") or ""
        self.url_final.setText(final)

        corpo = data.get("body") or ""
        if not ok:
            # a frase do que fazer vai na frente, e o texto tecnico fica embaixo como veio
            erro = data.get("error") or "erro desconhecido"
            frase = engine.explicar_erro(erro, final)
            corpo = f"{frase}\n\n{erro}" if frase else erro
        self._corpo = corpo

        tamanho = data.get("sizeBytes") or len(corpo)
        if ok and data.get("content") and eh_binario(content_type):
            aviso = f"resposta binaria de {human_bytes(tamanho)}, {content_type}. Use o salvar em arquivo."
            self.raw.set_text(aviso, "none")
            self.pretty.set_text(aviso, "none")
            self._raw_pendente = None
            self._grande = False
        elif len(corpo) > LIMITE_REALCE:
            # Grande: sem reformatar nem colorir, e o Raw so e preenchido quando alguem
            # abre ele. Acima do limite da tela, so o comeco aparece.
            cortado = len(corpo) > LIMITE_TELA
            trecho = corpo[:LIMITE_TELA] if cortado else corpo
            self._grande = True
            self.pretty.set_text(trecho, "none")
            self._raw_pendente = (trecho, "none")
            self.raw.set_text("", "none")
            if cortado:
                self.faixa.mostrar(
                    f"resposta grande, {human_bytes(tamanho)}: a tela mostra so o comeco e a "
                    "busca procura so nele",
                    "aviso",
                    "salvar em arquivo",
                )
            else:
                self.faixa.mostrar(
                    f"resposta grande, {human_bytes(tamanho)}: aparece sem formatar pra "
                    "janela nao travar",
                    "aviso",
                    "formatar mesmo assim",
                )
            if self.tabs.currentIndex() == 1:
                self._preencher_raw(1)
        else:
            idioma = guess_language(corpo, content_type)
            self._grande = False
            self._raw_pendente = None
            self.raw.set_text(corpo, idioma)
            self.pretty.set_text(self._embelezar(corpo, idioma), idioma)

        eh_html = "html" in content_type or corpo.lstrip().lower().startswith("<!doctype html")
        eh_imagem = content_type.startswith("image/")
        self.tabs.setTabEnabled(2, eh_html or eh_imagem)
        self.tabs.setTabText(2, "Imagem" if eh_imagem else "Preview")
        self._montar_preview(data, eh_html, eh_imagem, corpo)

        self._trocar(self.headers_box, tabela_pares(headers))
        self.tabs.set_badge(3, str(len(headers)) if headers else "", theme.ACCENT)

        cookies = parse_cookies(headers)
        self._trocar(self.cookies_box, self._tabela_cookies(cookies))
        self.tabs.set_badge(4, str(len(cookies)) if cookies else "", theme.WARN)

        self._trocar(self.enviado_box, self._painel_enviado(sent))

        if self.tabs.currentIndex() == 2 and not (eh_html or eh_imagem):
            self.tabs.setCurrentIndex(0)


    def _montar_preview(self, data: dict, eh_html: bool, eh_imagem: bool, corpo: str) -> None:
        if eh_imagem and data.get("content"):
            imagem = QPixmap()
            if imagem.loadFromData(data["content"]):
                rotulo = QLabel()
                rotulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
                if imagem.width() > 900 or imagem.height() > 600:
                    imagem = imagem.scaled(
                        900, 600, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                    )
                rotulo.setPixmap(imagem)
                rotulo.setToolTip(f"{imagem.width()} por {imagem.height()} pixels")
                self._trocar(self.preview_box, rotulo)
                return
        if eh_html:
            navegador = Previa()
            navegador.setOpenExternalLinks(False)
            navegador.setFrameShape(QFrame.Shape.NoFrame)
            navegador.setHtml(corpo)
            self._trocar(self.preview_box, navegador)
            return
        vazio = QLabel("esta resposta nao tem previa, so HTML e imagem tem")
        vazio.setObjectName("hint")
        vazio.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._trocar(self.preview_box, vazio)

    @staticmethod
    def _defasagem(data_header: str) -> str:
        if not data_header:
            return ""
        try:
            momento = parsedate_to_datetime(data_header)
        except (TypeError, ValueError):
            return ""
        if momento.tzinfo is None:
            momento = momento.replace(tzinfo=timezone.utc)
        delta = abs((datetime.now(timezone.utc) - momento).total_seconds())
        if delta < 90:
            return ""
        return f"relogio do servidor {int(delta)} s fora"

    @staticmethod
    def _embelezar(corpo: str, idioma: str) -> str:
        if idioma == "json":
            try:
                return json.dumps(json.loads(corpo), indent=2, ensure_ascii=False)
            except (json.JSONDecodeError, ValueError):
                return corpo
        return corpo

    def _trocar(self, caixa: QWidget, novo: QWidget) -> None:
        layout = caixa.layout()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        layout.addWidget(novo)

    def _tabela_cookies(self, cookies) -> QWidget:
        if not cookies:
            vazio = QLabel("a resposta nao mandou cookie")
            vazio.setObjectName("hint")
            vazio.setAlignment(Qt.AlignmentFlag.AlignCenter)
            return vazio
        tabela = QTableWidget(len(cookies), 3)
        tabela.setHorizontalHeaderLabels(["Cookie", "Valor", "Atributos"])
        cabecalho_a_esquerda(tabela)
        tabela.verticalHeader().setVisible(False)
        tabela.setShowGrid(False)
        tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tabela.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        tabela.setColumnWidth(0, 190)
        tabela.setColumnWidth(1, 260)
        for indice, (nome, valor, atributos) in enumerate(cookies):
            tabela.setItem(indice, 0, QTableWidgetItem(nome))
            tabela.setItem(indice, 1, QTableWidgetItem(valor))
            tabela.setItem(indice, 2, QTableWidgetItem(atributos))
            tabela.setRowHeight(indice, theme.medida("linha_tabela"))
        _pintar_coluna(tabela, 0, "marca")
        return tabela

    def _painel_enviado(self, sent: dict | None) -> QWidget:
        if not sent:
            vazio = QLabel("sem registro do que foi enviado")
            vazio.setObjectName("hint")
            vazio.setAlignment(Qt.AlignmentFlag.AlignCenter)
            return vazio

        caixa = QWidget()
        layout = QVBoxLayout(caixa)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        linha = QLabel(f"{sent.get('method', '')}  {sent.get('url', '')}")
        linha.setFont(mono(9))
        linha.setWordWrap(True)
        linha.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(linha)

        headers = [[k, v] for k, v in (sent.get("headers") or {}).items()]
        if headers:
            rotulo = QLabel(f"HEADERS ENVIADOS  {len(headers)}")
            rotulo.setObjectName("sectionTitle")
            layout.addWidget(rotulo)
            tabela = tabela_pares(headers, "aviso", 240)
            # pela altura de verdade: a conta de 22 por linha nao via o cabecalho nem a
            # linha de 26 do confortavel, e o unico header saia cortado ao meio
            tabela.ensurePolished()
            tabela.horizontalHeader().ensurePolished()
            altura = (
                tabela.horizontalHeader().sizeHint().height()
                + sum(tabela.rowHeight(i) for i in range(tabela.rowCount()))
                + 2 * tabela.frameWidth() + 2
            )
            tabela.setMaximumHeight(min(200, altura))
            # com o painel baixo, quem encolhe e o corpo, que tem rolagem propria; a
            # tabela nao desce de uma linha inteira
            primeira = tabela.rowHeight(0) if tabela.rowCount() else 0
            tabela.setMinimumHeight(min(altura, tabela.horizontalHeader().sizeHint().height()
                                        + primeira + 2 * tabela.frameWidth() + 2))
            layout.addWidget(tabela)

        corpo = sent.get("body") or ""
        if corpo:
            rotulo = QLabel(f"CORPO ENVIADO  {human_bytes(len(corpo.encode('utf-8')))}")
            rotulo.setObjectName("sectionTitle")
            layout.addWidget(rotulo)
            visao = BodyView()
            visao.set_text(self._embelezar(corpo, guess_language(corpo)), guess_language(corpo))
            layout.addWidget(visao, 1)
        else:
            layout.addStretch(1)

        aviso = QLabel("Valor de variavel secreta aparece aqui como veio do cofre, e nao vai pro historico em claro.")
        aviso.setObjectName("hint")
        aviso.setWordWrap(True)
        layout.addWidget(aviso)
        return caixa


    def _alternar_wrap(self, ligado: bool) -> None:
        self.pretty.set_wrap(ligado)
        self.raw.set_wrap(ligado)

    def _preencher_raw(self, indice: int) -> None:
        if indice == 1 and self._raw_pendente is not None:
            texto, idioma = self._raw_pendente
            self._raw_pendente = None
            self.raw.set_text(texto, idioma)

    def _acao_faixa(self) -> None:
        if len(self._corpo) > LIMITE_TELA:
            self._salvar()
            return
        # o pedido e explicito: a espera agora e escolha de quem clicou
        tipo = header_value((self._dados or {}).get("headers") or [], "content-type").split(";")[0]
        idioma = guess_language(self._corpo, tipo)
        self.pretty.set_text(self._embelezar(self._corpo, idioma), idioma)
        self.faixa.esconder()

    def _texto_visivel(self) -> str:
        """O que a aba aberta mostra. Na Raw e o corpo como veio, e nao o reindentado."""
        if self.tabs.currentIndex() == 1:
            self._preencher_raw(1)
            return self.raw.edit.toPlainText()
        return self.pretty.edit.toPlainText()

    def _piscar(self, botao, desenhar) -> None:
        """O mesmo visto verde do Copiar da barra do request, por um segundo e meio."""
        botao.setIcon(icons.icone_visto(theme.OK))
        QTimer.singleShot(1500, lambda b=botao, d=desenhar: b.setIcon(_com_apagado(d)))

    def _recado(self, texto: str, ms: int = 4000) -> None:
        janela = self.window()
        if hasattr(janela, "statusBar"):
            janela.statusBar().showMessage(texto, ms)

    def _copiar(self) -> None:
        if self._dados:
            QGuiApplication.clipboard().setText(self._texto_visivel())
            self._piscar(self.btn_copiar, icons.icone_copiar)
            self._recado("corpo da resposta copiado")

    @staticmethod
    def _nome_sugerido(headers) -> str:
        """O nome do Content-Disposition, quando o servidor manda um."""
        from urllib.parse import unquote

        achado = RE_NOME_ARQUIVO.search(header_value(headers, "content-disposition"))
        if not achado:
            return ""
        return Path(unquote(achado.group(1)).strip()).name

    # Sufixo pelo content-type. Sem isso toda resposta saia .txt, e imagem ou pdf
    # gravados como texto viravam arquivo ilegivel.
    SUFIXOS = {
        "application/json": ".json", "text/json": ".json",
        "application/xml": ".xml", "text/xml": ".xml",
        "text/html": ".html", "text/csv": ".csv", "text/plain": ".txt",
        "application/pdf": ".pdf", "application/zip": ".zip",
        "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
        "image/webp": ".webp", "image/svg+xml": ".svg",
    }

    def _salvar(self) -> None:
        if not self._dados:
            return
        tipo = header_value(self._dados.get("headers") or [], "content-type").split(";")[0].strip().lower()
        sufixo = self.SUFIXOS.get(tipo)
        if sufixo is None:
            sufixo = ".json" if "json" in tipo else ".xml" if "xml" in tipo else ".txt"

        bruto = self._dados.get("content")
        binario = bool(bruto) and not tipo.startswith("text/") and "json" not in tipo and "xml" not in tipo
        # Os bytes como vieram, a nao ser que a aba aberta seja a Pretty de um texto: ai
        # vai o que ela mostra, a versao formatada. Resposta cortada na tela sai inteira.
        como_veio = binario or self.tabs.currentIndex() != 0 or len(self._corpo) > LIMITE_TELA

        nome = self._nome_sugerido(self._dados.get("headers") or []) or f"resposta{sufixo}"
        destino, _ = QFileDialog.getSaveFileName(self, "Salvar resposta", nome)
        if not destino:
            return
        try:
            if como_veio and bruto:
                Path(destino).write_bytes(bruto)
            elif como_veio:
                Path(destino).write_text(self._corpo, encoding="utf-8")
            else:
                Path(destino).write_text(self.pretty.edit.toPlainText(), encoding="utf-8")
        except OSError as exc:
            self._recado(f"nao consegui gravar: {exc}", 6000)
            return
        self._piscar(self.btn_salvar, icons.icone_baixar)
        self._recado(f"resposta salva em {destino}", 6000)
