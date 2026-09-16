"""Gerenciador de variaveis: globais, collection, pasta, ambientes e o mapa efetivo."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core import scopes
from ..core.workspaces import new_id
from . import theme
from .kvtable import KvTable
from . import highlight
from .request_editor import mono
from .widgets import cabecalho_a_esquerda


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

        ordem = QLabel(
            "Precedencia, do mais fraco pro mais forte:   "
            "<b style='color:#9aa4b2'>globais</b>  &lt;  "
            "<b style='color:#c084fc'>collection</b>  &lt;  "
            "<b style='color:#50e3c2'>pasta</b>  &lt;  "
            "<b style='color:#4da3ff'>ambiente</b>  &lt;  "
            "<b style='color:#fca130'>execucao</b>"
        )
        root.addWidget(ordem)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)


        colecao = next((n for n in self.ancestry if n.get("type") == "collection"), None)
        if colecao is not None:
            colecao.setdefault("variables", [])
            self.pagina_colecao = ScopePage(
                f"Variaveis da collection {colecao.get('name')}",
                "Vao junto quando voce exporta ou compartilha a collection. Nunca coloque "
                "segredo real aqui, use o ambiente com a marca de secreto.",
                colecao["variables"],
            )
            self.pagina_colecao.changed.connect(self._mudou)
            self.tabs.addTab(self.pagina_colecao, "Collection")

        pasta = next((n for n in reversed(self.ancestry) if n.get("type") == "folder"), None)
        if pasta is not None:
            pasta.setdefault("variables", [])
            self.pagina_pasta = ScopePage(
                f"Variaveis da pasta {pasta.get('name')}",
                "Valem so para os requests dentro desta pasta. Servem para valor comum de "
                "um grupo, e perdem para o ambiente de proposito.",
                pasta["variables"],
            )
            self.pagina_pasta.changed.connect(self._mudou)
            self.tabs.addTab(self.pagina_pasta, "Pasta")

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
            for indice in range(self.tabs.count()):
                if self.tabs.tabText(indice).lower() == aba.lower():
                    self.tabs.setCurrentIndex(indice)
                    break


    def _pagina_ambientes(self) -> QWidget:
        pagina = QWidget()
        layout = QVBoxLayout(pagina)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        barra = QHBoxLayout()
        barra.setSpacing(6)
        self.combo_env = QComboBox()
        self.combo_env.setMinimumWidth(220)
        self.combo_env.currentIndexChanged.connect(self._trocar_env)
        barra.addWidget(self.combo_env)

        for texto, alvo in (
            ("Novo", self._novo_env),
            ("Renomear", self._renomear_env),
            ("Duplicar", self._duplicar_env),
            ("Usar este", self._ativar_env),
            ("Excluir", self._excluir_env),
        ):
            botao = QPushButton(texto)
            botao.clicked.connect(alvo)
            barra.addWidget(botao)
        barra.addStretch(1)

        self.marca_ativo = QLabel("")
        self.marca_ativo.setObjectName("hint")
        barra.addWidget(self.marca_ativo)
        layout.addLayout(barra)

        explicacao = QLabel(
            "O ambiente e o que voce troca na barra para ir de dev para hml e para prd. "
            "Marque como secreto o que nao pode aparecer em historico nem em log."
        )
        explicacao.setObjectName("hint")
        explicacao.setWordWrap(True)
        layout.addWidget(explicacao)

        self.caixa_env = QWidget()
        QVBoxLayout(self.caixa_env).setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.caixa_env, 1)

        self._recarregar_envs()
        return pagina

    def _recarregar_envs(self, selecionar: str | None = None) -> None:
        self.combo_env.blockSignals(True)
        self.combo_env.clear()
        for env in self.tree.get("environments") or []:
            self.combo_env.addItem(env.get("name") or "sem nome", env.get("id"))
        alvo = selecionar or self.tree.get("activeEnv")
        indice = self.combo_env.findData(alvo)
        self.combo_env.setCurrentIndex(indice if indice >= 0 else 0)
        self.combo_env.blockSignals(False)
        self._trocar_env()

    def _env_atual(self) -> dict | None:
        alvo = self.combo_env.currentData()
        for env in self.tree.get("environments") or []:
            if env.get("id") == alvo:
                return env
        return None

    def _trocar_env(self) -> None:
        env = self._env_atual()
        layout = self.caixa_env.layout()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if env is None:
            vazio = QLabel("nenhum ambiente ainda, crie o primeiro em Novo")
            vazio.setObjectName("hint")
            vazio.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(vazio)
            self.marca_ativo.setText("")
            return

        env.setdefault("values", [])
        tabela = KvTable(env["values"], ("Nome", "Valor"), with_secret=True)
        tabela.changed.connect(self._mudou)
        layout.addWidget(tabela)
        ativo = env.get("id") == self.tree.get("activeEnv")
        self.marca_ativo.setText("este e o ambiente ativo" if ativo else "ambiente ativo e outro")

    def _novo_env(self) -> None:
        nome, ok = QInputDialog.getText(self, "Novo ambiente", "Nome do ambiente")
        if not ok or not nome.strip():
            return
        env = {"id": new_id("env"), "name": nome.strip(), "values": []}
        self.tree.setdefault("environments", []).append(env)
        self.tree["activeEnv"] = env["id"]
        self._recarregar_envs(env["id"])
        self._mudou()

    def _ativar_env(self) -> None:
        env = self._env_atual()
        if not env:
            return
        self.tree["activeEnv"] = env.get("id")
        self._trocar_env()
        self._mudou()

    def _renomear_env(self) -> None:
        env = self._env_atual()
        if not env:
            return
        nome, ok = QInputDialog.getText(self, "Renomear ambiente", "Nome", text=env.get("name") or "")
        if ok and nome.strip():
            env["name"] = nome.strip()
            self._recarregar_envs(env["id"])
            self._mudou()

    def _duplicar_env(self) -> None:
        import copy

        env = self._env_atual()
        if not env:
            return
        clone = copy.deepcopy(env)
        clone["id"] = new_id("env")
        clone["name"] = f"{env.get('name')} copia"
        self.tree["environments"].append(clone)
        self._recarregar_envs(clone["id"])
        self._mudou()

    def _excluir_env(self) -> None:
        env = self._env_atual()
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
        self.tree["environments"].remove(env)
        if self.tree.get("activeEnv") == env.get("id"):
            self.tree["activeEnv"] = None
        self._recarregar_envs()
        self._mudou()


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
                item_valor.setForeground(QColor("#c084fc"))
            item_valor.setToolTip(mostrado)
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
            f"{len(nomes)} variaveis efetivas   |   {secretas} secretas   |   {vazias} sem valor"
        )


    def _ao_trocar_aba(self, _indice: int) -> None:
        self._atualizar_efetivo()

    def _mudou(self) -> None:
        self._atualizar_efetivo()
        parent = self.parent()
        if parent is not None and hasattr(parent, "on_variables_changed"):
            parent.on_variables_changed()
