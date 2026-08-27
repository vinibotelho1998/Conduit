"""Painel de historico e janela de detalhe de uma execucao."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHeaderView,
    QStyledItemDelegate,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core.history import History, Query, short_id
from .icons import ALTURA, LARGURA, method_icon, status_icon
from . import theme
from .highlight import CodeHighlighter
from .request_editor import mono
from .response_view import human_bytes

PERIODOS = [("hoje", 1), ("7 dias", 7), ("30 dias", 30), ("tudo", 0)]
STATUS_FILTROS = [
    ("todos", ""),
    ("2xx", "2"),
    ("3xx", "3"),
    ("4xx", "4"),
    ("5xx", "5"),
    ("falha de rede", "erro"),
]


def status_color(status, ok: bool) -> str:
    if not ok:
        return theme.ERR
    if not status:
        return theme.DIM
    return {2: theme.OK, 3: "#61affe", 4: theme.WARN, 5: theme.ERR}.get(status // 100, theme.DIM)


class LinhaHistorico(QStyledItemDelegate):
    """Desenha a execucao em duas linhas: nome em cima, contexto embaixo.

    Quatro colunas nao cabem numa lateral de 300 pixels. So o cabecalho METODO pede 88
    pixels com o padding, e o horario sozinho pede 96. Em duas linhas cabe tudo e ainda
    sobra espaco pro nome inteiro.
    """

    ALTURA = 48

    def paint(self, painter, option, index):
        dados = index.data(Qt.ItemDataRole.UserRole + 1)
        if not dados:
            super().paint(painter, option, index)
            return

        painter.save()
        if option.state & option.state.__class__.State_Selected:
            painter.fillRect(option.rect, QColor(theme.RAISE))
        elif option.state & option.state.__class__.State_MouseOver:
            painter.fillRect(option.rect, QColor(theme.PANEL2))

        area = option.rect.adjusted(8, 4, -8, -4)

        fonte_nome = QFont(option.font)
        fonte_nome.setPointSizeF(max(8.0, option.font.pointSizeF()))
        painter.setFont(fonte_nome)
        painter.setPen(QPen(QColor(theme.TEXT)))
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

        painter.setPen(QPen(QColor(dados["cor_status"])))
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
        tamanho.setHeight(self.ALTURA)
        return tamanho


class HistoryPanel(QWidget):
    replay_requested = Signal(str)          # id da execucao
    open_request_requested = Signal(str)    # id do request na arvore
    load_response_requested = Signal(dict)  # execucao completa

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

        foot = QWidget()
        foot_layout = QHBoxLayout(foot)
        foot_layout.setContentsMargins(8, 4, 8, 8)
        foot_layout.setSpacing(6)

        self.summary = QLabel("")
        self.summary.setObjectName("hint")
        foot_layout.addWidget(self.summary, 1)

        self.btn_detail = QToolButton()
        self.btn_detail.setText("Detalhe")
        self.btn_detail.clicked.connect(self.open_detail)
        self.btn_replay = QToolButton()
        self.btn_replay.setText("Reenviar")
        self.btn_replay.clicked.connect(self._replay)
        for btn in (self.btn_detail, self.btn_replay):
            btn.setStyleSheet(
                f"QToolButton {{ background: {theme.PANEL2}; border: 1px solid {theme.BORDER};"
                f" border-radius: 5px; padding: 4px 10px; }}"
                f"QToolButton:hover {{ border-color: {theme.ACCENT}; }}"
            )
            foot_layout.addWidget(btn)
        root.addWidget(foot)


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

        for index, row in enumerate(rows):
            hora = row["ts"][11:19] if row["ts"] else ""
            dia = row["ts"][5:10] if row["ts"] else ""

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
                    "hora": hora,
                    "status": str(row["status"] or "falhou"),
                    "cor_status": status_color(row["status"], bool(row["ok"])),
                    "resto": "   ".join(partes),
                },
            )
            linha.setToolTip(detalhe)
            self.table.setItem(index, 1, linha)
            self.table.setRowHeight(index, LinhaHistorico.ALTURA)

        stats = self.history.stats()
        self.summary.setText(
            f"{len(rows)} de {stats['total']} execucoes   |   {stats['falhas']} falhas"
        )


    def selected_id(self) -> str | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 1) or self.table.item(rows[0].row(), 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_select(self) -> None:
        entry_id = self.selected_id()
        if not entry_id or not self.history:
            return
        entry = self.history.get(entry_id)
        if entry:
            self.load_response_requested.emit(entry)

    def open_detail(self) -> None:
        entry_id = self.selected_id()
        if not entry_id or not self.history:
            return
        entry = self.history.get(entry_id)
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
        entry = self.history.get(entry_id)
        menu = QMenu(self)
        menu.addAction("Ver detalhe", self.open_detail)
        menu.addAction("Reenviar", self._replay)
        menu.addSeparator()
        menu.addAction("Copiar id", lambda: QGuiApplication.clipboard().setText(entry_id))
        if entry:
            menu.addAction(
                "Copiar url",
                lambda: QGuiApplication.clipboard().setText(entry["request"]["url"]),
            )
            menu.addAction("Copiar como curl", lambda: QGuiApplication.clipboard().setText(to_curl(entry)))
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
    """Comando equivalente, com segredo ainda como {{nome}}."""
    request = entry.get("request") or {}
    parts = [f"curl -X {request.get('method', 'GET')} \"{request.get('url', '')}\""]
    for key, value in request.get("headers") or []:
        parts.append(f'  -H "{key}: {value}"')
    if request.get("body"):
        body = request["body"].replace('"', '\\"')
        parts.append(f'  -d "{body}"')
    return " \\\n".join(parts)


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

        linha = QLabel(f"{request.get('method', '')}  {request.get('url', '')}")
        linha.setFont(mono(9))
        linha.setWordWrap(True)
        head_layout.addWidget(linha)

        cor = status_color(response.get("status"), bool(response.get("ok")))
        resumo = QLabel(
            f"<span style='color:{cor};font-weight:700'>"
            f"{response.get('status') or 'falhou'} {response.get('reason') or ''}</span>"
            f" &nbsp;·&nbsp; {response.get('elapsedMs', 0)} ms"
            f" &nbsp;·&nbsp; {human_bytes(response.get('sizeBytes'))}"
            f" &nbsp;·&nbsp; {entry.get('ts', '')}"
            f" &nbsp;·&nbsp; ambiente {entry.get('env') or 'nenhum'}"
        )
        head_layout.addWidget(resumo)

        caminho = QLabel(f"{entry.get('requestPath') or ''}   id {entry.get('id')}")
        caminho.setObjectName("hint")
        head_layout.addWidget(caminho)

        if entry.get("trace"):
            trace = QLabel("   ".join(f"{k}: {v}" for k, v in entry["trace"].items()))
            trace.setObjectName("hint")
            trace.setWordWrap(True)
            trace.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            head_layout.addWidget(trace)

        if response.get("error"):
            erro = QLabel(response["error"])
            erro.setStyleSheet(f"color: {theme.ERR};")
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

        view = QPlainTextEdit(text)
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
