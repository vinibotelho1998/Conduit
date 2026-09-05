"""Grade de chave e valor, no comportamento do Postman: linha fantasma que vira linha real."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QWidget,
)

from . import icons, theme
from .controles import BotaoApagar, Marcador
from .highlight import VAR_PY, cor_da_variavel


def _centrado(widget: QWidget) -> QWidget:
    """Poe o controle no meio da celula sem pintar fundo por cima da linha escolhida."""
    wrap = QWidget()
    wrap.setStyleSheet("background: transparent;")
    hl = QHBoxLayout(wrap)
    hl.setContentsMargins(0, 0, 0, 0)
    hl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    hl.addWidget(widget)
    return wrap

class DicaDelegate(QStyledItemDelegate):
    """Pinta a dica da linha vazia e as variaveis da celula.

    A dica nao vira texto de verdade porque isso obrigaria o usuario a apagar antes de
    digitar. Pintando por cima, ela some sozinha no primeiro caractere.

    A variavel {{assim}} sai na cor do estado dela, a mesma cor da url e do corpo: azul
    quando resolve, roxo quando e secreta e vermelho quando nenhum escopo define. Sem
    isso a grade era o unico lugar do app onde variavel parecia texto comum.

    Enquanto pinta, guarda onde cada token ficou. E dai que o cartao do mouse sabe em
    que ponto ancorar, sem ter que refazer a conta de largura de fonte.
    """

    def __init__(self, dicas: dict[int, str], parent=None, variaveis=None):
        super().__init__(parent)
        self.dicas = dicas
        self.variaveis = variaveis  # callable que devolve o mapa, ou None
        self.tokens: dict = {}

    def _mapa(self) -> dict:
        return (self.variaveis() if self.variaveis else None) or {}

    def paint(self, painter, option, index):
        texto = index.data() or ""
        chave = (index.row(), index.column())
        if not texto or not VAR_PY.search(texto):
            self.tokens.pop(chave, None)
            super().paint(painter, option, index)
            self._pintar_dica(painter, option, index)
            return

        opcao = QStyleOptionViewItem(option)
        self.initStyleOption(opcao, index)
        rotulo = opcao.text
        opcao.text = ""
        estilo = opcao.widget.style() if opcao.widget else QApplication.style()
        estilo.drawControl(QStyle.ControlElement.CE_ItemViewItem, opcao, painter, opcao.widget)

        area = estilo.subElementRect(
            QStyle.SubElement.SE_ItemViewItemText, opcao, opcao.widget
        )
        painter.save()
        painter.setFont(opcao.font)
        metrica = painter.fontMetrics()
        negrito = QFont(opcao.font)
        negrito.setWeight(QFont.Weight.DemiBold)

        mapa = self._mapa()
        x = area.left() + 1
        limite = area.right()
        marcas = []
        posicao = 0
        for achado in VAR_PY.finditer(rotulo):
            for pedaco, cor, fonte in (
                (rotulo[posicao:achado.start()], theme.TEXT, opcao.font),
                (achado.group(0), cor_da_variavel(mapa.get(achado.group(1))), negrito),
            ):
                if not pedaco:
                    continue
                painter.setFont(fonte)
                painter.setPen(QColor(cor))
                largura = painter.fontMetrics().horizontalAdvance(pedaco)
                if x > limite:
                    break
                painter.drawText(
                    x, area.top(), min(largura, limite - x), area.height(),
                    int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                    pedaco,
                )
                if fonte is negrito:
                    marcas.append((achado.group(1), x, x + largura))
                x += largura
            posicao = achado.end()

        resto = rotulo[posicao:]
        if resto and x <= limite:
            painter.setFont(opcao.font)
            painter.setPen(QColor(theme.TEXT))
            painter.drawText(
                x, area.top(), limite - x, area.height(),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                metrica.elidedText(resto, Qt.TextElideMode.ElideRight, max(1, limite - x)),
            )
        painter.restore()
        self.tokens[chave] = marcas

    def _pintar_dica(self, painter, option, index):
        if index.data() or not index.data(Qt.ItemDataRole.UserRole):
            return
        dica = self.dicas.get(index.column())
        if not dica:
            return
        painter.save()
        painter.setPen(QColor(theme.FAINT))
        painter.drawText(
            option.rect.adjusted(8, 0, -4, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            dica,
        )
        painter.restore()


class VarHover(QObject):
    """Cartao da variavel quando o mouse para em cima de um {{token}} da grade."""

    def __init__(self, tabela: QTableWidget, delegate: DicaDelegate, variaveis):
        super().__init__(tabela)
        self.tabela = tabela
        self.delegate = delegate
        self.variaveis = variaveis
        self._atual = None
        tabela.setMouseTracking(True)
        tabela.viewport().setMouseTracking(True)
        tabela.viewport().installEventFilter(self)

    def eventFilter(self, obj, evento):  # noqa: N802
        tipo = evento.type()
        if tipo == QEvent.Type.MouseMove:
            self._talvez_mostrar(evento)
        elif tipo in (QEvent.Type.Leave, QEvent.Type.Wheel, QEvent.Type.FocusOut):
            self._esconder()
        return False

    def _esconder(self) -> None:
        from .var_popup import VarPopup

        self._atual = None
        VarPopup.esconder()

    def _talvez_mostrar(self, evento) -> None:
        from .var_popup import VarPopup

        ponto = evento.position().toPoint()
        index = self.tabela.indexAt(ponto)
        if not index.isValid():
            self._esconder()
            return

        marcas = self.delegate.tokens.get((index.row(), index.column()))
        if not marcas:
            self._esconder()
            return

        for nome, inicio, fim in marcas:
            if inicio <= ponto.x() <= fim:
                if nome == self._atual:
                    return
                self._atual = nome
                info = ((self.variaveis() if self.variaveis else None) or {}).get(nome)
                popup = VarPopup.instancia()
                popup.preencher(nome, info)
                area = self.tabela.visualRect(index)
                popup.mostrar_em(
                    self.tabela.viewport().mapToGlobal(QPoint(int(inicio), area.bottom() + 4))
                )
                return
        self._esconder()


class KvTable(QWidget):
    """Grade de pares. Com with_secret, ganha a coluna de marcar valor como secreto."""

    changed = Signal()

    def focar(self, nome: str) -> bool:
        """Poe o cursor no valor da linha com esse nome, ja em modo de edicao."""
        for linha in range(self.table.rowCount()):
            item = self.table.item(linha, 1)
            if item is not None and (item.text() or "").strip() == nome:
                alvo = self.table.item(linha, 2)
                if alvo is None:
                    return False
                self.table.setCurrentCell(linha, 2)
                self.table.scrollToItem(alvo)
                self.table.editItem(alvo)
                self.setFocus()
                return True
        return False

    def __init__(
        self,
        rows: list[dict],
        labels: tuple[str, str],
        parent=None,
        with_secret: bool = False,
        variaveis=None,
    ):
        super().__init__(parent)
        self.rows = rows
        self.labels = labels
        self.with_secret = with_secret
        self.variaveis = variaveis
        self._loading = False

        colunas = ["", labels[0], labels[1]]
        if with_secret:
            colunas.append("Secreto")
        colunas.append("")

        self.table = QTableWidget(0, len(colunas), self)
        self.table.setHorizontalHeaderLabels(colunas)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # a marca de escolhido pega a linha toda: celula sozinha vira uma caixinha
        # solta no meio da grade, sem comeco nem fim
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # AnyKeyPressed nao entra aqui de proposito: com a celula so selecionada, uma
        # tecla como Delete ou Backspace apertada por engano iniciava edicao com o texto
        # inteiro pre-selecionado, e a mesma tecla virava o valor vazio.
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )

        self.col_secret = 3 if with_secret else None
        self.col_del = len(colunas) - 1

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.col_del, QHeaderView.ResizeMode.Fixed)
        if with_secret:
            header.setSectionResizeMode(self.col_secret, QHeaderView.ResizeMode.Fixed)
            # cabecalho desenha em maiuscula, e SECRETO pede 100 com o padding
            self.table.setColumnWidth(self.col_secret, 112)
        self.table.setColumnWidth(0, 38)
        self.table.setColumnWidth(1, 260)
        self.table.setColumnWidth(self.col_del, 34)
        self.table.itemChanged.connect(self._on_item_changed)
        self.delegate = DicaDelegate(
            {1: labels[0].lower(), 2: labels[1].lower()}, self.table, variaveis
        )
        self.table.setItemDelegate(self.delegate)
        self.hover = VarHover(self.table, self.delegate, variaveis)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)

        self.reload()


    def repintar(self) -> None:
        self.table.viewport().update()

    def reload(self) -> None:
        self._loading = True
        self.delegate.tokens.clear()
        self.table.setRowCount(0)
        for row in self.rows:
            self._append_row(row, ghost=False)
        self._append_row({"key": "", "value": "", "enabled": True}, ghost=True)
        self._loading = False

    def _checkbox(self, marcado: bool, ao_mudar, dica: str = "") -> QWidget:
        box = Marcador()
        box.setChecked(marcado)
        if dica:
            box.setToolTip(dica)
        box.stateChanged.connect(ao_mudar)
        return _centrado(box)

    def _botao_apagar(self, data: dict) -> QWidget:
        """X desenhado, com area de clique redonda que so acende no hover."""
        botao = BotaoApagar()
        botao.clicked.connect(lambda _=False, d=data: self._remove(d))
        return _centrado(botao)

    def _append_row(self, data: dict, ghost: bool) -> None:
        index = self.table.rowCount()
        self.table.insertRow(index)
        self.table.setRowHeight(index, theme.medida("linha_grade"))

        if not ghost:
            self.table.setCellWidget(
                index,
                0,
                self._checkbox(
                    data.get("enabled", True) is not False,
                    lambda st, d=data: self._toggle(d, st),
                    "desmarque pra nao mandar esta linha",
                ),
            )

        for col, field in ((1, "key"), (2, "value")):
            item = QTableWidgetItem(data.get(field) or "")
            item.setData(Qt.ItemDataRole.UserRole, ghost)
            if ghost:
                item.setForeground(Qt.GlobalColor.gray)
            if col == 2 and data.get("secret") and data.get(field):
                item.setToolTip("valor secreto, mostrado inteiro aqui e mascarado no resto do app")
            self.table.setItem(index, col, item)

        if self.with_secret and not ghost:
            self.table.setCellWidget(
                index,
                self.col_secret,
                self._checkbox(
                    bool(data.get("secret")),
                    lambda st, d=data: self._toggle_secret(d, st),
                    "valor secreto: fica no cofre e nunca sai em log, historico ou git",
                ),
            )

        if not ghost:
            self.table.setCellWidget(index, self.col_del, self._botao_apagar(data))


    def _toggle(self, data: dict, state: int) -> None:
        data["enabled"] = state == Qt.CheckState.Checked.value
        self.changed.emit()

    def _toggle_secret(self, data: dict, state: int) -> None:
        data["secret"] = state == Qt.CheckState.Checked.value
        self.changed.emit()

    def _remove(self, data: dict) -> None:
        if data in self.rows:
            self.rows.remove(data)
        self.reload()
        self.changed.emit()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        row = item.row()
        # a coluna tem que sair daqui, antes do reload: remontar a grade apaga a celula
        # do lado C++, e ler item.column() depois derruba o app com objeto ja deletado
        coluna = item.column()
        is_ghost = bool(item.data(Qt.ItemDataRole.UserRole))
        key = self.table.item(row, 1).text() if self.table.item(row, 1) else ""
        value = self.table.item(row, 2).text() if self.table.item(row, 2) else ""

        if is_ghost:
            if not key and not value:
                return
            novo = {"key": key, "value": value, "enabled": True}
            if self.with_secret:
                novo["secret"] = False
            self.rows.append(novo)
            self.reload()
            self.table.setCurrentCell(len(self.rows) - 1, coluna)
        else:
            if 0 <= row < len(self.rows):
                self.rows[row]["key"] = key
                self.rows[row]["value"] = value
        self.changed.emit()

    def active_count(self) -> int:
        return len([r for r in self.rows if r.get("enabled") is not False and r.get("key")])
