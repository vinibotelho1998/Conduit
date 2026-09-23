"""Painel de historico e janela de detalhe de uma execucao."""

from __future__ import annotations

from datetime import date, timedelta
from html import escape

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QStyledItemDelegate,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core.history import DIAS_CORPO, History, Query, short_id
from .icons import ALTURA, LARGURA, method_icon
from . import theme
from .highlight import CodeHighlighter
from .request_editor import mono
from .response_view import human_bytes
from .numeros import EditorNumerado
from .widgets import Elastico, cabecalho_a_esquerda, conta, dica_de_fora

PERIODOS = [("hoje", 1), ("7 dias", 7), ("30 dias", 30), ("tudo", 0)]
STATUS_FILTROS = [
    ("todos", ""),
    ("2xx", "2"),
    ("3xx", "3"),
    ("4xx", "4"),
    ("5xx", "5"),
    ("falha de rede", "erro"),
]


def quando(ts: str, hoje: date | None = None) -> str:
    """Hora pra hoje, ontem mais a hora, e dia e hora pro resto.

    So a hora fazia uma chamada de ontem as 14:32 parecer igual a uma de hoje no
    mesmo horario, e o dia so aparecia passando o mouse linha por linha.
    """
    if not ts or len(ts) < 16:
        return ts or ""
    hoje = hoje or date.today()
    try:
        dia = date.fromisoformat(ts[:10])
    except ValueError:
        return ts[11:19]
    if dia == hoje:
        return ts[11:19]
    if dia == hoje - timedelta(days=1):
        return f"ontem {ts[11:16]}"
    return f"{ts[8:10]}/{ts[5:7]} {ts[11:16]}"


def entrada_do_resumo(resumo: dict) -> dict:
    """Execucao montada so com o que o indice guardou, pro corpo que ja foi expurgado."""
    return {
        "id": resumo.get("id"),
        "ts": resumo.get("ts"),
        "requestId": resumo.get("request_id"),
        "requestPath": resumo.get("request_path"),
        "name": resumo.get("name"),
        "env": resumo.get("env"),
        "trace": {},
        "semCorpo": True,
        "request": {"method": resumo.get("method"), "url": resumo.get("url"), "headers": []},
        "response": {
            "ok": bool(resumo.get("ok")),
            "status": resumo.get("status"),
            "error": resumo.get("error"),
            "elapsedMs": resumo.get("elapsed_ms"),
            "sizeBytes": resumo.get("size_bytes"),
            "headers": [],
            "body": "",
        },
    }


def status_color(status, ok: bool) -> str:
    if not status:
        # sem status e falha de rede: a pilula da resposta diz falhou em vermelho, e a
        # lista dizia o mesmo falhou em cinza, com cara de coisa neutra
        return theme.DIM if ok else theme.ERR
    return theme.cor_do_status(status, ok)


def _repintar_metodos(tabela) -> None:
    """Refaz a pilula de metodo de cada linha, sem reconsultar o historico nem perder a
    linha escolhida."""
    for linha in range(tabela.rowCount()):
        item = tabela.item(linha, 0)
        if item is not None:
            item.setIcon(method_icon((item.toolTip() or "GET").upper()))
    tabela.viewport().update()


class LinhaHistorico(QStyledItemDelegate):
    """Desenha a execucao em duas linhas: nome em cima, contexto embaixo.

    Quatro colunas nao cabem numa lateral de 300 pixels. So o cabecalho METODO pede 88
    pixels com o padding, e o horario sozinho pede 96. Em duas linhas cabe tudo e ainda
    sobra espaco pro nome inteiro.
    """

    @staticmethod
    def altura() -> int:
        """Duas linhas de texto cabem em quase o dobro da linha de grade comum.

        Metodo e nao constante, senao Densidade nunca alcancava esta lista.
        """
        return int(theme.medida("linha_grade") * 1.6)

    def paint(self, painter, option, index):
        dados = index.data(Qt.ItemDataRole.UserRole + 1)
        if not dados:
            super().paint(painter, option, index)
            return

        painter.save()
        # A mesma cor que a folha de estilo usa na coluna do metodo ao lado. Antes esta
        # coluna pintava por conta propria em RAISE e PANEL2, e a linha selecionada
        # saia com duas cores diferentes coladas uma na outra.
        if option.state & option.state.__class__.State_Selected:
            painter.fillRect(option.rect, QColor(theme.cor("selecao")))
        elif option.state & option.state.__class__.State_MouseOver:
            painter.fillRect(option.rect, QColor(theme.cor("hover")))

        area = option.rect.adjusted(8, 4, -8, -4)

        fonte_nome = QFont(option.font)
        fonte_nome.setPointSizeF(max(8.0, option.font.pointSizeF()))
        painter.setFont(fonte_nome)
        # sem corpo no log, a linha e so resumo: apagada, pra nao prometer o que nao abre
        painter.setPen(QPen(QColor(theme.FAINT if dados.get("sem_corpo") else theme.TEXT)))
        metricas = painter.fontMetrics()
        nome = metricas.elidedText(dados["nome"], Qt.TextElideMode.ElideRight, area.width())
        painter.drawText(area.left(), area.top() + metricas.ascent(), nome)

        # segunda linha: hora, status colorido, tempo e caminho
        fonte_sub = QFont(option.font)
        fonte_sub.setPointSizeF(max(7.0, option.font.pointSizeF() - 1.2))
        painter.setFont(fonte_sub)
        sub = painter.fontMetrics()
        base = area.top() + metricas.height() + sub.ascent() + 1
        x = area.left()

        painter.setPen(QPen(QColor(theme.FAINT)))
        painter.drawText(x, base, dados["hora"])
        x += sub.horizontalAdvance(dados["hora"]) + 8

        # a cor sai da paleta na hora de pintar: guardada no item, a lista continuava com
        # o verde neon do escuro depois de trocar pro claro
        painter.setPen(QPen(QColor(status_color(dados.get("status_bruto"), dados.get("ok", True)))))
        painter.drawText(x, base, dados["status"])
        x += sub.horizontalAdvance(dados["status"]) + 8

        painter.setPen(QPen(QColor(theme.FAINT)))
        resto = dados["resto"]
        if resto:
            resto = sub.elidedText(resto, Qt.TextElideMode.ElideRight, max(0, area.right() - x))
            painter.drawText(x, base, resto)

        painter.restore()

    def sizeHint(self, option, index):
        tamanho = super().sizeHint(option, index)
        tamanho.setHeight(self.altura())
        return tamanho


class HistoryPanel(QWidget):
    replay_requested = Signal(str)          # id da execucao
    open_request_requested = Signal(str)    # id do request na arvore
    load_response_requested = Signal(dict)  # execucao completa
    recado = Signal(str)                    # frase pro rodape da janela

    def __init__(self, parent=None):
        super().__init__(parent)
        self.history: History | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        head = QWidget()
        head_layout = QVBoxLayout(head)
        head_layout.setContentsMargins(8, 8, 8, 6)
        head_layout.setSpacing(6)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar url, nome, id ou trace")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.reload)
        head_layout.addWidget(self.search)

        filters = QHBoxLayout()
        filters.setSpacing(6)
        self.status_filter = QComboBox()
        for label, value in STATUS_FILTROS:
            self.status_filter.addItem(label, value)
        self.status_filter.currentIndexChanged.connect(self.reload)

        self.period_filter = QComboBox()
        for label, value in PERIODOS:
            self.period_filter.addItem(label, value)
        self.period_filter.setCurrentIndex(1)
        self.period_filter.currentIndexChanged.connect(self.reload)

        filters.addWidget(self.status_filter, 1)
        filters.addWidget(self.period_filter, 1)
        head_layout.addLayout(filters)

        root.addWidget(head)

        self.table = QTableWidget(0, 2)
        self.table.horizontalHeader().setVisible(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # sem isso o delegate da coluna do nome nunca recebe State_MouseOver, e o
        # hover que acende na coluna do metodo nunca acendia do lado do nome
        self.table.setMouseTracking(True)
        self.table.setIconSize(QSize(LARGURA, ALTURA))
        cabecalho = self.table.horizontalHeader()
        cabecalho.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, LARGURA + 8)
        cabecalho.setStretchLastSection(True)
        self.table.setItemDelegateForColumn(1, LinhaHistorico(self.table))
        self.table.itemSelectionChanged.connect(self._on_select)
        self.table.itemDoubleClicked.connect(lambda *_: self.open_detail())
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        root.addWidget(self.table, 1)
        # a pilula do metodo e desenho pronto, com a cor do tema dentro
        theme.ao_trocar_widget(self.table, _repintar_metodos)

        # Lista vazia dizia nada: nao dava pra saber se nunca houve envio ou se o filtro
        # escondeu tudo. Favoritos e SFTP ja explicavam o proprio vazio.
        self.vazio = QLabel("")
        self.vazio.setObjectName("hint")
        self.vazio.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.vazio.setWordWrap(True)
        self.vazio.setContentsMargins(16, 24, 16, 24)
        self.vazio.hide()
        root.addWidget(self.vazio, 1)

        # o resumo mora numa linha propria: dividindo a largura com os dois botoes, numa
        # lateral estreita ele virava "0 de 0 ex" e os botoes "D...e" e "R...r"
        # Elastico: com o texto inteiro como largura minima, ele pedia 420 pixels e a
        # lateral de 300 cortava o fim da frase sem reticencias
        self.summary = Elastico()
        self.summary.setObjectName("hint")
        self.summary.setContentsMargins(10, 4, 10, 0)
        root.addWidget(self.summary)

        foot = QWidget()
        foot_layout = QHBoxLayout(foot)
        foot_layout.setContentsMargins(8, 4, 8, 8)
        foot_layout.setSpacing(6)
        foot_layout.addStretch(1)

        self.btn_detail = QToolButton()
        self.btn_detail.setText("Detalhe")
        self.btn_detail.clicked.connect(self.open_detail)
        self.btn_replay = QToolButton()
        self.btn_replay.setText("Reenviar")
        self.btn_replay.clicked.connect(self._replay)
        for btn in (self.btn_detail, self.btn_replay):
            theme.estilizar(
                btn,
                lambda: f"QToolButton {{ background: {theme.PANEL2};"
                f" border: 1px solid {theme.BORDER}; border-radius: 5px; padding: 4px 10px; }}"
                f"QToolButton:hover {{ border-color: {theme.ACCENT}; }}",
            )
            foot_layout.addWidget(btn)
        root.addWidget(foot)
        self._ajustar_botoes()


    def set_history(self, history: History | None) -> None:
        self.history = history
        self.reload()

    def reload(self) -> None:
        self.table.setRowCount(0)
        if not self.history:
            self.summary.setText("")
            return

        # A busca por texto ja cobre o caso de olhar um request so: digitar o nome
        # dele filtra, porque a consulta procura em nome, url, caminho, trace e id.
        spec = Query(
            text=self.search.text(),
            status_class=self.status_filter.currentData() or "",
            since_days=self.period_filter.currentData() or 0,
        )
        rows = self.history.query(spec)
        self.table.setRowCount(len(rows))
        com_corpo = self.history.dias_com_corpo()
        hoje = date.today()

        for index, row in enumerate(rows):
            hora = row["ts"][11:19] if row["ts"] else ""
            dia = row["ts"][5:10] if row["ts"] else ""
            sem_corpo = (row["day"] or "") not in com_corpo

            # coluna da pilula, a mesma da arvore, pra leitura ser igual nos dois lugares
            metodo = QTableWidgetItem()
            metodo.setIcon(method_icon((row["method"] or "GET").upper()))
            metodo.setData(Qt.ItemDataRole.UserRole, row["id"])
            metodo.setToolTip(row["method"] or "")
            self.table.setItem(index, 0, metodo)

            detalhe = f"{row['request_path'] or ''}\n{row['url'] or ''}\n{dia} {hora}   id {short_id(row['id'])}"
            if row["trace"]:
                detalhe += f"\ntrace {row['trace']}"
            if row["error"]:
                detalhe += f"\n{row['error']}"
            if sem_corpo:
                detalhe += f"\ncorpo apagado depois de {DIAS_CORPO} dias, sobrou o resumo"

            partes = []
            if row["elapsed_ms"] is not None:
                partes.append(f"{row['elapsed_ms']} ms")
            if row["size_bytes"]:
                partes.append(human_bytes(row["size_bytes"]))
            if row["request_path"]:
                partes.append(row["request_path"])

            linha = QTableWidgetItem()
            linha.setData(Qt.ItemDataRole.UserRole, row["id"])
            linha.setData(
                Qt.ItemDataRole.UserRole + 1,
                {
                    "nome": row["name"] or row["url"] or "sem nome",
                    "hora": quando(row["ts"] or "", hoje),
                    "sem_corpo": sem_corpo,
                    "status": str(row["status"] or "falhou"),
                    "status_bruto": row["status"],
                    "ok": bool(row["ok"]),
                    "resto": "   ".join(partes),
                },
            )
            linha.setToolTip(dica_de_fora(detalhe))
            self.table.setItem(index, 1, linha)
            self.table.setRowHeight(index, LinhaHistorico.altura())

        stats = self.history.stats()
        self.summary.setText(
            f"{len(rows)} de {conta(stats['total'], 'execucao', 'execucoes')}   |   "
            f"{conta(stats['falhas'] or 0, 'falha', 'falhas')}"
        )
        filtrando = bool(self.search.text().strip()) or bool(self.status_filter.currentData())
        if rows:
            self.vazio.hide()
        elif stats["total"] and (filtrando or self.period_filter.currentData()):
            self.vazio.setText("nada bate com o filtro")
            self.vazio.show()
        else:
            self.vazio.setText("nenhuma execucao ainda\n\nCtrl+Enter envia o request aberto")
            self.vazio.show()
        self.table.setVisible(bool(rows))
        self._ajustar_botoes()

    def _ajustar_botoes(self) -> None:
        tem = self.selected_id() is not None
        self.btn_detail.setEnabled(tem)
        self.btn_replay.setEnabled(tem)


    def selected_id(self) -> str | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 1) or self.table.item(rows[0].row(), 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _entrada(self, entry_id: str) -> dict | None:
        """A execucao inteira do log, ou so o resumo do indice quando o corpo ja foi."""
        entry = self.history.get(entry_id)
        if entry is None:
            resumo = self.history.resumo(entry_id)
            if resumo is not None:
                return entrada_do_resumo(resumo)
        return entry

    def _on_select(self) -> None:
        self._ajustar_botoes()
        entry_id = self.selected_id()
        if not entry_id or not self.history:
            return
        entry = self._entrada(entry_id)
        if entry and entry.get("semCorpo"):
            # clicar mostrava nada e nao dizia nada
            self.recado.emit(
                f"o corpo desta execucao foi apagado depois de {DIAS_CORPO} dias, sobrou "
                "o resumo. Detalhe mostra o que ficou, Reenviar manda de novo"
            )
            return
        if entry:
            self.load_response_requested.emit(entry)

    def open_detail(self) -> None:
        entry_id = self.selected_id()
        if not entry_id or not self.history:
            return
        entry = self._entrada(entry_id)
        if entry:
            HistoryDetail(entry, self).exec()

    def _replay(self) -> None:
        entry_id = self.selected_id()
        if entry_id:
            self.replay_requested.emit(entry_id)

    def _menu(self, pos) -> None:
        entry_id = self.selected_id()
        if not entry_id or not self.history:
            return
        entry = self._entrada(entry_id)
        menu = QMenu(self)
        menu.addAction("Ver detalhe", self.open_detail)
        menu.addAction("Enviar o request de novo", self._replay)
        menu.addSeparator()
        menu.addAction("Copiar id", lambda: QGuiApplication.clipboard().setText(entry_id))
        if entry:
            menu.addAction(
                "Copiar url",
                lambda: QGuiApplication.clipboard().setText(entry["request"]["url"]),
            )
            if not entry.get("semCorpo"):
                menu.addAction(
                    "Copiar como curl", lambda: QGuiApplication.clipboard().setText(to_curl(entry))
                )
            if entry.get("requestId"):
                menu.addAction(
                    "Abrir o request na arvore",
                    lambda: self.open_request_requested.emit(entry["requestId"]),
                )
        menu.addSeparator()
        menu.addAction("Excluir do historico", lambda: self._delete(entry_id))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _delete(self, entry_id: str) -> None:
        if self.history:
            self.history.delete(entry_id)
            self.reload()


def to_curl(entry: dict) -> str:
    """Comando equivalente, com segredo ainda como {{nome}}.

    Pelo mesmo gerador do resto do app, com aspa simples. Entre aspas duplas o terminal
    expandia o que viesse no corpo: um $HOME ou uma crase dentro do JSON gravado saiam
    trocados, e a execucao reproduzida nao era a mesma.
    """
    from ..core import codegen

    request = entry.get("request") or {}
    headers = {str(par[0]): str(par[1]) for par in request.get("headers") or []}
    return codegen.generate(
        "curl", request.get("method") or "GET", request.get("url") or "", headers,
        request.get("body") or None,
    )


class HistoryDetail(QDialog):
    """Janela com a execucao inteira, do jeito que ficou gravada."""

    def __init__(self, entry: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Execucao {short_id(entry['id'])}")
        self.resize(940, 700)

        request = entry.get("request") or {}
        response = entry.get("response") or {}

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        # cabecalho
        header = QFrame()
        header.setObjectName("card")
        head_layout = QVBoxLayout(header)
        head_layout.setContentsMargins(14, 10, 14, 10)
        head_layout.setSpacing(4)

        # Frase de status, trace e erro vem do servidor. Lidos como HTML, um <img> la dentro
        # fazia o Windows abrir o caminho de rede apontado so de abrir o detalhe, ver
        # widgets.dica_de_fora. Por isso texto puro, e o que entra no HTML vai escapado.
        linha = QLabel(f"{request.get('method', '')}  {request.get('url', '')}")
        linha.setTextFormat(Qt.TextFormat.PlainText)
        linha.setFont(mono(9))
        linha.setWordWrap(True)
        head_layout.addWidget(linha)

        cor = status_color(response.get("status"), bool(response.get("ok")))
        resumo = QLabel(
            f"<span style='color:{cor};font-weight:700'>"
            f"{escape(str(response.get('status') or 'falhou'))} {escape(str(response.get('reason') or ''))}</span>"
            f" &nbsp;·&nbsp; {escape(str(response.get('elapsedMs', 0)))} ms"
            f" &nbsp;·&nbsp; {human_bytes(response.get('sizeBytes'))}"
            f" &nbsp;·&nbsp; {escape(str(entry.get('ts', '')))}"
            f" &nbsp;·&nbsp; ambiente {escape(str(entry.get('env') or 'nenhum'))}"
        )
        head_layout.addWidget(resumo)

        if entry.get("semCorpo"):
            aviso_corpo = QLabel(
                f"O corpo desta execucao foi apagado depois de {DIAS_CORPO} dias. Sobrou o "
                "resumo do indice: metodo, url, status e tempo."
            )
            aviso_corpo.setWordWrap(True)
            theme.estilizar(aviso_corpo, lambda: f"color: {theme.WARN};")
            head_layout.addWidget(aviso_corpo)

        caminho = QLabel(f"{entry.get('requestPath') or ''}   id {entry.get('id')}")
        caminho.setTextFormat(Qt.TextFormat.PlainText)
        caminho.setObjectName("hint")
        head_layout.addWidget(caminho)

        if entry.get("trace"):
            trace = QLabel("   ".join(f"{k}: {v}" for k, v in entry["trace"].items()))
            trace.setTextFormat(Qt.TextFormat.PlainText)
            trace.setObjectName("hint")
            trace.setWordWrap(True)
            trace.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            head_layout.addWidget(trace)

        if response.get("error"):
            erro = QLabel(response["error"])
            erro.setTextFormat(Qt.TextFormat.PlainText)
            theme.estilizar(erro, lambda: f"color: {theme.ERR};")
            erro.setWordWrap(True)
            head_layout.addWidget(erro)

        root.addWidget(header)

        # abas
        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.addTab(self._headers_view(request.get("headers") or []), "Headers do request")
        tabs.addTab(self._text_view(request.get("body") or "", request.get("bodyTruncated")), "Body do request")
        tabs.addTab(self._headers_view(response.get("headers") or []), "Headers da resposta")
        tabs.addTab(self._text_view(response.get("body") or "", response.get("bodyTruncated")), "Body da resposta")
        tabs.setCurrentIndex(3)
        root.addWidget(tabs, 1)

        # rodape
        foot = QHBoxLayout()
        aviso = QLabel("Valor de variavel secreta foi gravado como {{nome}}, nunca em claro.")
        aviso.setObjectName("hint")
        foot.addWidget(aviso, 1)

        copy_curl = QPushButton("Copiar como curl")
        copy_curl.clicked.connect(lambda: QGuiApplication.clipboard().setText(to_curl(entry)))
        close = QPushButton("Fechar")
        close.clicked.connect(self.accept)
        foot.addWidget(copy_curl)
        foot.addWidget(close)
        root.addLayout(foot)

    @staticmethod
    def _headers_view(rows: list) -> QWidget:
        table = QTableWidget(len(rows), 2)
        table.setHorizontalHeaderLabels(["Header", "Valor"])
        cabecalho_a_esquerda(table)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        table.setColumnWidth(0, 280)
        for index, pair in enumerate(rows):
            key = QTableWidgetItem(str(pair[0]))
            key.setForeground(QColor(theme.ACCENT))
            table.setItem(index, 0, key)
            table.setItem(index, 1, QTableWidgetItem(str(pair[1])))
        return table

    @staticmethod
    def _text_view(text: str, truncated: bool) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        view = EditorNumerado()
        view.setPlainText(text)
        view.setReadOnly(True)
        view.setFont(mono(9))
        view.setFrameShape(QFrame.Shape.NoFrame)
        stripped = text.lstrip()
        if stripped.startswith(("{", "[")):
            import json

            try:
                view.setPlainText(json.dumps(json.loads(text), indent=2, ensure_ascii=False))
                view._hl = CodeHighlighter(view.document(), "json")
            except (json.JSONDecodeError, ValueError):
                pass
        layout.addWidget(view, 1)

        if truncated:
            aviso = QLabel("corpo cortado no limite de gravacao")
            aviso.setObjectName("hint")
            layout.addWidget(aviso)
        return wrap
