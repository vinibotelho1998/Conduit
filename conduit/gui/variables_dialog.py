"""Gerenciador de variaveis: globais, collection, pasta, ambientes e o mapa efetivo."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core import scopes
from . import theme
from .kvtable import KvTable
from . import highlight
from .request_editor import mono
from .widgets import cabecalho_a_esquerda, conta, dica_de_fora


class ScopePage(QWidget):
    """Uma aba de escopo: explicacao curta mais a grade de pares."""

    changed = Signal()

    def __init__(self, titulo: str, explicacao: str, rows: list, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        cabeca = QLabel(titulo)
        cabeca.setStyleSheet("font-weight: 600;")
        layout.addWidget(cabeca)

        texto = QLabel(explicacao)
        texto.setObjectName("hint")
        texto.setWordWrap(True)
        layout.addWidget(texto)

        self.table = KvTable(rows, ("Nome", "Valor"), with_secret=True)
        self.table.changed.connect(self.changed.emit)
        layout.addWidget(self.table, 1)


class VariablesDialog(QDialog):
    """Edita os quatro escopos que vao pro disco e mostra o resultado efetivo."""

    def __init__(
        self,
        tree: dict,
        ancestry: list[dict] | None,
        runtime: dict | None,
        parent=None,
        aba: str = "",
        origem: str = "",
    ):
        super().__init__(parent)
        self.tree = tree
        self.ancestry = ancestry or []
        self.runtime = runtime or {}
        self.setWindowTitle("Variaveis")
        self.resize(940, 700)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        # Cor de cada escopo pela paleta do tema, a mesma da tabela Efetivo. Com hex
        # fixo, ambiente saia numa cor na legenda e em outra nos nomes, e pasta quase
        # sumia no tema claro. Execucao fica de fora: nao ha como criar uma pela tela.
        ordem = QLabel()
        theme.ao_trocar_widget(
            ordem,
            lambda alvo: alvo.setText(
                "Precedencia, do mais fraco pro mais forte:   "
                + "  &lt;  ".join(
                    f"<b style='color:{highlight.cor_do_escopo(escopo)}'>{escopo}</b>"
                    for escopo in ("globais", "collection", "pasta", "ambiente")
                )
            ),
        )
        root.addWidget(ordem)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        # nome de origem de cada aba, pra abrir a pasta certa quando ha pasta dentro de pasta
        self._origem_da_aba: dict[int, str] = {}

        colecao = next((n for n in self.ancestry if n.get("type") == "collection"), None)
        if colecao is not None:
            colecao.setdefault("variables", [])
            self.pagina_colecao = ScopePage(
                f"Variaveis da collection {colecao.get('name')}",
                "Vao junto quando voce exporta ou compartilha a collection. Marcada como "
                "secreta, o valor fica no cofre desta maquina e sai do arquivo versionado.",
                colecao["variables"],
            )
            self.pagina_colecao.changed.connect(self._mudou)
            indice = self.tabs.addTab(self.pagina_colecao, "Collection")
            self._origem_da_aba[indice] = colecao.get("name") or ""

        # Uma aba por pasta da linhagem, da mais de fora pra mais de dentro. So com a
        # mais proxima, a variavel da pasta de fora caia numa pagina onde ela nao existia,
        # e editar criava uma copia na pasta de dentro.
        pastas = [n for n in self.ancestry if n.get("type") == "folder"]
        for pasta in pastas:
            pasta.setdefault("variables", [])
            pagina = ScopePage(
                f"Variaveis da pasta {pasta.get('name')}",
                "Valem so para os requests dentro desta pasta. Servem para valor comum de "
                "um grupo, e perdem para o ambiente de proposito.",
                pasta["variables"],
            )
            pagina.changed.connect(self._mudou)
            self.pagina_pasta = pagina
            rotulo = "Pasta" if len(pastas) == 1 else f"Pasta {pasta.get('name')}"
            indice = self.tabs.addTab(pagina, rotulo)
            self._origem_da_aba[indice] = pasta.get("name") or ""

        # Ambientes e globais moram na lateral agora, no modelo do Postman. Aqui fica
        # so o que e do contexto do request aberto, mais o resultado efetivo.
        self.tabs.addTab(self._pagina_efetivo(), "Efetivo")
        self.tabs.currentChanged.connect(self._ao_trocar_aba)
        root.addWidget(self.tabs, 1)

        rodape = QHBoxLayout()
        self.resumo = QLabel("")
        self.resumo.setObjectName("hint")
        rodape.addWidget(self.resumo, 1)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.accept)
        rodape.addWidget(fechar)
        root.addLayout(rodape)

        self._mudou()

        # a aba pedida so pode ser escolhida aqui no fim: trocar de aba dispara a
        # atualizacao do mapa efetivo, que precisa do rodape ja montado
        if aba:
            self._escolher_aba(aba, origem)

    def _escolher_aba(self, aba: str, origem: str = "") -> None:
        candidatas = [
            indice for indice in range(self.tabs.count())
            if self.tabs.tabText(indice).lower().split(" ")[0] == aba.lower()
        ]
        if origem:
            certas = [i for i in candidatas if self._origem_da_aba.get(i) == origem]
            candidatas = certas or candidatas
        if candidatas:
            # a pasta mais de dentro e a ultima, e e ela que vence na precedencia
            self.tabs.setCurrentIndex(candidatas[-1])


    def _pagina_efetivo(self) -> QWidget:
        pagina = QWidget()
        layout = QVBoxLayout(pagina)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        texto = QLabel(
            "O que o request enxerga de verdade agora, ja aplicada a precedencia. "
            "Quando o mesmo nome existe em mais de um escopo, a coluna da direita diz quem perdeu."
        )
        texto.setObjectName("hint")
        texto.setWordWrap(True)
        layout.addWidget(texto)

        self.tabela_efetivo = QTableWidget(0, 4)
        self.tabela_efetivo.setHorizontalHeaderLabels(["Nome", "Valor", "Vem de", "Sombreada em"])
        cabecalho_a_esquerda(self.tabela_efetivo)
        self.tabela_efetivo.verticalHeader().setVisible(False)
        self.tabela_efetivo.setShowGrid(False)
        self.tabela_efetivo.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabela_efetivo.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tabela_efetivo.setColumnWidth(0, 190)
        self.tabela_efetivo.setColumnWidth(2, 170)
        self.tabela_efetivo.setColumnWidth(3, 210)
        layout.addWidget(self.tabela_efetivo, 1)
        return pagina

    def _atualizar_efetivo(self) -> None:
        mapa = scopes.build(self.tree, self.ancestry, self.runtime)
        nomes = sorted(mapa)
        self.tabela_efetivo.setRowCount(len(nomes))

        for indice, nome in enumerate(nomes):
            info = mapa[nome]
            item_nome = QTableWidgetItem(nome)
            item_nome.setFont(mono(9))
            item_nome.setForeground(QColor(highlight.cor_do_escopo(info.scope)))
            self.tabela_efetivo.setItem(indice, 0, item_nome)

            mostrado = info.masked() if info.secret else info.value
            item_valor = QTableWidgetItem(mostrado or "sem valor")
            item_valor.setFont(mono(9))
            if not info.value:
                item_valor.setForeground(QColor(theme.WARN))
            elif info.secret:
                item_valor.setForeground(QColor(theme.CODIGO["variavel_secreta"]))
            item_valor.setToolTip(dica_de_fora(mostrado))
            self.tabela_efetivo.setItem(indice, 1, item_valor)

            origem = f"{scopes.SCOPE_LABEL.get(info.scope, info.scope)}  {info.origin}".strip()
            self.tabela_efetivo.setItem(indice, 2, QTableWidgetItem(origem))

            if info.shadowed:
                perdedores = ", ".join(
                    f"{scopes.SCOPE_LABEL.get(s.scope, s.scope)}" for s in info.shadowed
                )
                item_sombra = QTableWidgetItem(perdedores)
                item_sombra.setForeground(QColor(theme.FAINT))
                item_sombra.setToolTip(
                    "\n".join(f"{s.scope} {s.origin}: {s.masked() if s.secret else s.value}" for s in info.shadowed)
                )
                self.tabela_efetivo.setItem(indice, 3, item_sombra)
            self.tabela_efetivo.setRowHeight(indice, theme.medida("linha_tabela"))

        secretas = sum(1 for n in nomes if mapa[n].secret)
        vazias = sum(1 for n in nomes if not mapa[n].value)
        self.resumo.setText(
            f"{conta(len(nomes), 'variavel efetiva', 'variaveis efetivas')}   |   "
            f"{conta(secretas, 'secreta', 'secretas')}   |   {vazias} sem valor"
        )


    def _ao_trocar_aba(self, _indice: int) -> None:
        self._atualizar_efetivo()

    def _mudou(self) -> None:
        self._atualizar_efetivo()
        parent = self.parent()
        if parent is not None and hasattr(parent, "on_variables_changed"):
            parent.on_variables_changed()
