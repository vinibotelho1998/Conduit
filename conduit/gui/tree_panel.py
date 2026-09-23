"""Arvore de collections, pastas e requests."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QCursor, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QMenu,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .tree_delegate import (
    RECUO,
    TreeDelegate,
    cor_da_linha,
    pintar_chevron,
    pintar_fundo,
)

ROLE_ID = Qt.ItemDataRole.UserRole
ROLE_NODE = Qt.ItemDataRole.UserRole + 1

class DropTree(QTreeWidget):
    """Arvore que aceita arrastar e soltar, com as regras do dominio.

    Regras: request e pasta podem ir pra dentro de collection ou pasta, collection
    fica sempre na raiz, e nada entra dentro de um request.
    """

    def __init__(self, painel):
        super().__init__()
        self.painel = painel
        self.setDragDropMode(QTreeWidget.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(True)

    def _tipo(self, item) -> str:
        node = self.painel._node(item)
        return (node or {}).get("type", "")

    def dragMoveEvent(self, event):  # noqa: N802
        alvo = self.itemAt(event.position().toPoint())
        posicao = self.dropIndicatorPosition()
        arrastado = self.currentItem()
        tipo_arrastado = self._tipo(arrastado)

        # collection so se reordena entre collections, nunca entra em ninguem
        if tipo_arrastado == "collection":
            if alvo is not None and posicao == QTreeWidget.DropIndicatorPosition.OnItem:
                event.ignore()
                return

        # nada entra dentro de um request ou de um exemplo: os dois sao ponta da arvore,
        # nenhum guarda lista de filhos de verdade no modelo de dados
        if (
            alvo is not None
            and posicao == QTreeWidget.DropIndicatorPosition.OnItem
            and self._tipo(alvo) in ("request", "example")
        ):
            event.ignore()
            return

        # pasta e request nao podem cair na raiz. Antes o codigo transformava a pasta
        # solta em collection, o que mudava o significado do item sem ninguem pedir.
        if tipo_arrastado in ("folder", "request"):
            if alvo is None:
                event.ignore()
                return
            if posicao != QTreeWidget.DropIndicatorPosition.OnItem:
                pai = alvo.parent()
                # cair como irmao de um exemplo poe o item dentro do request dono do
                # exemplo. rebuild_from_widget nao le filho de request nenhum, entao o
                # item largado ali sumia da arvore de dados sem aviso nem desfazer. So
                # exemplo tem pai do tipo request, entao barrar isso tambem cobre o caso.
                if pai is None or self._tipo(pai) == "request":
                    event.ignore()
                    return

        super().dragMoveEvent(event)

    def dropEvent(self, event):  # noqa: N802
        if self.painel.ordenacao != "manual":
            event.ignore()
            return
        self.painel.guardar_estado("mover item")
        super().dropEvent(event)
        self.painel.rebuild_from_widget()

    def paintEvent(self, evento):  # noqa: N802
        """Descobre a linha sob o ponteiro uma vez por pintura.

        A faixa e desenhada linha a linha, e perguntar a posicao do mouse dentro de cada
        uma virava uma chamada ao sistema por linha visivel a cada repintura.
        """
        ponteiro = self.viewport().mapFromGlobal(QCursor.pos())
        self._sob_ponteiro = (
            self.indexAt(ponteiro)
            if self.viewport().rect().contains(ponteiro)
            else QModelIndex()
        )
        super().paintEvent(evento)

    def drawRow(self, painter, opcoes, index):  # noqa: N802
        """Pinta a faixa da linha antes de qualquer outra coisa.

        Antes a faixa saia de dois pinceis, um pra coluna do recuo e outro pro resto, e
        cada um recortava o proprio pedaco. Encostando os dois recortes, a borda suavizada
        de cada metade deixava um risco no meio da linha escolhida. Pintando de uma vez
        so, a faixa e uma peca inteira.
        """
        cor = cor_da_linha(
            self.selectionModel().isSelected(index),
            getattr(self, "_sob_ponteiro", QModelIndex()) == index,
        )
        if cor is not None:
            area = opcoes.rect
            pintar_fundo(painter, area, 2.0, self.viewport().width() - 6.0,
                         area.top() + 1.0, area.height() - 2.0, cor)
        super().drawRow(painter, opcoes, index)

    def drawBranches(self, painter, rect, index):  # noqa: N802
        """Guia vertical por nivel mais a seta do proprio item.

        A guia e o que responde de relance o que esta dentro do que, e onde acaba um
        ramo. Sem ela, tres niveis de pasta viram uma lista plana com recuo.
        """
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        nivel = 0
        pai = index.parent()
        while pai.isValid():
            nivel += 1
            pai = pai.parent()

        passo = self.indentation()
        caneta = QPen(QColor(theme.BORDER))
        caneta.setWidthF(1.0)
        painter.setPen(caneta)
        # na linha em foco a guia nao aparece: o risco cortaria a faixa no meio
        em_foco = self.selectionModel().isSelected(index) or (
            getattr(self, "_sob_ponteiro", QModelIndex()) == index
        )
        for degrau in range(0 if em_foco else nivel):
            x = rect.left() + degrau * passo + passo / 2 + 1
            painter.drawLine(QRectF(x, rect.top(), 0, rect.height()).topLeft(),
                             QRectF(x, rect.top(), 0, rect.height()).bottomLeft())

        if self.model().hasChildren(index):
            centro_x = rect.left() + nivel * passo + passo / 2 + 1
            pintar_chevron(
                painter, centro_x, rect.center().y() + 0.5, self.isExpanded(index), theme.FAINT
            )
        painter.restore()


class TreePanel(QWidget):
    # o painel nao sabe montar curl nem exemplo, quem sabe e a janela
    request_opened = Signal(object)
    tree_changed = Signal()
    favorito_mudou = Signal()
    ordem_aplicada = Signal()
    auth_pedida = Signal(object)
    exemplo_aberto = Signal(object)
    curl_pedido = Signal(object)
    codigo_pedido = Signal(object)
    abrir_pedido = Signal(object)
    # a arvore nao decide excluir sozinha: quem confirma, fecha a aba aberta e avisa o
    # editor e a janela, que tem o contexto todo. Excluir direto daqui, sem passar por
    # ela, deixava a aba do request excluido apontando pro vazio e apagava exemplo sem
    # perguntar.
    exclusao_pedida = Signal(object)
    exemplo_exclusao_pedida = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tree_data: dict = {"collections": []}
        self._by_id: dict[str, dict] = {}
        self._loading = False
        self._desfazer: list[tuple[str, list]] = []
        self.ordenacao = "manual"
        self.uso: dict = {}
        self.caminho_de: dict[str, str] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        head = QWidget()
        head.setFixedHeight(32)
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(12, 0, 6, 0)
        title = QLabel("COLLECTIONS")
        title.setObjectName("sectionTitle")
        head_layout.addWidget(title)
        head_layout.addStretch(1)

        self.btn_new = QToolButton()
        self.btn_new.setText("+")
        self.btn_new.setToolTip("Criar collection, pasta ou request")
        self.btn_new.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu_novo = QMenu(self)
        self.btn_new.setMenu(self.menu_novo)
        self.btn_ordem = QToolButton()
        self.btn_ordem.setText("AZ")
        self.btn_ordem.setToolTip("Ordenar a lista")
        self.btn_ordem.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu_ordem = QMenu(self)
        self.btn_ordem.setMenu(self.menu_ordem)
        self.menu_ordem.aboutToShow.connect(self._montar_menu_ordem)

        self.btn_collapse = QToolButton()
        self.btn_collapse.setText("−")
        self.btn_collapse.setToolTip("Recolher tudo")
        for btn in (self.btn_new, self.btn_ordem, self.btn_collapse):
            theme.estilizar(
                btn,
                lambda: f"QToolButton {{ border: 0; background: transparent; color: {theme.DIM};"
                f" padding: 2px 6px; border-radius: 4px; }}"
                f"QToolButton:hover {{ background: {theme.RAISE}; color: {theme.TEXT}; }}",
            )
            head_layout.addWidget(btn)
        self.btn_collapse.clicked.connect(self._collapse_all)
        root.addWidget(head)

        self.tree = DropTree(self)
        self.tree.setObjectName("arvore")
        # O Qt considera que a marca de escolhido cobre tambem a coluna do recuo, e pinta
        # essa faixa com o azul de realce do sistema direto, sem passar pela folha de
        # estilo: por isso sobrava um retangulo aceso na esquerda da linha, colado na
        # faixa que a gente desenha. Sem cor de realce, so fica o nosso desenho.
        palete = self.tree.palette()
        palete.setBrush(QPalette.ColorRole.Highlight, QBrush(Qt.GlobalColor.transparent))
        palete.setBrush(
            QPalette.ColorGroup.Inactive,
            QPalette.ColorRole.Highlight,
            QBrush(Qt.GlobalColor.transparent),
        )
        self.tree.setPalette(palete)
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(RECUO)
        self.tree.setAnimated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setMouseTracking(True)
        self.tree.setItemDelegate(TreeDelegate(self, self.tree))
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.itemClicked.connect(self._on_click)
        self.tree.itemChanged.connect(self._on_renamed)
        self.tree.itemExpanded.connect(lambda it: self._set_expanded(it, True))
        self.tree.itemCollapsed.connect(lambda it: self._set_expanded(it, False))
        root.addWidget(self.tree, 1)


    def load(self, tree_data: dict) -> None:
        self.tree_data = tree_data
        self._desfazer.clear()
        self.refresh()


    def guardar_estado(self, rotulo: str) -> None:
        """Foto da arvore antes de uma operacao que mexe na estrutura."""
        import copy

        self._desfazer.append((rotulo, copy.deepcopy(self.tree_data.get("collections") or [])))
        del self._desfazer[:-30]

    def pode_desfazer(self) -> str | None:
        return self._desfazer[-1][0] if self._desfazer else None

    def desfazer(self) -> str | None:
        if not self._desfazer:
            return None
        rotulo, foto = self._desfazer.pop()
        self.tree_data["collections"] = foto
        self.refresh()
        self.tree_changed.emit()
        self.favorito_mudou.emit()
        return rotulo


    MODOS = {
        "manual": "Ordem manual",
        "nome": "Nome, A a Z",
        "nome-desc": "Nome, Z a A",
        "metodo": "Metodo",
        "usado": "Mais usados",
        "recente": "Executados por ultimo",
    }

    def definir_ordenacao(self, modo: str) -> None:
        self.ordenacao = modo if modo in self.MODOS else "manual"
        self.tree_data["sortMode"] = self.ordenacao
        # arrastar so faz sentido quando a ordem exibida e a ordem real
        manual = self.ordenacao == "manual"
        self.tree.setDragDropMode(
            QTreeWidget.DragDropMode.InternalMove if manual else QTreeWidget.DragDropMode.NoDragDrop
        )
        self.refresh()

    def _chave_ordem(self, node: dict):
        nome = (node.get("name") or "").lower()
        if self.ordenacao in ("nome", "nome-desc"):
            return nome
        if self.ordenacao == "metodo":
            ordem = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
            metodo = (node.get("method") or "").upper()
            posicao = ordem.index(metodo) if metodo in ordem else 99
            # pasta e collection ficam antes dos requests, senao a lista embaralha
            return (0 if node.get("type") != "request" else 1, posicao, nome)
        if self.ordenacao in ("usado", "recente"):
            vezes, ultima = self._uso_de(node)
            valor = vezes if self.ordenacao == "usado" else ultima
            return (0 if node.get("type") != "request" else 1, -valor, nome)
        return 0

    def _uso_de(self, node: dict) -> tuple[int, float]:
        if node.get("type") != "request":
            return (0, 0.0)
        por_id = self.uso.get(node.get("id"))
        if por_id:
            return por_id
        return self.uso.get(self.caminho_de.get(node.get("id"), ""), (0, 0.0))

    def _ordenados(self, items: list) -> list:
        if self.ordenacao == "manual" or not items:
            return items
        ordenado = sorted(items, key=self._chave_ordem)
        if self.ordenacao == "nome-desc":
            ordenado.reverse()
        return ordenado

    def _mapear_caminhos(self) -> None:
        self.caminho_de.clear()

        def andar(items, prefixo):
            for node in items or []:
                caminho = prefixo + [node.get("name") or ""]
                if node.get("type") == "request":
                    self.caminho_de[node.get("id")] = " / ".join(caminho)
                else:
                    andar(node.get("items"), caminho)

        andar(self.tree_data.get("collections"), [])

    def refresh(self, keep_selection: str | None = None) -> None:
        self._loading = True
        self._mapear_caminhos()
        self.tree.clear()
        self._by_id.clear()
        for node in self._ordenados(self.tree_data.get("collections") or []):
            item = self._build(node)
            self.tree.addTopLevelItem(item)
            # setExpanded so vale depois do item estar dentro da arvore
            self._apply_expansion(item)
        self._loading = False
        if keep_selection:
            self.select(keep_selection)

    def _build(self, node: dict) -> QTreeWidgetItem:
        item = QTreeWidgetItem()
        item.setText(0, node.get("name") or "")
        item.setData(0, ROLE_ID, node.get("id"))
        # O Qt converte dict guardado em item, e o que volta nao e o mesmo objeto da
        # arvore. Por isso o item guarda so o id, e o dicionario real vem deste registro.
        self._by_id[node.get("id")] = node
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)

        for child in self._ordenados(node.get("items") or []):
            item.addChild(self._build(child))

        # Exemplo salvo entra como filho do request, do jeito que o Postman mostra: ele e
        # daquele request, e nao um item solto da collection. Nao existe no tree_data como
        # no de arvore, entao aqui nasce um involucro so pra tela, com ponteiro pro
        # exemplo de verdade e pro request dono.
        for exemplo in node.get("examples") or []:
            filho = QTreeWidgetItem()
            filho.setText(0, exemplo.get("name") or "exemplo")
            eid = exemplo.get("id") or ""
            filho.setData(0, ROLE_ID, eid)
            self._by_id[eid] = {
                "type": "example",
                "id": eid,
                "name": exemplo.get("name") or "exemplo",
                "_exemplo": exemplo,
                "_pai": node,
            }
            filho.setFlags(
                (filho.flags() | Qt.ItemFlag.ItemIsEditable)
                & ~Qt.ItemFlag.ItemIsDragEnabled
                & ~Qt.ItemFlag.ItemIsDropEnabled
            )
            item.addChild(filho)
        return item

    def _apply_expansion(self, item: QTreeWidgetItem) -> None:
        node = self._node(item)
        if node and node.get("type") != "request":
            item.setExpanded(bool(node.get("expanded")))
        for index in range(item.childCount()):
            self._apply_expansion(item.child(index))


    def _node_por_indice(self, index) -> dict | None:
        return self._by_id.get(index.data(ROLE_ID))

    def _node(self, item: QTreeWidgetItem | None) -> dict | None:
        if item is None:
            return None
        return self._by_id.get(item.data(0, ROLE_ID))

    def _on_click(self, item: QTreeWidgetItem, _column: int) -> None:
        node = self._node(item)
        if node and node.get("type") == "example":
            self.exemplo_aberto.emit(node)
            return
        if node and node.get("type") == "request":
            self.request_opened.emit(node)

    def _on_double_click(self, item: QTreeWidgetItem, _column: int) -> None:
        node = self._node(item)
        if node and node.get("type") != "request":
            item.setExpanded(not item.isExpanded())

    def _on_renamed(self, item: QTreeWidgetItem, _column: int) -> None:
        if self._loading:
            return
        node = self._node(item)
        if node and item.text(0) and item.text(0) != node.get("name"):
            node["name"] = item.text(0)
            if node.get("type") == "example":
                node["_exemplo"]["name"] = item.text(0)
            self.tree_changed.emit()

    def _set_expanded(self, item: QTreeWidgetItem, value: bool) -> None:
        node = self._node(item)
        self.tree.viewport().update()
        if self._loading:
            return
        if node and node.get("type") != "request":
            node["expanded"] = value

    def _montar_menu_ordem(self) -> None:
        from PySide6.QtGui import QAction

        self.menu_ordem.clear()
        for modo, rotulo in self.MODOS.items():
            acao = QAction(rotulo, self)
            acao.setCheckable(True)
            acao.setChecked(modo == self.ordenacao)
            acao.triggered.connect(lambda _=False, m=modo: self.definir_ordenacao(m))
            self.menu_ordem.addAction(acao)

        self.menu_ordem.addSeparator()
        aplicar = QAction("Aplicar esta ordem nos arquivos", self)
        aplicar.setEnabled(self.ordenacao != "manual")
        aplicar.setToolTip(
            "Grava a ordem exibida como a ordem real. Ate fazer isso, ordenar e so uma "
            "forma de olhar, e a ordem dos arquivos continua a sua."
        )
        aplicar.triggered.connect(self.ordem_aplicada.emit)
        self.menu_ordem.addAction(aplicar)

    def _collapse_all(self) -> None:
        self.tree.collapseAll()
        for node in self._iter_nodes():
            if node.get("type") != "request":
                node["expanded"] = False


    def _menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        node = self._node(item)
        menu = QMenu(self)

        # criar aparece em qualquer item. Clicando num request, o novo item nasce na
        # pasta dele, que e o que a pessoa quer quando clica ali.
        if node:
            destino = node if node.get("type") != "request" else self.find_parent(node)
            if destino is not None:
                onde = destino.get("name") or ""
                menu.addAction(
                    f"Novo request em {onde}", lambda: self.add_child(destino, "request")
                )
                menu.addAction(
                    f"Nova pasta em {onde}", lambda: self.add_child(destino, "folder")
                )
                menu.addSeparator()
        if node and node.get("type") == "example":
            menu.addAction("Abrir", lambda: self.exemplo_aberto.emit(node))
            menu.addAction("Renomear", lambda: self.rename(node))
            menu.addSeparator()
            menu.addAction("Excluir exemplo", lambda: self.exemplo_exclusao_pedida.emit(node))
            menu.exec(self.tree.viewport().mapToGlobal(pos))
            return

        if node and node.get("type") == "request":
            menu.addAction("Abrir", lambda: self.request_opened.emit(node))
            menu.addAction("Duplicar request", lambda: self.duplicate(node))
            menu.addSeparator()
            menu.addAction("Copiar como curl", lambda: self.curl_pedido.emit(node))
            menu.addAction("Gerar codigo", lambda: self.codigo_pedido.emit(node))
            menu.addSeparator()
            marcado = bool(node.get("favorite"))
            menu.addAction(
                "Remover dos favoritos" if marcado else "Favoritar",
                lambda: self.alternar_favorito(node),
            )
            menu.addSeparator()
        if node and node.get("type") != "request":
            menu.addAction("Auth desta " + ("collection" if node.get("type") == "collection" else "pasta"),
                           lambda: self.auth_pedida.emit(node))
            menu.addSeparator()
        if node:
            menu.addAction("Renomear", lambda: self.rename(node))
            menu.addAction("Duplicar", lambda: self.duplicate(node))
            menu.addSeparator()
            menu.addAction("Excluir", lambda: self.exclusao_pedida.emit(node))
        else:
            menu.addAction("Nova collection", self.btn_new.click)

        menu.exec(self.tree.viewport().mapToGlobal(pos))


    def _iter_nodes(self, items=None):
        for node in items if items is not None else (self.tree_data.get("collections") or []):
            yield node
            yield from self._iter_nodes(node.get("items") or [])

    def find_parent(self, target: dict, items=None, current=None):
        for node in items if items is not None else (self.tree_data.get("collections") or []):
            if node is target:
                return current
            found = self.find_parent(target, node.get("items") or [], node)
            if found is not None or any(child is target for child in node.get("items") or []):
                return found if found is not None else node
        return None

    def add_child(self, parent: dict, kind: str) -> dict:
        self.guardar_estado("criar item")
        from ..core.workspaces import new_id

        if kind == "request":
            node = {
                "id": new_id("req"),
                "type": "request",
                "name": "Novo request",
                "method": "GET",
                "url": "",
                "params": [],
                "headers": [],
                "body": {"mode": "none", "raw": ""},
                "docs": "",
            }
        else:
            node = {"id": new_id("fld"), "type": "folder", "name": "Nova pasta", "expanded": True, "items": []}

        parent.setdefault("items", []).append(node)
        parent["expanded"] = True
        self.refresh()
        self.tree_changed.emit()
        self.rename(node)
        return node

    def add_collection(self, name: str) -> dict:
        from ..core.workspaces import new_id

        node = {"id": new_id("col"), "type": "collection", "name": name, "expanded": True, "items": []}
        self.tree_data.setdefault("collections", []).append(node)
        self.refresh()
        self.tree_changed.emit()
        return node

    def alternar_favorito(self, node: dict) -> None:
        node["favorite"] = not node.get("favorite")
        self.tree.viewport().update()
        self.tree_changed.emit()
        self.favorito_mudou.emit()

    def duplicate(self, node: dict) -> None:
        self.guardar_estado(f"duplicar {node.get('name')}")
        import copy

        from ..core.workspaces import new_id

        from ..core import examples

        clone = copy.deepcopy(node)

        def reid(target: dict) -> None:
            target["id"] = new_id(target.get("type", "item")[:3])
            # o exemplo tambem ganha id novo: repetido, a arvore guardava so um dos dois
            # pelo id, e clicar no exemplo do original abria, renomeava ou excluia o da copia
            for exemplo in target.get("examples") or []:
                exemplo["id"] = examples.novo_id()
            for child in target.get("items") or []:
                reid(child)

        reid(clone)
        clone["name"] = f"{node.get('name')} copia"
        parent = self.find_parent(node)
        siblings = parent["items"] if parent else self.tree_data["collections"]
        posicao = next((i for i, irmao in enumerate(siblings) if irmao is node), None)
        if posicao is None:
            # o item saiu da arvore por fora com a aba ainda aberta: index estourava
            # ValueError e o Duplicar da aba virava caixa de erro
            self._desfazer.pop()
            return
        siblings.insert(posicao + 1, clone)
        self.refresh()
        self.tree_changed.emit()
        # quem duplica um request quer mexer na copia agora, entao ela ja abre. Pasta e
        # collection nao abrem nada, ai seria uma enxurrada de abas.
        if clone.get("type") == "request":
            self.request_opened.emit(clone)

    def remove(self, node: dict) -> None:
        self.guardar_estado(f"excluir {node.get('name')}")
        parent = self.find_parent(node)
        siblings = parent["items"] if parent else self.tree_data["collections"]
        if node in siblings:
            siblings.remove(node)
        self.refresh()
        self.tree_changed.emit()

    def rename(self, node: dict) -> None:
        item = self._item_by_id(node.get("id"))
        if item:
            self.tree.setCurrentItem(item)
            self.tree.editItem(item, 0)

    def expandir(self, node_id: str | None) -> None:
        item = self._item_by_id(node_id)
        if item is not None:
            item.setExpanded(True)

    def select(self, node_id: str) -> None:
        item = self._item_by_id(node_id)
        if item:
            self.tree.setCurrentItem(item)

    def current_node(self) -> dict | None:
        return self._node(self.tree.currentItem())

    def _item_by_id(self, node_id: str | None):
        if not node_id:
            return None
        iterator = self.tree.findItems("", Qt.MatchFlag.MatchContains | Qt.MatchFlag.MatchRecursive, 0)
        for item in iterator:
            if item.data(0, ROLE_ID) == node_id:
                return item
        return None

    def aplicar_ordenacao(self) -> str:
        """Grava a ordem exibida como a ordem real dos arquivos."""
        if self.ordenacao == "manual":
            return "a ordem ja e a manual, nao ha o que aplicar"

        self.guardar_estado(f"aplicar ordem {self.MODOS.get(self.ordenacao)}")

        def andar(items):
            novos = list(self._ordenados(items))
            items[:] = novos
            for node in items:
                if node.get("items"):
                    andar(node["items"])

        andar(self.tree_data.setdefault("collections", []))
        rotulo = self.MODOS.get(self.ordenacao, self.ordenacao)
        self.definir_ordenacao("manual")
        self.tree_changed.emit()
        return f"ordem {rotulo} aplicada nos arquivos"

    def rebuild_from_widget(self) -> None:
        """Refaz a arvore de dados a partir do que ficou na tela depois do arrastar."""

        def colher(item) -> dict | None:
            node = self._node(item)
            if node is None:
                return None
            if node.get("type") != "request":
                filhos = []
                for indice in range(item.childCount()):
                    filho = colher(item.child(indice))
                    if filho is not None:
                        filhos.append(filho)
                node["items"] = filhos
                node["expanded"] = item.isExpanded()
            else:
                node.pop("items", None)
            return node

        raiz = []
        for indice in range(self.tree.topLevelItemCount()):
            node = colher(self.tree.topLevelItem(indice))
            if node is None:
                continue
            if node.get("type") != "collection":
                # a regra de drop ja barra isso, mas se algo escapar o item volta pra
                # primeira collection em vez de mudar de tipo sozinho
                destino = next((n for n in raiz if n.get("type") == "collection"), None)
                if destino is not None:
                    destino.setdefault("items", []).append(node)
                    continue
            raiz.append(node)

        self.tree_data["collections"] = raiz
        self.refresh()
        self.tree_changed.emit()

    def apply_filter(self, text: str) -> None:
        query = (text or "").strip().lower()

        def visit(item: QTreeWidgetItem) -> bool:
            node = self._node(item)
            hay = f"{node.get('name', '')} {node.get('url', '')}".lower()
            visible = query in hay if query else True
            child_visible = False
            for index in range(item.childCount()):
                if visit(item.child(index)):
                    child_visible = True
            visible = visible or child_visible
            item.setHidden(not visible)
            if query and child_visible:
                item.setExpanded(True)
            return visible

        for index in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(index))

    def refresh_icon(self, node: dict) -> None:
        item = self._item_by_id(node.get("id"))
        if item and item.text(0) != node.get("name"):
            self._loading = True
            item.setText(0, node.get("name") or "")
            self._loading = False
        self.tree.viewport().update()
