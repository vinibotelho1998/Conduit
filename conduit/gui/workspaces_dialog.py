"""Gerenciador de workspaces: trocar, renomear, cor, duplicar, abrir pasta e excluir.

Era uma tabela de cinco colunas com seis botoes iguais embaixo. Tabela e a forma certa
pra comparar muitos valores do mesmo tipo, e aqui nao e isso: sao poucos itens, cada um
com um nome, uma cor e um resumo em prosa. Cartao le melhor esse formato, e libera a
coluna do "Ativo", que existia so pra escrever a palavra sim.

Os botoes tambem tinham todos o mesmo peso, inclusive o de excluir. Agora abrir e a acao
principal, o resto e secundario e o destrutivo fica sozinho do outro lado da barra.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core import workspaces as ws
from ..seed import EXAMPLES_ID
from . import icons, theme, tokens
from .request_editor import mono
from .widgets import conta

PAPEL_ID = Qt.ItemDataRole.UserRole

# Os nomes que aparecem no menu de cor, na mesma ordem de ws.COLORS.
NOMES_DE_COR = ["cinza", "verde", "laranja", "azul", "vermelho", "turquesa"]


def criar_workspace(pai, nome: str) -> dict | None:
    """Cria o workspace, e pergunta antes quando o nome e o de um que saiu da lista.

    Tirar da lista promete que da pra voltar depois, e o caminho de volta e criar com o
    mesmo nome, coisa que nenhuma tela contava: o conteudo antigo era adotado calado, e
    nao havia jeito de criar um vazio com aquele nome.
    """
    wid = ws.slug(nome)
    registrados = {w["id"] for w in ws.list_workspaces()["workspaces"]}
    outro_id = None
    if wid not in registrados and ws.ja_existe_no_disco(wid):
        caixa = QMessageBox(pai)
        caixa.setWindowTitle("Novo workspace")
        caixa.setText(f"Existe um workspace {nome} fora da lista.")
        caixa.setInformativeText(
            "Trazer de volta abre ele com o que tinha. Criar outro vazio deixa aquela "
            "pasta como esta e comeca um workspace novo."
        )
        trazer = caixa.addButton("Trazer de volta", QMessageBox.ButtonRole.AcceptRole)
        vazio = caixa.addButton("Criar outro vazio", QMessageBox.ButtonRole.ActionRole)
        caixa.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        caixa.setDefaultButton(trazer)
        caixa.exec()
        clicado = caixa.clickedButton()
        if clicado is vazio:
            outro_id = ws.id_livre(nome)
        elif clicado is not trazer:
            return None
    try:
        return ws.create_workspace(nome, wid=outro_id)
    except ValueError as exc:
        QMessageBox.warning(pai, "Novo workspace", str(exc))
        return None


def menu_de_cores(pai, atual: str, escolher) -> QMenu:
    """Menu com as cores desenhadas, no lugar de uma lista de nomes soltos.

    Escolher cor numa caixa que lista as palavras azul, verde e laranja obriga a pessoa a
    imaginar o resultado. Com o circulo desenhado ao lado, ela ve.
    """
    menu = QMenu(pai)
    for nome, cor in zip(NOMES_DE_COR, ws.COLORS):
        acao = QAction(nome, menu)
        acao.setIcon(icons.ponto_cor(cor, 14))
        acao.setCheckable(True)
        acao.setChecked(cor == atual)
        acao.triggered.connect(lambda _=False, c=cor: escolher(c))
        menu.addAction(acao)
    return menu


class Cartao(QWidget):
    """Uma linha da lista: ponto na cor, nome, marca de ativo e o resumo embaixo."""

    cor_pedida = Signal(str)

    def __init__(self, entrada: dict, ativo: bool, resumo: str, parent=None):
        super().__init__(parent)
        self.entrada = entrada

        linha = QHBoxLayout(self)
        linha.setContentsMargins(10, 7, 10, 7)
        linha.setSpacing(10)

        self.ponto = QToolButton()
        self.ponto.setObjectName("silencioso")
        self.ponto.setIconSize(QSize(16, 16))
        self.ponto.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ponto.setToolTip("Trocar a cor deste workspace")
        cor = entrada.get("color") or theme.DIM
        theme.ao_trocar_widget(self.ponto, lambda alvo, c=cor: alvo.setIcon(icons.ponto_cor(c, 16)))
        self.ponto.clicked.connect(self._abrir_cores)
        linha.addWidget(self.ponto, 0, Qt.AlignmentFlag.AlignVCenter)

        coluna = QVBoxLayout()
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(2)

        topo = QHBoxLayout()
        topo.setContentsMargins(0, 0, 0, 0)
        topo.setSpacing(8)

        nome = QLabel(entrada.get("name") or entrada["id"])
        theme.estilizar(nome, lambda: f"color: {theme.TEXT}; font-weight: 600; font-size: 10pt;")
        topo.addWidget(nome)

        if ativo:
            marca = QLabel("aberto")
            theme.estilizar(
                marca,
                lambda: f"color: {theme.OK}; background: {tokens.alfa(theme.OK, 0.15)};"
                f" border-radius: 8px; padding: 1px 8px; font-size: 8pt; font-weight: 600;",
            )
            topo.addWidget(marca)
        topo.addStretch(1)
        coluna.addLayout(topo)

        detalhe = QLabel(resumo)
        detalhe.setObjectName("hint")
        theme.estilizar(detalhe, lambda: f"color: {theme.FAINT}; font-size: 8pt;")
        coluna.addWidget(detalhe)
        linha.addLayout(coluna, 1)

        pasta = QLabel(Path(entrada.get("path") or "").name)
        pasta.setFont(mono(8))
        pasta.setToolTip(str(entrada.get("path") or ""))
        theme.estilizar(pasta, lambda: f"color: {theme.FAINT};")
        linha.addWidget(pasta, 0, Qt.AlignmentFlag.AlignVCenter)

    def _abrir_cores(self) -> None:
        menu = menu_de_cores(self, self.entrada.get("color") or "", self.cor_pedida.emit)
        menu.exec(self.ponto.mapToGlobal(self.ponto.rect().bottomLeft()))


class WorkspacesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Workspaces")
        self.resize(720, 480)

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(18, 16, 18, 14)
        raiz.setSpacing(12)

        cabecalho = QHBoxLayout()
        cabecalho.setContentsMargins(0, 0, 0, 0)
        titulo = QLabel("Workspaces")
        theme.estilizar(titulo, lambda: f"font-size: 15pt; font-weight: 700; color: {theme.TEXT};")
        cabecalho.addWidget(titulo)
        cabecalho.addStretch(1)

        self.btn_novo = QPushButton("Novo workspace")
        self.btn_novo.clicked.connect(self.criar)
        cabecalho.addWidget(self.btn_novo)
        raiz.addLayout(cabecalho)

        texto = QLabel(
            "Cada um e uma pasta isolada, com collections, ambientes, cofre e historico "
            "proprios. Nada vaza de um pro outro."
        )
        texto.setObjectName("hint")
        texto.setWordWrap(True)
        raiz.addWidget(texto)

        self.lista = QListWidget()
        self.lista.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.lista.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.lista.setUniformItemSizes(False)
        theme.estilizar(
            self.lista,
            lambda: f"QListWidget {{ background: {theme.PANEL};"
            f" border: 1px solid {theme.BORDER}; border-radius: 10px; padding: 5px;"
            f" outline: 0; }}"
            f"QListWidget::item {{ border-radius: 7px; margin: 1px 2px; }}"
            f"QListWidget::item:hover {{ background: {theme.PANEL2}; }}"
            f"QListWidget::item:selected {{ background: {theme.SEL}; }}",
        )
        self.lista.itemDoubleClicked.connect(lambda *_: self.usar())
        self.lista.itemSelectionChanged.connect(self._ajustar_botoes)
        self.lista.currentItemChanged.connect(lambda *_: self._ajustar_botoes())
        self.lista.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.lista.customContextMenuRequested.connect(self._menu)
        raiz.addWidget(self.lista, 1)

        barra = QHBoxLayout()
        barra.setSpacing(6)

        self.btn_usar = QPushButton("Abrir este")
        self.btn_usar.setObjectName("primario")
        self.btn_usar.setToolTip("Tambem da pra abrir com duplo clique no cartao")
        self.btn_usar.clicked.connect(self.usar)
        barra.addWidget(self.btn_usar)

        # um respiro depois da acao principal: sem ele os cinco botoes leem como uma
        # fila so, e o olho nao separa o que abre do que so ajusta
        barra.addSpacing(10)

        self.secundarios = []
        for rotulo, alvo in (
            ("Renomear", self.renomear),
            ("Cor", self.trocar_cor),
            ("Duplicar", self.duplicar),
            ("Abrir pasta", self.abrir_pasta),
        ):
            botao = QPushButton(rotulo)
            botao.clicked.connect(alvo)
            barra.addWidget(botao)
            self.secundarios.append(botao)
        barra.addStretch(1)

        # sozinho do outro lado da barra: acao que nao se desfaz nao pode ficar
        # encostada nas que se desfazem
        self.btn_excluir = QPushButton("Excluir")
        self.btn_excluir.setObjectName("perigo")
        self.btn_excluir.clicked.connect(self.excluir)
        barra.addWidget(self.btn_excluir)
        raiz.addLayout(barra)

        # Resumo e Fechar dividem a mesma linha. Empilhados, viravam duas faixas de
        # rodape embaixo da barra de acoes, e o caminho longo ainda quebrava em duas
        # linhas: tres alturas de texto pra dizer onde fica a pasta.
        rodape = QHBoxLayout()
        rodape.setSpacing(10)

        self.resumo = QLabel("")
        self.resumo.setObjectName("hint")
        self.resumo.setWordWrap(False)
        self.resumo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        rodape.addWidget(self.resumo, 1)

        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        botoes.button(QDialogButtonBox.StandardButton.Close).setText("Fechar")
        botoes.rejected.connect(self.reject)
        botoes.accepted.connect(self.accept)
        rodape.addWidget(botoes, 0)
        raiz.addLayout(rodape)

        self.recarregar()
        # o teclado nasce na lista, e nao no primeiro botao do cabecalho: o anel de foco
        # num botao de acao logo na abertura sugere que ele e o que voce deve apertar
        self.lista.setFocus()

    # ------------------------------------------------------------------------- montagem

    def recarregar(self, selecionar: str | None = None) -> None:
        registro = ws.list_workspaces()
        self.entradas = registro["workspaces"]
        ativo = registro.get("active")

        self.lista.clear()
        for entrada in self.entradas:
            cartao = Cartao(entrada, entrada["id"] == ativo, self._contar(entrada))
            cartao.cor_pedida.connect(
                lambda cor, wid=entrada["id"]: self._aplicar_cor(wid, cor)
            )
            item = QListWidgetItem()
            item.setData(PAPEL_ID, entrada["id"])
            item.setSizeHint(cartao.sizeHint())
            self.lista.addItem(item)
            self.lista.setItemWidget(item, cartao)

        alvo = selecionar or ativo
        for indice in range(self.lista.count()):
            if self.lista.item(indice).data(PAPEL_ID) == alvo:
                self.lista.setCurrentRow(indice)
                break

        # So a contagem no rotulo. O caminho inteiro vai pro balao e pro botao Abrir
        # pasta: escrito na tela ele ocupava duas linhas e ainda empurrava a largura do
        # dialogo, porque QLabel entrega o texto inteiro como largura minima.
        plural = "workspace" if len(self.entradas) == 1 else "workspaces"
        self.resumo.setText(
            f"{len(self.entradas)} {plural} em {Path(ws.WORKSPACES_DIR).parent.name}"
        )
        self.resumo.setToolTip(str(ws.WORKSPACES_DIR))
        self._ajustar_botoes()

    def _ajustar_botoes(self) -> None:
        entrada = self.selecionado()
        tem = entrada is not None
        aberto = tem and entrada["id"] == ws.list_workspaces().get("active")
        for botao in self.secundarios:
            botao.setEnabled(tem)
        self.btn_usar.setEnabled(tem and not aberto)
        self.btn_usar.setText("Ja esta aberto" if aberto else "Abrir este")
        # o ultimo workspace nao se exclui: sem nenhum, o app abriria numa tela sem raiz
        self.btn_excluir.setEnabled(tem and len(self.entradas) > 1)
        self.btn_excluir.setToolTip(
            "" if len(self.entradas) > 1 else "Nao da pra excluir o unico workspace"
        )

    @staticmethod
    def _contar(entrada: dict) -> str:
        raiz = Path(entrada.get("path") or "")
        colecoes = raiz / "collections"
        if not colecoes.exists():
            return "ainda vazio"
        requests = len([p for p in colecoes.rglob("*.yaml") if not p.name.startswith("_")])
        pastas = len(list(colecoes.rglob("_folder.yaml")))
        cols = len(list(colecoes.glob("*/_collection.yaml")))
        if not cols and not requests:
            return "ainda vazio"

        partes = [conta(cols, "collection", "collections"), conta(requests, "request", "requests")]
        if pastas:
            partes.insert(1, conta(pastas, "pasta", "pastas"))
        if (raiz / ".secrets" / "vault.dbx").exists():
            partes.append("cofre")
        return "   ·   ".join(partes)

    def selecionado(self) -> dict | None:
        item = self.lista.currentItem()
        if item is None:
            return None
        wid = item.data(PAPEL_ID)
        return next((e for e in self.entradas if e["id"] == wid), None)

    def _menu(self, posicao) -> None:
        entrada = self.selecionado()
        menu = QMenu(self)
        menu.addAction("Novo workspace", self.criar)
        if entrada:
            menu.addSeparator()
            menu.addAction("Abrir este", self.usar)
            menu.addAction("Renomear", self.renomear)
            menu.addAction("Duplicar", self.duplicar)
            menu.addAction("Abrir pasta no explorador", self.abrir_pasta)
            menu.addSeparator()
            menu.addAction("Excluir", self.excluir)
        menu.exec(self.lista.viewport().mapToGlobal(posicao))

    # --------------------------------------------------------------------------- acoes

    def criar(self) -> None:
        nome, ok = QInputDialog.getText(self, "Novo workspace", "Nome do workspace")
        nome = (nome or "").strip()
        if not ok or not nome:
            return
        entrada = criar_workspace(self, nome)
        if entrada is not None:
            self.recarregar(entrada["id"])

    def renomear(self) -> None:
        entrada = self.selecionado()
        if not entrada:
            return
        nome, ok = QInputDialog.getText(
            self, "Renomear workspace", "Nome", text=entrada.get("name") or ""
        )
        if ok and nome.strip():
            ws.rename_workspace(entrada["id"], nome.strip())
            self.recarregar(entrada["id"])

    def trocar_cor(self) -> None:
        entrada = self.selecionado()
        if not entrada:
            return
        menu = menu_de_cores(
            self, entrada.get("color") or "", lambda cor: self._aplicar_cor(entrada["id"], cor)
        )
        botao = self.secundarios[1]
        menu.exec(botao.mapToGlobal(botao.rect().topLeft()))

    def _aplicar_cor(self, wid: str, cor: str) -> None:
        ws.set_color(wid, cor)
        self.recarregar(wid)
        janela = self.parent()
        if janela is not None and hasattr(janela, "_pintar_botao_workspace"):
            if getattr(janela, "workspace_id", None) == wid:
                janela._pintar_botao_workspace(ws.get_workspace(wid))

    def duplicar(self) -> None:
        entrada = self.selecionado()
        if not entrada:
            return
        nome, ok = QInputDialog.getText(
            self, "Duplicar workspace", "Nome da copia", text=f"{entrada.get('name')} copia"
        )
        if not ok or not nome.strip():
            return
        try:
            novo = ws.duplicate_workspace(entrada["id"], nome.strip())
        except ValueError as exc:
            QMessageBox.warning(self, "Duplicar", str(exc))
            return
        QMessageBox.information(
            self,
            "Duplicado",
            "A copia levou collections, pastas, ambientes e globais.\n\n"
            "O cofre e o historico ficaram no original de proposito: segredo nao se "
            "duplica sem alguem pedir, e historico e do workspace que executou.",
        )
        self.recarregar(novo["id"])

    def abrir_pasta(self) -> None:
        entrada = self.selecionado()
        if entrada:
            QDesktopServices.openUrl(QUrl.fromLocalFile(entrada["path"]))

    def usar(self) -> None:
        entrada = self.selecionado()
        if not entrada:
            return
        ws.set_active(entrada["id"])
        janela = self.parent()
        if janela is not None and hasattr(janela, "load_workspace"):
            janela.load_workspace(entrada["id"])
        self.recarregar(entrada["id"])

    def excluir(self) -> None:
        entrada = self.selecionado()
        if not entrada:
            return
        if len(self.entradas) <= 1:
            QMessageBox.information(self, "Excluir", "Nao da pra excluir o unico workspace.")
            return

        caixa = QMessageBox(self)
        caixa.setWindowTitle("Excluir workspace")
        caixa.setIcon(QMessageBox.Icon.Warning)
        caixa.setText(f"Excluir o workspace {entrada.get('name')}?")
        caixa.setInformativeText(
            f"{self._contar(entrada)}\n\n"
            "Tirar da lista deixa a pasta intacta no disco. Pra voltar, crie um "
            f"workspace chamado {entrada['id']} e escolha Trazer de volta.\n"
            "Mover pra lixeira tira a pasta do lugar, mas nao apaga: ela vai pra "
            "lixeira do Conduit e pode ser recuperada na mao."
        )
        so_lista = caixa.addButton("Tirar da lista", QMessageBox.ButtonRole.AcceptRole)
        com_arquivos = caixa.addButton("Mover pra lixeira", QMessageBox.ButtonRole.DestructiveRole)
        cancelar = caixa.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        caixa.setDefaultButton(cancelar)
        caixa.exec()

        clicado = caixa.clickedButton()
        if clicado not in (so_lista, com_arquivos):
            return

        # O aberto e solto antes: o indice do historico fica aberto enquanto ele esta na
        # tela, e no Windows pasta com arquivo aberto nao sai do lugar. Solto tambem pro
        # caso de so tirar da lista, senao a janela seguia olhando um workspace que o
        # registro nao conhece mais.
        janela = self.parent()
        if getattr(janela, "workspace_id", None) == entrada["id"] and hasattr(janela, "load_workspace"):
            outro = next(e for e in self.entradas if e["id"] != entrada["id"])
            janela.load_workspace(outro["id"])
            if janela.workspace_id == entrada["id"]:
                # a troca foi recusada pra nao perder o que o disco nao gravou, e ele segue
                # aberto: excluir agora levava junto a unica copia dessa alteracao
                return

        try:
            resultado = ws.delete_workspace(entrada["id"], apagar_arquivos=clicado is com_arquivos)
        except OSError as exc:
            QMessageBox.warning(
                self,
                "Excluir",
                "A pasta nao pode ser movida agora, entao nada foi excluido.\n\n"
                "Feche o que estiver usando algum arquivo dela, como o explorador aberto "
                f"la dentro, e tente de novo.\n\n{exc}",
            )
            self.recarregar()
            return
        if entrada["id"] == EXAMPLES_ID:
            # quem tira os exemplos da lista nao quer ver eles de volta na proxima abertura
            ws.write_preferences(exemplosDispensados=True)
        if resultado["lixeira"]:
            QMessageBox.information(
                self, "Excluido", f"A pasta foi movida para\n{resultado['lixeira']}"
            )
        self.recarregar()
