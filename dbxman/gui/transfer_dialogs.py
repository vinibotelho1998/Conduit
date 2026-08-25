"""Telas de importar e exportar."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyledItemDelegate,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import importer
from . import theme
from .icons import ABREVIACAO
from .request_editor import mono
from .tree_delegate import pintar_pilula
from .widgets import Faixa

FILTRO_ARQUIVO = (
    "Tudo que eu entendo (*.json *.yaml *.yml *.bru);;"
    "Postman e Insomnia (*.json);;"
    "OpenAPI e Swagger (*.json *.yaml *.yml);;"
    "Bruno (*.bru);;"
    "Todos (*)"
)

FORMATOS = [
    ("Postman", "Collection v2.1 e environment"),
    ("Insomnia", "exportacao v4"),
    ("Bruno", "pasta com arquivos .bru"),
    ("OpenAPI", "OpenAPI 3 e Swagger 2"),
]

PAPEL_NODE = Qt.ItemDataRole.UserRole + 1


# --------------------------------------------------------------------- pecas


def titulo(texto: str, tamanho: float = 13.0) -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setStyleSheet(f"font-size: {tamanho}pt; font-weight: 700;")
    return rotulo


def dica(texto: str) -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setObjectName("hint")
    rotulo.setWordWrap(True)
    return rotulo


class Pilula(QLabel):
    """Etiqueta arredondada, a mesma linguagem do resto do app."""

    def __init__(self, texto: str = "", cor: str = theme.DIM, parent=None):
        super().__init__(texto, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pintar(cor)

    def pintar(self, cor: str, forte: bool = False) -> None:
        qcor = QColor(cor)
        fundo = f"rgba({qcor.red()},{qcor.green()},{qcor.blue()},{70 if forte else 34})"
        self.setStyleSheet(
            f"color: {cor}; background: {fundo}; border: 1px solid {cor}{'aa' if forte else '44'};"
            f" border-radius: 9px; padding: 2px 10px; font-size: 8pt;"
            f" font-weight: {'700' if forte else '600'};"
        )


class Numero(QFrame):
    """Um numero grande com rotulo embaixo, pro resumo do que vai entrar."""

    def __init__(self, rotulo: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(0)

        self.valor = QLabel("0")
        self.valor.setStyleSheet(f"font-size: 16pt; font-weight: 700; color: {theme.TEXT};")
        self.valor.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.valor)

        texto = QLabel(rotulo)
        texto.setStyleSheet(f"color: {theme.FAINT}; font-size: 8pt;")
        texto.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(texto)

        # o seletor precisa do objectName, senao o QLabel de dentro herda a borda
        self.setObjectName("numero")
        self.setStyleSheet(
            f"QFrame#numero {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER};"
            f" border-radius: 8px; }}"
            f"QFrame#numero QLabel {{ background: transparent; border: 0; }}"
        )

    def definir(self, valor: int, destaque: bool = False) -> None:
        self.valor.setText(str(valor))
        cor = theme.ACCENT if destaque and valor else (theme.TEXT if valor else theme.FAINT)
        self.valor.setStyleSheet(f"font-size: 16pt; font-weight: 700; color: {cor};")


class AreaSolta(QFrame):
    """Onde se arrasta o arquivo. Aceita soltar de verdade, nao e so enfeite."""

    escolhido = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(150)
        self._pintar(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.recado = QLabel("Arraste o arquivo aqui")
        self.recado.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.recado.setStyleSheet(f"font-size: 11pt; color: {theme.DIM};")
        layout.addWidget(self.recado)

        botoes = QHBoxLayout()
        botoes.setAlignment(Qt.AlignmentFlag.AlignCenter)
        botoes.setSpacing(8)
        arquivo = QPushButton("Escolher arquivo")
        arquivo.clicked.connect(self._pedir_arquivo)
        pasta = QPushButton("Escolher pasta")
        pasta.setToolTip("O Bruno guarda a collection numa pasta")
        pasta.clicked.connect(self._pedir_pasta)
        botoes.addWidget(arquivo)
        botoes.addWidget(pasta)
        layout.addLayout(botoes)

        formatos = QHBoxLayout()
        formatos.setAlignment(Qt.AlignmentFlag.AlignCenter)
        formatos.setSpacing(6)
        self.pilulas: dict[str, Pilula] = {}
        for nome, descricao in FORMATOS:
            pilula = Pilula(nome, theme.FAINT)
            pilula.setToolTip(descricao)
            self.pilulas[nome] = pilula
            formatos.addWidget(pilula)
        layout.addLayout(formatos)

    def _pintar(self, ativo: bool) -> None:
        cor = theme.ACCENT if ativo else theme.BORDER
        fundo = theme.PANEL2 if ativo else theme.PANEL
        self.setObjectName("areaSolta")
        self.setStyleSheet(
            f"QFrame#areaSolta {{ background: {fundo}; border: 2px dashed {cor};"
            f" border-radius: 12px; }}"
            f"QFrame#areaSolta > QLabel {{ background: transparent; border: 0; }}"
        )

    def marcar_formato(self, nome: str | None) -> None:
        for chave, pilula in self.pilulas.items():
            if chave == nome:
                pilula.pintar(theme.ACCENT, forte=True)
            else:
                pilula.pintar(theme.FAINT)

    # ----------------------------------------------------------- arrastar

    def dragEnterEvent(self, evento):  # noqa: N802
        if evento.mimeData().hasUrls():
            evento.acceptProposedAction()
            self._pintar(True)
            self.recado.setText("solte pra importar")

    def dragLeaveEvent(self, evento):  # noqa: N802
        self._pintar(False)
        self.recado.setText("Arraste o arquivo aqui")

    def dropEvent(self, evento):  # noqa: N802
        self._pintar(False)
        self.recado.setText("Arraste o arquivo aqui")
        urls = evento.mimeData().urls()
        if urls:
            self.escolhido.emit(urls[0].toLocalFile())

    def _pedir_arquivo(self) -> None:
        caminho, _ = QFileDialog.getOpenFileName(self, "Escolher arquivo", "", FILTRO_ARQUIVO)
        if caminho:
            self.escolhido.emit(caminho)

    def _pedir_pasta(self) -> None:
        caminho = QFileDialog.getExistingDirectory(self, "Escolher pasta da collection")
        if caminho:
            self.escolhido.emit(caminho)


class LinhaPrevia(QStyledItemDelegate):
    """Mesma leitura da arvore do app: pilula do metodo colada no nome.

    Desenha apagado de proposito. A previa e so leitura, nao tem o que clicar nela, e
    linha que acende no hover ou fica selecionada promete uma acao que nao existe.
    """

    OPACIDADE = 0.62

    def paint(self, painter, option, index):
        node = index.data(PAPEL_NODE)
        if not node:
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setOpacity(self.OPACIDADE)
        area = option.rect

        x = area.left() + 2
        centro = area.center().y() + 0.5
        tipo = node.get("type")

        if tipo == "request":
            metodo = (node.get("method") or "GET").upper()
            x = pintar_pilula(
                painter, x, centro, ABREVIACAO.get(metodo, metodo),
                theme.METHOD_COLORS.get(metodo, theme.DIM),
            ) + 8
            cor = theme.TEXT
        else:
            cor = theme.ACCENT if tipo == "collection" else theme.DIM

        fonte = QFont(option.font)
        fonte.setBold(tipo == "collection")
        painter.setFont(fonte)
        painter.setPen(QPen(QColor(cor)))
        metricas = painter.fontMetrics()
        largura = area.right() - x - 8
        painter.drawText(
            QRectF(x, area.top(), largura, area.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            metricas.elidedText(node.get("name") or "", Qt.TextElideMode.ElideRight, int(largura)),
        )
        painter.restore()

    def sizeHint(self, option, index):
        tamanho = super().sizeHint(option, index)
        tamanho.setHeight(25)
        return tamanho


# ------------------------------------------------------------------ importar


class ImportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Importar")
        self.resize(820, 700)
        self.resultado = None
        self.caminho: Path | None = None

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(20, 18, 20, 16)
        raiz.setSpacing(12)

        raiz.addWidget(titulo("Importar collection"))
        raiz.addWidget(
            dica(
                "Reconheco o formato pelo conteudo do arquivo, entao voce nao precisa dizer "
                "de onde veio. O que entrar fica ao lado do que ja existe, nada e apagado."
            )
        )

        self.area = AreaSolta()
        self.area.escolhido.connect(lambda c: self.analisar(Path(c)))
        raiz.addWidget(self.area)

        # barra compacta que substitui a area depois de escolher
        self.barra = QFrame()
        self.barra.setObjectName("card")
        barra_layout = QHBoxLayout(self.barra)
        barra_layout.setContentsMargins(14, 10, 14, 10)
        barra_layout.setSpacing(10)

        self.pilula_formato = Pilula("", theme.ACCENT)
        barra_layout.addWidget(self.pilula_formato)

        self.nome_arquivo = QLabel("")
        self.nome_arquivo.setFont(mono(9))
        barra_layout.addWidget(self.nome_arquivo, 1)

        trocar = QPushButton("Trocar")
        trocar.setObjectName("flat")
        trocar.clicked.connect(self._voltar)
        barra_layout.addWidget(trocar)
        self.barra.hide()
        raiz.addWidget(self.barra)

        # numeros do que vai entrar
        self.numeros = QWidget()
        grade = QGridLayout(self.numeros)
        grade.setContentsMargins(0, 0, 0, 0)
        grade.setSpacing(8)
        self.tiles = {}
        for coluna, (chave, rotulo) in enumerate(
            (("collections", "collections"), ("pastas", "pastas"),
             ("requests", "requests"), ("ambientes", "ambientes"))
        ):
            tile = Numero(rotulo)
            self.tiles[chave] = tile
            grade.addWidget(tile, 0, coluna)
        self.numeros.hide()
        raiz.addWidget(self.numeros)

        self.rotulo_previa = QLabel("O QUE VAI ENTRAR")
        self.rotulo_previa.setObjectName("sectionTitle")
        self.rotulo_previa.hide()
        raiz.addWidget(self.rotulo_previa)

        self.previa = QTreeWidget()
        self.previa.setHeaderHidden(True)
        self.previa.setIndentation(16)
        self.previa.setItemDelegate(LinhaPrevia(self.previa))
        self.previa.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.previa.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.previa.setStyleSheet(
            f"QTreeWidget {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER};"
            f" border-radius: 8px; padding: 6px; }}"
            f"QTreeWidget::item:hover {{ background: transparent; }}"
        )
        self.previa.hide()
        raiz.addWidget(self.previa, 1)

        self.faixa = Faixa()
        raiz.addWidget(self.faixa)

        self.botoes = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        aplicar = self.botoes.button(QDialogButtonBox.StandardButton.Ok)
        aplicar.setText("Importar")
        aplicar.setObjectName("send")
        aplicar.setEnabled(False)
        self.botoes.accepted.connect(self.accept)
        self.botoes.rejected.connect(self.reject)
        raiz.addWidget(self.botoes)

    # ------------------------------------------------------------------ fluxo

    def _voltar(self) -> None:
        self.resultado = None
        self.caminho = None
        self.barra.hide()
        self.numeros.hide()
        self.rotulo_previa.hide()
        self.previa.hide()
        self.previa.clear()
        self.faixa.esconder()
        self.area.show()
        self.area.marcar_formato(None)
        self.botoes.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)

    def analisar(self, caminho: Path) -> None:
        self.caminho = caminho
        self.previa.clear()
        self.faixa.esconder()

        possiveis = importer.detectar(caminho)
        if not possiveis:
            self.area.marcar_formato(None)
            self.faixa.mostrar(
                f"nao reconheci o formato de {caminho.name}. Aceito Postman, Insomnia, "
                "Bruno e OpenAPI",
                theme.ERR,
            )
            self.botoes.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
            return

        nome, _ = possiveis[0]
        resultado = importer.importar(caminho)
        self.resultado = resultado

        if resultado.erro:
            self.faixa.mostrar(resultado.erro, theme.ERR)
            self.botoes.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
            return

        self.area.hide()
        self.barra.show()
        self.pilula_formato.setText(nome)
        self.pilula_formato.pintar(theme.ACCENT, forte=True)
        self.nome_arquivo.setText(caminho.name)
        self.nome_arquivo.setToolTip(str(caminho))

        contagem = resultado.contar()
        for chave, tile in self.tiles.items():
            tile.definir(contagem.get(chave, 0), destaque=chave == "requests")
        self.numeros.show()

        for colecao in resultado.collections:
            item = QTreeWidgetItem()
            item.setData(0, PAPEL_NODE, colecao)
            self._preencher(item, colecao.get("items") or [])
            self.previa.addTopLevelItem(item)

        for env in resultado.environments:
            quantos = len(env.get("values") or [])
            item = QTreeWidgetItem()
            item.setData(
                0,
                PAPEL_NODE,
                {"type": "folder", "name": f"ambiente {env.get('name')}, {quantos} variaveis"},
            )
            self.previa.addTopLevelItem(item)

        self.rotulo_previa.show()
        self.previa.show()
        # expandir so funciona com a arvore ja montada, entao vai tudo de uma vez no fim
        self.previa.expandAll()

        if resultado.avisos:
            self.faixa.mostrar("   ·   ".join(resultado.avisos), theme.WARN)

        self.botoes.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

    def _preencher(self, pai: QTreeWidgetItem, items: list) -> None:
        for node in items:
            filho = QTreeWidgetItem()
            filho.setData(0, PAPEL_NODE, node)
            if node.get("type") != "request":
                self._preencher(filho, node.get("items") or [])
            pai.addChild(filho)


# ------------------------------------------------------------------ exportar


class CartaoFormato(QFrame):
    """Opcao de formato desenhada como cartao, em vez de linha de combo."""

    escolhido = Signal(str)

    def __init__(self, chave: str, nome: str, detalhe: str, parent=None):
        super().__init__(parent)
        self.chave = chave
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)

        self.nome = QLabel(nome)
        self.nome.setStyleSheet("font-weight: 700;")
        layout.addWidget(self.nome)

        self.detalhe = QLabel(detalhe)
        self.detalhe.setStyleSheet(f"color: {theme.FAINT}; font-size: 8pt;")
        self.detalhe.setWordWrap(True)
        layout.addWidget(self.detalhe)

        self.marcar(False)

    def marcar(self, ativo: bool) -> None:
        cor = theme.ACCENT if ativo else theme.BORDER
        fundo = theme.PANEL2 if ativo else theme.PANEL
        self.setObjectName("cartaoFormato")
        self.setStyleSheet(
            f"QFrame#cartaoFormato {{ background: {fundo}; border: 1px solid {cor};"
            f" border-radius: 8px; }}"
            f"QFrame#cartaoFormato:hover {{ border-color: {theme.ACCENT}; }}"
            f"QFrame#cartaoFormato QLabel {{ background: transparent; border: 0; }}"
        )

    def mousePressEvent(self, evento):  # noqa: N802
        self.escolhido.emit(self.chave)


class ExportDialog(QDialog):
    def __init__(self, tree: dict, parent=None):
        super().__init__(parent)
        self.tree = tree
        self.setWindowTitle("Exportar")
        self.resize(820, 700)
        self.destino: Path | None = None
        self.formato = "postman"

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(20, 18, 20, 16)
        raiz.setSpacing(12)

        raiz.addWidget(titulo("Exportar collections"))

        rotulo = QLabel("PARA QUAL FORMATO")
        rotulo.setObjectName("sectionTitle")
        raiz.addWidget(rotulo)

        grade = QGridLayout()
        grade.setSpacing(8)
        self.cartoes: dict[str, CartaoFormato] = {}
        detalhes = [
            ("postman", "Postman", "Collection v2.1, um arquivo .json"),
            ("insomnia", "Insomnia", "exportacao v4, um arquivo .json"),
            ("bruno", "Bruno", "uma pasta com arquivos .bru"),
            ("openapi", "OpenAPI 3", "um .json ou .yaml, aproximado"),
        ]
        for indice, (chave, nome, detalhe) in enumerate(detalhes):
            cartao = CartaoFormato(chave, nome, detalhe)
            cartao.escolhido.connect(self.escolher_formato)
            self.cartoes[chave] = cartao
            grade.addWidget(cartao, indice // 2, indice % 2)
        raiz.addLayout(grade)

        cabeca = QHBoxLayout()
        rotulo = QLabel("O QUE LEVAR")
        rotulo.setObjectName("sectionTitle")
        cabeca.addWidget(rotulo)
        cabeca.addStretch(1)
        self.contagem = QLabel("")
        self.contagem.setObjectName("hint")
        cabeca.addWidget(self.contagem)
        marcar = QPushButton("Marcar todas")
        marcar.setObjectName("flat")
        marcar.clicked.connect(self._marcar_todas)
        cabeca.addWidget(marcar)
        raiz.addLayout(cabeca)

        self.lista = QListWidget()
        self.lista.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.lista.setStyleSheet(
            f"QListWidget {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER};"
            f" border-radius: 8px; padding: 6px; }}"
            f"QListWidget::item {{ padding: 6px 8px; border-radius: 5px; }}"
            f"QListWidget::item:hover {{ background: {theme.PANEL2}; }}"
        )
        for colecao in tree.get("collections") or []:
            quantos = self._contar(colecao)
            item = QListWidgetItem(f"{colecao.get('name') or ''}      {quantos} requests")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, colecao.get("id"))
            self.lista.addItem(item)
        self.lista.itemChanged.connect(self._atualizar_contagem)
        raiz.addWidget(self.lista, 1)

        self.com_segredo = QCheckBox("incluir o valor real das variaveis secretas")
        self.com_segredo.stateChanged.connect(self._aviso_segredo)
        raiz.addWidget(self.com_segredo)

        self.faixa = Faixa()
        raiz.addWidget(self.faixa)

        destino = QHBoxLayout()
        destino.setSpacing(8)
        self.caminho_label = QLabel("nenhum destino escolhido")
        self.caminho_label.setObjectName("hint")
        self.caminho_label.setFont(mono(8))
        destino.addWidget(self.caminho_label, 1)
        botao = QPushButton("Escolher destino")
        botao.clicked.connect(self.escolher_destino)
        destino.addWidget(botao)
        raiz.addLayout(destino)

        self.botoes = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        exportar = self.botoes.button(QDialogButtonBox.StandardButton.Ok)
        exportar.setText("Exportar")
        exportar.setObjectName("send")
        exportar.setEnabled(False)
        self.botoes.accepted.connect(self.accept)
        self.botoes.rejected.connect(self.reject)
        raiz.addWidget(self.botoes)

        self.escolher_formato("postman")
        self._atualizar_contagem()
        self._aviso_segredo()

    # ------------------------------------------------------------------ apoio

    @staticmethod
    def _contar(colecao: dict) -> int:
        total = 0

        def andar(items):
            nonlocal total
            for node in items or []:
                if node.get("type") == "request":
                    total += 1
                else:
                    andar(node.get("items"))

        andar(colecao.get("items"))
        return total

    def escolher_formato(self, chave: str) -> None:
        self.formato = chave
        for atual, cartao in self.cartoes.items():
            cartao.marcar(atual == chave)
        self.destino = None
        self.caminho_label.setText("nenhum destino escolhido")
        self.botoes.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)

    def _marcar_todas(self) -> None:
        alvo = (
            Qt.CheckState.Unchecked
            if all(
                self.lista.item(i).checkState() == Qt.CheckState.Checked
                for i in range(self.lista.count())
            )
            else Qt.CheckState.Checked
        )
        for indice in range(self.lista.count()):
            self.lista.item(indice).setCheckState(alvo)

    def _atualizar_contagem(self, *_):
        escolhidas = self.escolhidas()
        requests = sum(self._contar(c) for c in escolhidas)
        self.contagem.setText(f"{len(escolhidas)} de {self.lista.count()}, {requests} requests")

    def _aviso_segredo(self) -> None:
        if self.com_segredo.isChecked():
            self.faixa.mostrar(
                "o arquivo vai conter credencial de verdade, nao mande por chat nem "
                "coloque em repositorio",
                theme.ERR,
            )
        else:
            self.faixa.mostrar(
                "variavel secreta sai so com o nome, sem valor", theme.FAINT
            )

    def escolher_destino(self) -> None:
        pasta = self.formato == "bruno" or (
            self.formato == "postman" and len(self.escolhidas()) > 1
        )
        if pasta:
            caminho = QFileDialog.getExistingDirectory(self, "Pasta de destino")
        else:
            sugestao = {
                "postman": "collection.postman_collection.json",
                "insomnia": "collection.insomnia.json",
                "openapi": "api.openapi.yaml",
            }.get(self.formato, "export.json")
            caminho, _ = QFileDialog.getSaveFileName(self, "Salvar como", sugestao)
        if caminho:
            self.destino = Path(caminho)
            self.caminho_label.setText(caminho)
            self.caminho_label.setStyleSheet(f"color: {theme.TEXT};")
            self.botoes.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

    def escolhidas(self) -> list:
        ids = {
            self.lista.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.lista.count())
            if self.lista.item(i).checkState() == Qt.CheckState.Checked
        }
        return [c for c in self.tree.get("collections") or [] if c.get("id") in ids]

    @property
    def combo(self):
        """Compatibilidade com quem chamava o combo antigo."""

        class _Falso:
            def __init__(self, valor):
                self._valor = valor

            def currentData(self):
                return self._valor

        return _Falso(self.formato)
