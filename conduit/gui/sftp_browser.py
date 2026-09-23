"""Navegador de um servidor SFTP, aberto como aba na area principal.

Por que aba e nao painel lateral. A lateral tem 340 pixels e quatro colunas de listagem
nao cabem ali sem virar sopa. Navegar arquivo e a tarefa principal enquanto ela dura,
entao ela merece o mesmo espaco que um request: a lateral lista os servidores, a aba faz
o trabalho. E o mesmo desenho que o resto do app ja usa.

Nada de rede na thread da interface. Toda chamada ao servidor passa por `Tarefa`, que
roda no pool e devolve o resultado por sinal. Sem isso, um servidor lento congelava a
janela inteira, inclusive as abas de request que nao tem nada a ver com o SFTP.
"""

from __future__ import annotations

import posixpath
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QColor, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core import sftp
from . import icons, theme
from .highlight import CodeHighlighter, guess_language
from .request_editor import mono
from .numeros import EditorNumerado
from .splitter import Divisor
from .widgets import cabecalho_a_esquerda, conta

PAPEL_ENTRADA = Qt.ItemDataRole.UserRole
PAPEL_ORDEM = Qt.ItemDataRole.UserRole + 1


class ItemOrdenavel(QTableWidgetItem):
    """Celula que ordena pelo valor bruto, e nao pelo texto da tela.

    Pelo texto, 9 KB vinha depois de 10 KB e 31/12 antes de 01/01. A pasta fica
    sempre antes do arquivo, nos dois sentidos, como todo gerenciador de arquivo faz.
    """

    def __lt__(self, outro):  # noqa: D105
        meu, dele = self.data(PAPEL_ORDEM), outro.data(PAPEL_ORDEM)
        if meu is None or dele is None:
            return super().__lt__(outro)
        if meu[0] != dele[0]:
            tabela = self.tableWidget()
            decrescente = tabela is not None and (
                tabela.horizontalHeader().sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
            )
            return (meu[0] < dele[0]) != decrescente
        return meu[1] < dele[1]

# Extensoes que vale a pena abrir dentro do app. O resto se baixa: espiar um .zip como
# texto nao ajuda ninguem e ainda enche a tela de lixo.
TEXTO = {
    ".txt", ".log", ".csv", ".tsv", ".json", ".xml", ".yaml", ".yml", ".ini", ".conf",
    ".cfg", ".md", ".sql", ".sh", ".py", ".js", ".ts", ".html", ".css", ".env", ".properties",
    ".rem", ".ret", ".dat",
}


class _Sinais(QObject):
    pronto = Signal(object)
    falhou = Signal(str)
    # a excecao inteira, pra quem precisa do que vem dentro dela: a impressao digital
    # de uma chave desconhecida, por exemplo, nao cabe numa mensagem de texto
    estourou = Signal(object)
    andou = Signal(int, int)


class Tarefa(QRunnable):
    """Uma chamada ao servidor, fora da thread da interface.

    O autoDelete fica desligado pelo mesmo motivo do envio HTTP: com ele ligado o Qt
    destroi o runnable no fim do run, o objeto de sinal morre junto e o resultado se
    perde antes de chegar na tela. Quem segura a referencia e o navegador.
    """

    def __init__(self, funcao, *args, **kwargs):
        super().__init__()
        self.setAutoDelete(False)
        self.funcao = funcao
        self.args = args
        self.kwargs = kwargs
        self.sinais = _Sinais()

    @Slot()
    def run(self) -> None:
        try:
            self.sinais.pronto.emit(self.funcao(*self.args, **self.kwargs))
        except sftp.ErroSftp as erro:
            self.sinais.estourou.emit(erro)
            self.sinais.falhou.emit(str(erro))
        except Exception as erro:  # noqa: BLE001
            self.sinais.estourou.emit(erro)
            self.sinais.falhou.emit(f"{type(erro).__name__}: {erro}")


def _botao(texto: str, dica: str, acao, icone=None) -> QToolButton:
    alvo = QToolButton()
    alvo.setObjectName("silencioso")
    alvo.setToolTip(dica)
    alvo.setCursor(Qt.CursorShape.PointingHandCursor)
    if icone is not None:
        alvo.setIconSize(QSize(16, 16))
        theme.ao_trocar_widget(alvo, lambda w, d=icone: w.setIcon(d()))
    else:
        alvo.setText(texto)
    alvo.clicked.connect(acao)
    return alvo


def _pintar_listagem(tabela) -> None:
    """Icone e cor de cada linha pela paleta de agora. Roda ao listar e a cada troca de
    tema: com a cor pronta dentro da celula, a lista ficava no tema anterior."""
    texto, medio, fraco = QColor(theme.TEXT), QColor(theme.DIM), QColor(theme.FAINT)
    for linha in range(tabela.rowCount()):
        nome = tabela.item(linha, 0)
        entrada = nome.data(PAPEL_ENTRADA) if nome is not None else None
        if entrada is None:
            continue
        if entrada.link:
            nome.setIcon(icons.icone_link())
        elif entrada.pasta:
            nome.setIcon(icons.icone_pasta())
            nome.setForeground(texto)
        else:
            nome.setIcon(icons.icone_arquivo())
        for coluna, cor in ((1, medio), (2, medio), (3, fraco)):
            item = tabela.item(linha, coluna)
            if item is not None:
                item.setForeground(cor)


class SftpBrowser(QWidget):
    """A aba de um servidor conectado."""

    fechou = Signal()
    recado = Signal(str, int)   # mensagem, milissegundos
    # a sessao caiu por baixo, numa suspensao do notebook ou pelo servidor
    caiu = Signal()
    reconectar_pedido = Signal(str)  # a pasta em que estava, pra voltar nela

    def __init__(self, conexao: sftp.Conexao, parent=None):
        super().__init__(parent)
        self.conexao = conexao
        self.caminho = "/"
        self.ocultos = False
        self.pool = QThreadPool.globalInstance()
        self._tarefas: set = set()
        self._historico: list[str] = []
        self._ocupado = False

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(12, 10, 12, 0)
        raiz.setSpacing(7)

        raiz.addWidget(self._montar_barra())
        raiz.addWidget(self._montar_trilha())

        self.divisor = Divisor(Qt.Orientation.Vertical)
        self.divisor.addWidget(self._montar_tabela())
        self.divisor.addWidget(self._montar_espiada())
        self.divisor.setChildrenCollapsible(True)
        # a previa nasce escondida, e nao apenas colapsada: o painel tem altura minima
        # propria, entao colapsar pelo divisor ainda deixava uma caixa vazia na tela
        self.caixa_espiada.hide()
        raiz.addWidget(self.divisor, 1)

        raiz.addWidget(self._montar_rodape())

        QShortcut(QKeySequence("Backspace"), self, self.subir)
        QShortcut(QKeySequence.StandardKey.Refresh, self, self.recarregar)
        # Ctrl+L mora na janela, que chama _editar_caminho com esta aba na frente: dois
        # donos pro mesmo atalho o Qt trata como ambiguo, e nenhum dos dois disparava
        for tecla, acao in (
            (QKeySequence.StandardKey.Delete, self.excluir),
            (QKeySequence("F2"), self.renomear),
            (QKeySequence("Return"), self._abrir_selecao),
            (QKeySequence("Enter"), self._abrir_selecao),
        ):
            atalho = QShortcut(tecla, self.tabela, acao)
            atalho.setContext(Qt.ShortcutContext.WidgetShortcut)

    # ------------------------------------------------------------------------- montagem

    def _montar_barra(self) -> QWidget:
        barra = QWidget()
        linha = QHBoxLayout(barra)
        linha.setContentsMargins(0, 0, 0, 0)
        linha.setSpacing(6)

        self.alvo = QLabel(self.conexao.perfil.rotulo())
        self.alvo.setFont(mono(9))
        self.alvo.setToolTip(
            f"chave do servidor  {self.conexao.digital}" if self.conexao.digital else ""
        )
        theme.estilizar(self.alvo, lambda: f"color: {theme.TEXT}; font-weight: 600;")
        linha.addWidget(self.alvo)

        self.estado = QLabel("conectado")
        theme.estilizar(
            self.estado,
            lambda: f"color: {theme.OK}; font-size: 8pt; font-weight: 600;",
        )
        linha.addWidget(self.estado)
        self.btn_reconectar = _botao(
            "Reconectar", "abrir a sessao de novo e voltar pra esta pasta",
            lambda: self.reconectar_pedido.emit(self.caminho),
        )
        self.btn_reconectar.hide()
        linha.addWidget(self.btn_reconectar)
        linha.addStretch(1)

        linha.addWidget(_botao("", "voltar uma pasta,  Backspace", self.subir, icons.icone_subir))
        linha.addWidget(_botao("", "recarregar,  F5", self.recarregar, icons.icone_recarregar))

        self.btn_ocultos = _botao("", "mostrar arquivos ocultos", self._alternar_ocultos, icons.icone_oculto)
        self.btn_ocultos.setCheckable(True)
        linha.addWidget(self.btn_ocultos)

        linha.addWidget(_botao("Nova pasta", "criar uma pasta aqui", self.nova_pasta))
        # Baixar e a acao mais comum, e morava so no botao direito. Enviar ganhou o
        # "arquivo": sozinho, lia como o Enviar do request, que manda a requisicao.
        self.btn_baixar = _botao("Baixar", "trazer os arquivos marcados pro computador", self.baixar)
        self.btn_baixar.setEnabled(False)
        linha.addWidget(self.btn_baixar)
        linha.addWidget(_botao("Enviar arquivo", "mandar um arquivo do computador pra ca", self.enviar))
        return barra

    def _montar_trilha(self) -> QWidget:
        caixa = QWidget()
        caixa.setFixedHeight(30)
        self.trilha = QHBoxLayout(caixa)
        self.trilha.setContentsMargins(0, 0, 0, 0)
        self.trilha.setSpacing(0)

        self.campo_caminho = QLineEdit()
        self.campo_caminho.setFont(mono(9))
        self.campo_caminho.setPlaceholderText("/caminho/no/servidor")
        self.campo_caminho.returnPressed.connect(self._ir_pro_campo)
        self.campo_caminho.hide()
        return caixa

    def _montar_tabela(self) -> QWidget:
        self.tabela = QTableWidget(0, 4)
        self.tabela.setHorizontalHeaderLabels(["Nome", "Tamanho", "Modificado", "Permissoes"])
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.setShowGrid(False)
        self.tabela.setAlternatingRowColors(False)
        self.tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabela.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        cabecalho = self.tabela.horizontalHeader()
        cabecalho.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        # cabecalho centralizado sobre coluna esticada fica boiando longe do dado que
        # ele nomeia; o tamanho segue a direita porque numero se le pela unidade
        cabecalho_a_esquerda(self.tabela)
        self.tabela.horizontalHeaderItem(1).setTextAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.tabela.setColumnWidth(1, 96)
        self.tabela.setColumnWidth(2, 118)
        self.tabela.setColumnWidth(3, 108)
        self.tabela.setWordWrap(False)
        # ordenar clicando no cabecalho: numa pasta de retorno de banco com centenas de
        # arquivos, achar o mais recente era ler a coluna Modificado inteira
        self.tabela.setSortingEnabled(True)
        self.tabela.horizontalHeader().setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        self.tabela.itemDoubleClicked.connect(self._abrir_item)
        self.tabela.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabela.customContextMenuRequested.connect(self._menu)
        self.tabela.itemSelectionChanged.connect(self._contar_selecao)
        theme.ao_trocar_widget(self.tabela, _pintar_listagem)
        return self.tabela

    def _montar_espiada(self) -> QWidget:
        caixa = QWidget()
        layout = QVBoxLayout(caixa)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        topo = QWidget()
        topo.setFixedHeight(28)
        tl = QHBoxLayout(topo)
        tl.setContentsMargins(2, 0, 0, 0)
        tl.setSpacing(6)
        self.espiada_nome = QLabel("")
        # nome de arquivo vem do servidor, e com cara de tag viraria HTML que carrega
        # imagem de caminho de rede, ver widgets.dica_de_fora
        self.espiada_nome.setTextFormat(Qt.TextFormat.PlainText)
        self.espiada_nome.setObjectName("sectionTitle")
        tl.addWidget(self.espiada_nome)
        tl.addStretch(1)
        tl.addWidget(_botao("Fechar", "fechar a previa", self.fechar_espiada))
        layout.addWidget(topo)

        self.espiada = EditorNumerado()
        self.espiada.setReadOnly(True)
        self.espiada.setFont(mono(9))
        self.espiada.setFrameShape(QFrame.Shape.NoFrame)
        self.espiada.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.realce = CodeHighlighter(self.espiada.document(), "none")
        layout.addWidget(self.espiada, 1)

        self.caixa_espiada = caixa
        return caixa

    def _montar_rodape(self) -> QWidget:
        caixa = QWidget()
        caixa.setFixedHeight(28)
        linha = QHBoxLayout(caixa)
        linha.setContentsMargins(2, 0, 2, 0)
        linha.setSpacing(10)

        self.resumo = QLabel("")
        self.resumo.setTextFormat(Qt.TextFormat.PlainText)
        self.resumo.setObjectName("hint")
        linha.addWidget(self.resumo)
        linha.addStretch(1)

        self.barra = QProgressBar()
        self.barra.setFixedWidth(180)
        self.barra.setTextVisible(False)
        self.barra.hide()
        linha.addWidget(self.barra)

        self.transferindo = QLabel("")
        self.transferindo.setTextFormat(Qt.TextFormat.PlainText)
        self.transferindo.setObjectName("hint")
        self.transferindo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        linha.addWidget(self.transferindo)
        return caixa

    # ------------------------------------------------------------------------ navegacao

    def comecar(self, caminho: str = "") -> None:
        if caminho:
            self.ir_para(caminho)
            return
        self._rodar(self.conexao.inicio, ao_pronto=self.ir_para)

    def ir_para(self, caminho: str) -> None:
        alvo = posixpath.normpath(caminho or "/")
        if self._ocupado:
            # Trocar a pasta por dentro durante uma transferencia deixava a tela na pasta
            # anterior: renomear, enviar e nova pasta caiam na pasta que nao estava na tela
            self.recado.emit(f"espere terminar: {self.estado.text()}", 5000)
            return
        if self.caminho and alvo != self.caminho:
            self._historico.append(self.caminho)
        self.caminho = alvo
        self.recarregar()

    def subir(self) -> None:
        if self.caminho != "/":
            self.ir_para(sftp.pai(self.caminho))

    def recarregar(self) -> None:
        if self._ocupado:
            return
        self._marcar_ocupado(True, f"lendo {self.caminho}")
        self._rodar(
            self.conexao.listar,
            self.caminho,
            self.ocultos,
            ao_pronto=self._mostrar,
            ao_falhar=self._falha_ao_listar,
        )

    def _falha_ao_listar(self, mensagem: str) -> None:
        self._marcar_ocupado(False)
        self.recado.emit(mensagem, 8000)
        # sem isso a tela fica mostrando o conteudo da pasta anterior com a barra de
        # caminho apontando pra pasta que falhou, que e a pior das duas informacoes
        self.tabela.setRowCount(0)
        # a trilha vai pra pasta que falhou e o motivo sai na cor de erro: com a trilha
        # na pasta anterior e o texto cinza, parecia que a pasta anterior estava vazia
        self._pintar_trilha()
        self.resumo.setText(mensagem)
        theme.estilizar(self.resumo, lambda: f"color: {theme.ERR};")

    def _mostrar(self, entradas: list) -> None:
        self._marcar_ocupado(False)
        self._pintar_trilha()
        # a ordenacao fica desligada enquanto a tabela enche, senao cada linha nova
        # trocava de lugar no meio do preenchimento
        self.tabela.setSortingEnabled(False)
        self.tabela.setRowCount(len(entradas))
        altura = theme.medida("linha_tabela")
        self._nomes = {entrada.nome: entrada for entrada in entradas}

        for indice, entrada in enumerate(entradas):
            grupo = 0 if entrada.pasta else 1
            nome = ItemOrdenavel(entrada.nome)
            nome.setData(PAPEL_ORDEM, (grupo, entrada.nome.lower()))
            nome.setData(PAPEL_ENTRADA, entrada)
            self.tabela.setItem(indice, 0, nome)

            tamanho = ItemOrdenavel(entrada.tamanho_legivel())
            tamanho.setData(PAPEL_ORDEM, (grupo, entrada.tamanho))
            tamanho.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self.tabela.setItem(indice, 1, tamanho)

            quando = ItemOrdenavel(entrada.quando())
            quando.setData(PAPEL_ORDEM, (grupo, entrada.modificado))
            self.tabela.setItem(indice, 2, quando)

            modo = QTableWidgetItem(entrada.permissoes())
            modo.setFont(mono(8))
            self.tabela.setItem(indice, 3, modo)
            self.tabela.setRowHeight(indice, altura)
        _pintar_listagem(self.tabela)
        self.tabela.setSortingEnabled(True)

        pastas = sum(1 for e in entradas if e.pasta)
        arquivos = len(entradas) - pastas
        partes = []
        if pastas:
            partes.append(conta(pastas, "pasta", "pastas"))
        if arquivos:
            partes.append(conta(arquivos, "arquivo", "arquivos"))
        if not partes:
            partes.append("pasta vazia" if self.ocultos else "nada visivel aqui")
        theme.estilizar(self.resumo, lambda: "")
        self.resumo.setText("   ·   ".join(partes))

    def _pintar_trilha(self) -> None:
        while self.trilha.count():
            item = self.trilha.takeAt(0)
            if item.widget() and item.widget() is not self.campo_caminho:
                item.widget().deleteLater()

        self.campo_caminho.hide()
        for rotulo, destino in sftp.migalhas(self.caminho):
            # depois da raiz, que ja e a barra, o separador lia "/ / saida"
            if self.trilha.count() and sftp.pai(destino) != "/":
                risco = QLabel("/")
                theme.estilizar(risco, lambda: f"color: {theme.FAINT};")
                self.trilha.addWidget(risco)
            pedaco = QToolButton()
            pedaco.setObjectName("silencioso")
            pedaco.setText(rotulo)
            pedaco.setCursor(Qt.CursorShape.PointingHandCursor)
            pedaco.clicked.connect(lambda _=False, d=destino: self.ir_para(d))
            self.trilha.addWidget(pedaco)
        self.trilha.addStretch(1)
        self.trilha.addWidget(self.campo_caminho)
        self.campo_caminho.hide()

    def _editar_caminho(self) -> None:
        """Ctrl+L troca a trilha por um campo, pra colar um caminho inteiro de uma vez."""
        self.campo_caminho.setText(self.caminho)
        self.campo_caminho.show()
        self.campo_caminho.setFocus()
        self.campo_caminho.selectAll()

    def _ir_pro_campo(self) -> None:
        destino = self.campo_caminho.text().strip()
        self.campo_caminho.hide()
        if destino:
            self.ir_para(destino)

    def _alternar_ocultos(self) -> None:
        self.ocultos = self.btn_ocultos.isChecked()
        self.recarregar()

    # --------------------------------------------------------------------------- acoes

    def _selecionadas(self) -> list:
        vistos, saida = set(), []
        for item in self.tabela.selectedItems():
            if item.column() != 0:
                continue
            entrada = item.data(PAPEL_ENTRADA)
            if entrada is not None and entrada.caminho not in vistos:
                vistos.add(entrada.caminho)
                saida.append(entrada)
        return saida

    def _contar_selecao(self) -> None:
        escolhidas = self._selecionadas()
        arquivos = [e for e in escolhidas if not e.pasta]
        self.btn_baixar.setEnabled(bool(arquivos))
        if len(escolhidas) > 1:
            total = sum(e.tamanho for e in arquivos)
            marca = sftp.Entrada(nome="", caminho="", tamanho=total).tamanho_legivel()
            self.transferindo.setText(f"{len(escolhidas)} selecionados   {marca}")
        else:
            self.transferindo.setText("")

    def _abrir_selecao(self) -> None:
        escolhidas = self._selecionadas()
        if len(escolhidas) != 1:
            return
        if escolhidas[0].pasta:
            self.ir_para(escolhidas[0].caminho)
        else:
            self.espiar(escolhidas[0])

    def _abrir_item(self, item) -> None:
        entrada = self.tabela.item(item.row(), 0).data(PAPEL_ENTRADA)
        if entrada is None:
            return
        if entrada.pasta:
            self.ir_para(entrada.caminho)
        else:
            self.espiar(entrada)

    def espiar(self, entrada) -> None:
        if Path(entrada.nome).suffix.lower() not in TEXTO and entrada.tamanho > sftp.LIMITE_ESPIADA:
            self.recado.emit(
                f"{entrada.nome} e grande demais pra previa, use Baixar", 6000
            )
            return
        self._marcar_ocupado(True, f"abrindo {entrada.nome}")
        self._rodar(
            self.conexao.espiar,
            entrada.caminho,
            ao_pronto=lambda par, e=entrada: self._mostrar_espiada(e, *par),
            ao_falhar=self._erro_simples,
        )

    def _mostrar_espiada(self, entrada, texto: str, cortado: bool) -> None:
        self._marcar_ocupado(False)
        self.espiada.setPlainText(texto)
        self.realce.set_language(guess_language(texto))
        self.espiada_nome.setText(
            f"{entrada.nome}   ·   so leitura" + ("   ·   mostrando so o comeco" if cortado else "")
        )
        primeira = self.caixa_espiada.isHidden()
        self.caixa_espiada.show()
        if primeira or self.divisor.sizes()[1] < 40:
            total = sum(self.divisor.sizes()) or self.divisor.height() or 600
            self.divisor.setSizes([int(total * 0.45), int(total * 0.55)])

    def fechar_espiada(self) -> None:
        self.caixa_espiada.hide()
        self.espiada.clear()
        self.espiada_nome.setText("")

    def baixar(self) -> None:
        escolhidas = [e for e in self._selecionadas() if not e.pasta]
        if not escolhidas:
            self.recado.emit("escolha um arquivo pra baixar. Pasta ainda nao desce inteira", 5000)
            return

        if len(escolhidas) == 1:
            destino, _ = QFileDialog.getSaveFileName(
                self, "Salvar como", str(sftp.destino_local(Path.home() / "Downloads", escolhidas[0].nome))
            )
            if not destino:
                return
            alvos = [(escolhidas[0], Path(destino))]
        else:
            pasta = QFileDialog.getExistingDirectory(
                self, "Salvar os arquivos em", str(Path.home() / "Downloads")
            )
            if not pasta:
                return
            # o nome vem do servidor, e em lote ninguem ve o caminho antes de gravar
            alvos = [(e, sftp.destino_local(pasta, e.nome)) for e in escolhidas]
            # arquivo local de mesmo nome era trocado calado pelo que desceu
            repetidos = [local.name for _, local in alvos if local.exists()]
            if repetidos:
                escolha = self._perguntar_repetidos(
                    "Ja existe na pasta do computador", repetidos, "local"
                )
                if escolha is None:
                    return
                if escolha == "pular":
                    alvos = [(e, local) for e, local in alvos if not local.exists()]

        self._fila_transferencia(alvos, enviando=False)

    def enviar(self) -> None:
        arquivos, _ = QFileDialog.getOpenFileNames(
            self, "Escolher o que enviar", str(Path.home())
        )
        if not arquivos:
            return
        alvos = [
            (sftp.Entrada(nome=Path(a).name, caminho=sftp.juntar(self.caminho, Path(a).name)), Path(a))
            for a in arquivos
        ]
        # O put substitui o arquivo do servidor sem aviso, e ali nao existe lixeira.
        # A conferencia e pela listagem da tela, que e o que a pessoa esta vendo.
        nomes = getattr(self, "_nomes", {})
        repetidos = [e.nome for e, _ in alvos if e.nome in nomes]
        if repetidos:
            detalhe = [
                f"{nome}   {nomes[nome].tamanho_legivel()}   {nomes[nome].quando()}".rstrip()
                for nome in repetidos
            ]
            escolha = self._perguntar_repetidos(
                f"Ja existe em {self.caminho} no servidor", detalhe, "servidor"
            )
            if escolha is None:
                return
            if escolha == "pular":
                alvos = [(e, local) for e, local in alvos if e.nome not in nomes]
        if alvos:
            self._fila_transferencia(alvos, enviando=True)

    def _perguntar_repetidos(self, titulo: str, nomes: list, onde: str) -> str | None:
        """Substituir, Pular ou Cancelar. Devolve "substituir", "pular" ou None."""
        caixa = QMessageBox(self)
        caixa.setWindowTitle("Arquivo com o mesmo nome")
        caixa.setText(f"{titulo}:\n\n" + "\n".join(nomes[:12])
                      + (f"\n... e mais {len(nomes) - 12}" if len(nomes) > 12 else ""))
        if onde == "servidor":
            caixa.setInformativeText(
                "Substituir troca o arquivo do servidor, e la nao existe lixeira."
            )
        substituir = caixa.addButton("Substituir", QMessageBox.ButtonRole.DestructiveRole)
        pular = caixa.addButton("Pular estes", QMessageBox.ButtonRole.AcceptRole)
        cancelar = caixa.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        caixa.setDefaultButton(pular)
        caixa.exec()
        clicado = caixa.clickedButton()
        if clicado is substituir:
            return "substituir"
        if clicado is pular:
            return "pular"
        del cancelar
        return None

    def _fila_transferencia(self, alvos: list, enviando: bool) -> None:
        """Uma transferencia por vez, na ordem. O canal SFTP e um so."""
        fila = list(alvos)

        def proximo() -> None:
            if not fila:
                self.barra.hide()
                self.transferindo.setText("")
                self._marcar_ocupado(False)
                if enviando:
                    self.recarregar()
                return

            entrada, local = fila.pop(0)
            verbo = "enviando" if enviando else "baixando"
            self.transferindo.setText(f"{verbo} {entrada.nome}")
            self.barra.setValue(0)
            self.barra.show()

            tarefa = Tarefa(
                self.conexao.enviar if enviando else self.conexao.baixar,
                str(local) if enviando else entrada.caminho,
                entrada.caminho if enviando else str(local),
                progresso=lambda feito, total: tarefa.sinais.andou.emit(feito, total),
            )
            tarefa.sinais.andou.connect(self._andar)
            tarefa.sinais.pronto.connect(
                lambda _=None, e=entrada: (
                    self.recado.emit(f"{e.nome} {'enviado' if enviando else 'salvo'}", 4000),
                    proximo(),
                )
            )
            tarefa.sinais.falhou.connect(
                lambda msg: (self.recado.emit(msg, 9000), proximo())
            )
            tarefa.sinais.falhou.connect(self._conferir_sessao)
            self._guardar(tarefa)
            self.pool.start(tarefa)

        self._marcar_ocupado(True, "transferindo")
        proximo()

    def _andar(self, feito: int, total: int) -> None:
        if total <= 0:
            return
        self.barra.setValue(int(feito * 100 / total))

    def nova_pasta(self) -> None:
        nome, ok = QInputDialog.getText(self, "Nova pasta", f"Nome da pasta em {self.caminho}")
        nome = (nome or "").strip()
        if not ok or not nome:
            return
        if "/" in nome:
            self.recado.emit("o nome da pasta nao pode ter barra", 5000)
            return
        self._rodar(
            self.conexao.criar_pasta,
            sftp.juntar(self.caminho, nome),
            ao_pronto=lambda _: (self.recado.emit(f"pasta {nome} criada", 4000), self.recarregar()),
            ao_falhar=self._erro_simples,
        )

    def renomear(self) -> None:
        escolhidas = self._selecionadas()
        if len(escolhidas) != 1:
            self.recado.emit("escolha um item pra renomear", 4000)
            return
        alvo = escolhidas[0]
        nome, ok = QInputDialog.getText(self, "Renomear", "Novo nome", text=alvo.nome)
        nome = (nome or "").strip()
        if not ok or not nome or nome == alvo.nome:
            return
        if "/" in nome:
            self.recado.emit("o nome nao pode ter barra", 5000)
            return
        # o rename do servidor troca o destino de forma atomica: o b.txt que ja estava
        # la sumia sem aviso nenhum
        if nome in getattr(self, "_nomes", {}):
            resposta = QMessageBox.question(
                self,
                "Renomear",
                f"Ja existe {nome} nesta pasta do servidor. Substituir?\n\n"
                "O que esta la hoje some, e no servidor nao existe lixeira.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if resposta != QMessageBox.StandardButton.Yes:
                return
        # o destino e a pasta do proprio item, e nao a da tela: com as duas diferentes, o
        # arquivo ia parar em outra pasta em vez de trocar de nome
        self._rodar(
            self.conexao.renomear,
            alvo.caminho,
            sftp.juntar(sftp.pai(alvo.caminho), nome),
            ao_pronto=lambda _: (self.recado.emit(f"virou {nome}", 4000), self.recarregar()),
            ao_falhar=self._erro_simples,
        )

    def excluir(self) -> None:
        escolhidas = self._selecionadas()
        if not escolhidas:
            return
        if len(escolhidas) == 1:
            pergunta = f"Apagar {escolhidas[0].nome} do servidor?"
        else:
            pergunta = f"Apagar {len(escolhidas)} itens do servidor?"

        caixa = QMessageBox(self)
        caixa.setWindowTitle("Apagar no servidor")
        caixa.setText(pergunta)
        caixa.setInformativeText(
            "Isso acontece no servidor, e nao no seu computador. Nao existe lixeira: "
            "o que sair daqui so volta pelo backup de quem cuida da maquina."
        )
        apagar = caixa.addButton("Apagar", QMessageBox.ButtonRole.DestructiveRole)
        caixa.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        caixa.setDefaultButton(caixa.buttons()[-1])
        caixa.exec()
        if caixa.clickedButton() is not apagar:
            return

        restantes = list(escolhidas)
        falhas: list[str] = []

        def proximo() -> None:
            if not restantes:
                if falhas:
                    self.recado.emit("   ".join(falhas[:3]), 9000)
                else:
                    self.recado.emit(f"{len(escolhidas)} apagados no servidor", 5000)
                self.recarregar()
                return
            alvo = restantes.pop(0)
            self._rodar(
                self.conexao.remover,
                alvo,
                ao_pronto=lambda _: proximo(),
                ao_falhar=lambda msg: (falhas.append(msg), proximo()),
            )

        proximo()

    def copiar_caminho(self) -> None:
        escolhidas = self._selecionadas()
        alvo = "\n".join(e.caminho for e in escolhidas) or self.caminho
        QGuiApplication.clipboard().setText(alvo)
        self.recado.emit("caminho copiado", 3000)

    def _menu(self, posicao) -> None:
        escolhidas = self._selecionadas()
        menu = QMenu(self)

        if len(escolhidas) == 1 and escolhidas[0].pasta:
            menu.addAction("Entrar", lambda: self.ir_para(escolhidas[0].caminho))
        elif len(escolhidas) == 1:
            menu.addAction("Abrir previa", lambda: self.espiar(escolhidas[0]))

        if any(not e.pasta for e in escolhidas):
            menu.addAction("Baixar", self.baixar)
        menu.addAction("Copiar caminho", self.copiar_caminho)
        menu.addSeparator()
        menu.addAction("Nova pasta", self.nova_pasta)
        menu.addAction("Enviar arquivo", self.enviar)
        if len(escolhidas) == 1:
            menu.addAction("Renomear", self.renomear)
        if escolhidas:
            menu.addSeparator()
            menu.addAction("Apagar no servidor", self.excluir)
        menu.addSeparator()
        menu.addAction("Recarregar", self.recarregar)
        menu.exec(self.tabela.viewport().mapToGlobal(posicao))

    # ------------------------------------------------------------------------ encanamento

    def _marcar_ocupado(self, ocupado: bool, texto: str = "") -> None:
        self._ocupado = ocupado
        self.estado.setText(texto or ("trabalhando" if ocupado else "conectado"))
        papel = "aviso" if ocupado else "ok"
        theme.estilizar(
            self.estado,
            lambda p=papel: f"color: {theme.cor(p)}; font-size: 8pt; font-weight: 600;",
        )
        self.setCursor(Qt.CursorShape.BusyCursor if ocupado else Qt.CursorShape.ArrowCursor)

    def _erro_simples(self, mensagem: str) -> None:
        self._marcar_ocupado(False)
        self.recado.emit(mensagem, 8000)

    def _conferir_sessao(self, *_) -> None:
        """Depois de uma falha, ve se a sessao ainda existe.

        Suspender o notebook ou o servidor derrubar a conexao deixava a aba dizendo
        conectado em verde, e toda acao falhava com Socket is closed.
        """
        if self.conexao.aberta:
            return
        self.estado.setText("desconectado")
        theme.estilizar(
            self.estado, lambda: f"color: {theme.ERR}; font-size: 8pt; font-weight: 600;"
        )
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.btn_reconectar.show()
        self.caiu.emit()

    def _guardar(self, tarefa: Tarefa) -> None:
        self._tarefas.add(tarefa)
        for sinal in (tarefa.sinais.pronto, tarefa.sinais.falhou):
            sinal.connect(lambda *_, t=tarefa: self._tarefas.discard(t))

    def _rodar(self, funcao, *args, ao_pronto=None, ao_falhar=None, **kwargs) -> None:
        tarefa = Tarefa(funcao, *args, **kwargs)
        if ao_pronto is not None:
            tarefa.sinais.pronto.connect(ao_pronto)
        tarefa.sinais.falhou.connect(ao_falhar or self._erro_simples)
        tarefa.sinais.falhou.connect(self._conferir_sessao)
        self._guardar(tarefa)
        self.pool.start(tarefa)

    def encerrar(self) -> None:
        self.conexao.fechar()
        self.fechou.emit()
