"""Painel de resposta: status, metricas, corpo, headers, cookies e o que foi enviado."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QPainter,
    QGuiApplication,
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
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import icons, theme
from .highlight import CodeHighlighter, guess_language
from .request_editor import mono
from .widgets import BadgeTabs, so_a_pagina_aberta


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
    """Devolve cor do texto e cor de fundo da pilula."""
    if not ok:
        return theme.ERR, "#3a1620"
    familia = (status or 0) // 100
    return {
        2: (theme.OK, "#12301f"),
        3: ("#61affe", "#12243a"),
        4: (theme.WARN, "#332411"),
        5: (theme.ERR, "#3a1620"),
    }.get(familia, (theme.DIM, theme.RAISE))


def header_value(headers, nome: str) -> str:
    for par in headers or []:
        if str(par[0]).lower() == nome.lower():
            return str(par[1])
    return ""


def flat_button(texto: str, dica: str = "", icone=None) -> QToolButton:
    """Acao da barra da resposta. Com icone, o texto vira so o tooltip."""
    btn = QToolButton()
    if icone is not None:
        btn.setIcon(icone)
        btn.setIconSize(QSize(18, 18))
        btn.setAutoRaise(True)
    else:
        btn.setText(texto)
    btn.setToolTip(dica or texto)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(
        f"QToolButton {{ border: 0; background: transparent; color: {theme.DIM};"
        f" padding: 4px 7px; border-radius: 8px; }}"
        f"QToolButton:hover {{ background: {theme.RAISE}; color: {theme.TEXT}; }}"
        f"QToolButton:checked {{ background: {theme.RAISE}; color: {theme.ACCENT}; }}"
    )
    return btn


class Elastico(QLabel):
    """Rotulo que encolhe ate sumir em vez de empurrar o painel.

    Um QLabel comum entrega o texto inteiro como largura minima. Com uma url de cento e
    poucos caracteres, o lado direito da janela passava a exigir quase dois mil pixels, e
    o splitter tirava essa largura da arvore: bastava chegar uma resposta comprida pra
    coluna da esquerda encolher sozinha.
    """

    def __init__(self, modo=Qt.TextElideMode.ElideRight, parent=None):
        super().__init__(parent)
        self._modo = modo
        self._cheio = ""
        self.setMinimumWidth(1)

    def setText(self, texto: str) -> None:  # noqa: N802
        self._cheio = texto or ""
        self.setToolTip(self._cheio)
        self._encaixar()
        self.updateGeometry()

    def texto_cheio(self) -> str:
        return self._cheio

    def sizeHint(self):  # noqa: N802
        """O que ele gostaria de ter e a largura do texto inteiro.

        Sem isso o rotulo pergunta o tamanho do texto ja cortado, que foi cortado no
        tamanho que ele tinha, e a conta se fecha em zero: ele some da barra.
        """
        tamanho = super().sizeHint()
        tamanho.setWidth(self.fontMetrics().horizontalAdvance(self._cheio) + 2)
        return tamanho

    def minimumSizeHint(self):  # noqa: N802
        tamanho = super().minimumSizeHint()
        tamanho.setWidth(1)
        return tamanho

    def resizeEvent(self, evento):  # noqa: N802
        super().resizeEvent(evento)
        self._encaixar()

    def _encaixar(self) -> None:
        largura = max(0, self.width() - 2)
        super().setText(self.fontMetrics().elidedText(self._cheio, self._modo, largura))


class Pill(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hide()

    def set_status(self, texto: str, cor: str, fundo: str) -> None:
        self.setText(texto)
        self.setStyleSheet(
            f"color: {cor}; background: {fundo}; border: 1px solid {cor}44;"
            f" border-radius: 11px; padding: 3px 12px; font-weight: 700;"
        )
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

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.edit = QPlainTextEdit()
        self.edit.setReadOnly(True)
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
        self.busca.setClearButtonEnabled(True)
        self.busca.textChanged.connect(self._marcar)
        self.busca.returnPressed.connect(lambda: self._pular(1))
        bl.addWidget(self.busca, 1)

        self.contador = QLabel("")
        self.contador.setObjectName("hint")
        bl.addWidget(self.contador)

        anterior = flat_button("‹", "anterior")
        anterior.clicked.connect(lambda: self._pular(-1))
        proximo = flat_button("›", "proximo")
        proximo.clicked.connect(lambda: self._pular(1))
        bl.addWidget(anterior)
        bl.addWidget(proximo)
        layout.addWidget(barra)

        self._ocorrencias: list[int] = []
        self._atual = -1

        fechar = QShortcut(QKeySequence(Qt.Key.Key_Escape), self.busca)
        fechar.setContext(Qt.ShortcutContext.WidgetShortcut)
        fechar.activated.connect(lambda: self.mostrar_busca(False))

    def mostrar_busca(self, ligado: bool) -> None:
        self.barra_busca.setVisible(ligado)
        if ligado:
            self.busca.setFocus()
            self.busca.selectAll()
        else:
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
                selecao.format.setBackground(QColor("#3d5a80"))
                selecoes.append(selecao)
                self._ocorrencias.append(cursor.position())

        self.edit.setExtraSelections(selecoes)
        self.contador.setText(f"{len(self._ocorrencias)}" if termo else "")
        if self._ocorrencias:
            self._pular(1)

    def _pular(self, passo: int) -> None:
        if not self._ocorrencias:
            return
        self._atual = (self._atual + passo) % len(self._ocorrencias)
        cursor = self.edit.textCursor()
        cursor.setPosition(self._ocorrencias[self._atual])
        self.edit.setTextCursor(cursor)
        self.contador.setText(f"{self._atual + 1} de {len(self._ocorrencias)}")


def tabela_pares(rows, cor_chave: str = theme.ACCENT, largura: int = 280) -> QTableWidget:
    tabela = QTableWidget(len(rows or []), 2)
    tabela.setHorizontalHeaderLabels(["Nome", "Valor"])
    tabela.verticalHeader().setVisible(False)
    tabela.setShowGrid(False)
    tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    tabela.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    tabela.setColumnWidth(0, largura)
    tabela.setWordWrap(False)
    for indice, par in enumerate(rows or []):
        chave = QTableWidgetItem(str(par[0]))
        chave.setForeground(QColor(cor_chave))
        chave.setFont(mono(9))
        valor = QTableWidgetItem(str(par[1]))
        valor.setFont(mono(9))
        valor.setToolTip(str(par[1]))
        tabela.setItem(indice, 0, chave)
        tabela.setItem(indice, 1, valor)
        tabela.setRowHeight(indice, 26)
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dados: dict | None = None

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
        self.metricas.setStyleSheet(f"color: {theme.DIM};")
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

        self.btn_busca = flat_button("", "procurar no corpo (Ctrl+F)", icons.icone_lupa())
        self.btn_busca.setCheckable(True)
        self.btn_busca.toggled.connect(self._alternar_busca)
        self.btn_wrap = flat_button("", "quebrar linha", icons.icone_quebra())
        self.btn_wrap.setCheckable(True)
        self.btn_wrap.toggled.connect(self._alternar_wrap)
        self.btn_copiar = flat_button("", "copiar o corpo da resposta", icons.icone_copiar())
        self.btn_copiar.clicked.connect(self._copiar)
        self.btn_salvar = flat_button("", "salvar o corpo em arquivo", icons.icone_baixar())
        self.btn_salvar.clicked.connect(self._salvar)
        self.btn_exemplo = flat_button(
            "", "guardar esta resposta como exemplo do request", icons.icone_marcador()
        )
        self.btn_exemplo.clicked.connect(self.salvar_exemplo.emit)
        for b in (self.btn_busca, self.btn_wrap, self.btn_copiar, self.btn_salvar, self.btn_exemplo):
            cl.addWidget(b)
        root.addWidget(cabeca)

        self.linha = QFrame()
        self.linha.setFixedHeight(1)
        self.linha.setStyleSheet(f"background: {theme.BORDER};")
        root.addWidget(self.linha)

        self.tabs = BadgeTabs()

        self.pretty = BodyView()
        self.raw = BodyView()
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
        root.addWidget(self.tabs, 1)

        atalho = QShortcut(QKeySequence.StandardKey.Find, self)
        atalho.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        atalho.activated.connect(lambda: self.btn_busca.setChecked(True))

        self.clear()

    def _alternar_busca(self, ligado: bool) -> None:
        for corpo in (self.pretty, self.raw):
            corpo.mostrar_busca(ligado)
        if ligado:
            atual = self.tabs.currentWidget()
            if isinstance(atual, BodyView):
                atual.busca.setFocus()


    def clear(self) -> None:
        self.espera.stop()
        self._dados = None
        self.marca.hide()
        self.pill.hide()
        self.metricas.setText("")
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
        self.pill.hide()
        self.marca.hide()
        self.espera.start()
        self.metricas.setText("")
        self.url_final.setText(url)
        self.pretty.edit.setPlaceholderText("aguardando resposta")
        self.pretty.set_text("", "none")

    def _marcar_exemplo(self, nome: str) -> None:
        self.marca.setVisible(bool(nome))
        if not nome:
            return
        self.marca.setText(f"exemplo: {nome}")
        self.marca.setStyleSheet(
            f"color: {theme.ACCENT}; background: rgba(77,163,255,38); border-radius: 8px;"
            f" padding: 1px 9px; font-size: 8pt; font-weight: 600;"
        )

    def show_response(self, data: dict, sent: dict | None = None) -> None:
        self.espera.stop()
        self._dados = data
        self._marcar_exemplo(data.get("exemplo") or "")
        ok = bool(data.get("ok"))
        status = data.get("status")
        cor, fundo = status_tone(status, ok)

        if ok:
            self.pill.set_status(f"{status} {data.get('reason', '')}".strip(), cor, fundo)
        else:
            self.pill.set_status("falhou", cor, fundo)

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
        if miudos:
            self.metricas.setToolTip("\n".join(miudos))

        final = data.get("url") or (sent or {}).get("url") or ""
        self.url_final.setText(final)

        corpo = data.get("body") or ""
        if not ok:
            corpo = data.get("error") or "erro desconhecido"

        idioma = guess_language(corpo, content_type)
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

        if self.tabs.currentIndex() == 2 and not eh_html:
            self.tabs.setCurrentIndex(0)


    def _montar_preview(self, data: dict, eh_html: bool, eh_imagem: bool, corpo: str) -> None:
        indice = self.tabs.indexOf(self.preview_box)
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
            navegador = QTextBrowser()
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
        tabela.verticalHeader().setVisible(False)
        tabela.setShowGrid(False)
        tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tabela.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        tabela.setColumnWidth(0, 190)
        tabela.setColumnWidth(1, 260)
        for indice, (nome, valor, atributos) in enumerate(cookies):
            item_nome = QTableWidgetItem(nome)
            item_nome.setForeground(QColor(theme.ACCENT))
            tabela.setItem(indice, 0, item_nome)
            tabela.setItem(indice, 1, QTableWidgetItem(valor))
            tabela.setItem(indice, 2, QTableWidgetItem(atributos))
            tabela.setRowHeight(indice, 22)
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
            tabela = tabela_pares(headers, theme.WARN, 240)
            tabela.setMaximumHeight(min(200, 30 + 22 * len(headers)))
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

    def _copiar(self) -> None:
        if self._dados:
            QGuiApplication.clipboard().setText(self.pretty.edit.toPlainText())

    def _salvar(self) -> None:
        if not self._dados:
            return
        content_type = header_value(self._dados.get("headers") or [], "content-type")
        sufixo = ".json" if "json" in content_type else ".xml" if "xml" in content_type else ".txt"
        destino, _ = QFileDialog.getSaveFileName(self, "Salvar resposta", f"resposta{sufixo}")
        if destino:
            with open(destino, "w", encoding="utf-8") as arquivo:
                arquivo.write(self.pretty.edit.toPlainText())
