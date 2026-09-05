"""Certificados do workspace: a CA em que confiar e a identidade cliente por host.

Duas coisas diferentes moram aqui, e o Postman separa do mesmo jeito:

- **CA**, o certificado da autoridade em que voce quer confiar alem das do sistema.
  Serve pro servidor de cadeia incompleta ou de CA interna. Sem isso a unica saida era
  desligar a verificacao do request, trocando um problema pontual por um buraco fixo.
- **Cliente**, o pfx ou pem que prova quem voce e no handshake. Vale por host, aceita
  curinga, e a senha vai pro cofre, nunca pro arquivo versionado.

Adicionar e um formulario aqui dentro, e nao tres caixinhas em sequencia: com tudo na
mesma tela da pra conferir o certificado antes de gravar, e voltar num campo sem
recomecar.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import certs
from . import theme
from .request_editor import mono
from .widgets import Faixa

FILTRO = "Certificado (*.pfx *.p12 *.pem *.crt *.cer);;Todos (*)"


def titulo(texto: str) -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setObjectName("sectionTitle")
    return rotulo


def separador() -> QFrame:
    linha = QFrame()
    linha.setFixedHeight(1)
    linha.setStyleSheet(f"background: {theme.BORDER};")
    return linha


class CampoArquivo(QWidget):
    """Campo de caminho com botao de escolher, que e o gesto que a pessoa espera."""

    def __init__(self, dica: str, parent=None):
        super().__init__(parent)
        linha = QHBoxLayout(self)
        linha.setContentsMargins(0, 0, 0, 0)
        linha.setSpacing(8)

        self.campo = QLineEdit()
        self.campo.setPlaceholderText(dica)
        self.campo.setFont(mono(9))
        linha.addWidget(self.campo, 1)

        self.botao = QPushButton("Escolher")
        self.botao.clicked.connect(self._escolher)
        linha.addWidget(self.botao)

    def _escolher(self) -> None:
        caminho, _ = QFileDialog.getOpenFileName(self, "Escolher arquivo", "", FILTRO)
        if caminho:
            self.campo.setText(caminho)

    def text(self) -> str:
        return self.campo.text().strip()

    def setText(self, valor: str) -> None:  # noqa: N802
        self.campo.setText(valor or "")


class CertsDialog(QDialog):
    def __init__(self, tree: dict, cofre, parent=None):
        super().__init__(parent)
        self.tree = tree
        self.cofre = cofre
        self.setWindowTitle("Certificados")
        self.resize(940, 720)

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(18, 16, 18, 14)
        raiz.setSpacing(12)

        cabeca = QLabel("Certificados deste workspace")
        cabeca.setStyleSheet("font-size: 14pt; font-weight: 700;")
        raiz.addWidget(cabeca)

        raiz.addWidget(titulo("CERTIFICADO DE CA"))
        explica_ca = QLabel(
            "Um arquivo pem com a autoridade em que este workspace deve confiar, alem das "
            "que o sistema ja conhece. Use quando o servidor entrega a cadeia incompleta "
            "ou usa CA interna, em vez de desligar a verificacao do request."
        )
        explica_ca.setObjectName("hint")
        explica_ca.setWordWrap(True)
        raiz.addWidget(explica_ca)

        self.ca = CampoArquivo("caminho do pem com a cadeia, vazio para usar so as do sistema")
        self.ca.setText(tree.get("caFile") or "")
        self.ca.campo.textChanged.connect(self._ca_mudou)
        raiz.addWidget(self.ca)

        self.faixa_ca = Faixa()
        raiz.addWidget(self.faixa_ca)
        raiz.addWidget(separador())

        raiz.addWidget(titulo("CERTIFICADOS CLIENTE"))
        explica = QLabel(
            "Quando a url do request bate com o host, esta identidade entra no handshake. "
            "A senha do arquivo vai pro cofre da maquina e nunca pro arquivo versionado."
        )
        explica.setObjectName("hint")
        explica.setWordWrap(True)
        raiz.addWidget(explica)

        self.tabela = QTableWidget(0, 5)
        self.tabela.setHorizontalHeaderLabels(["Host", "Arquivo", "Senha", "Vale ate", "Dono"])
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.setShowGrid(False)
        self.tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabela.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabela.setWordWrap(False)
        self.tabela.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.tabela.setColumnWidth(0, 200)
        self.tabela.setColumnWidth(1, 210)
        self.tabela.setColumnWidth(2, 96)
        self.tabela.setColumnWidth(3, 100)
        self.tabela.setMinimumHeight(180)
        self.tabela.itemSelectionChanged.connect(self._mudou_selecao)
        raiz.addWidget(self.tabela, 1)

        barra = QHBoxLayout()
        self.btn_novo = QPushButton("Adicionar certificado")
        self.btn_novo.clicked.connect(lambda: self._mostrar_form(True))
        barra.addWidget(self.btn_novo)

        self.btn_senha = QPushButton("Trocar senha")
        self.btn_senha.clicked.connect(self.trocar_senha)
        barra.addWidget(self.btn_senha)

        self.btn_testar = QPushButton("Conferir")
        self.btn_testar.clicked.connect(lambda: self.conferir())
        barra.addWidget(self.btn_testar)
        barra.addStretch(1)

        self.btn_remover = QPushButton("Remover")
        self.btn_remover.setStyleSheet(f"QPushButton {{ color: {theme.ERR}; }}")
        self.btn_remover.clicked.connect(self.remover)
        barra.addWidget(self.btn_remover)
        raiz.addLayout(barra)

        self.form = QFrame()
        self.form.setObjectName("formCert")
        self.form.setStyleSheet(
            f"QFrame#formCert {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER};"
            f" border-radius: 10px; }}"
            f"QFrame#formCert QLabel {{ background: transparent; border: 0; }}"
        )
        fl = QVBoxLayout(self.form)
        fl.setContentsMargins(14, 12, 14, 12)
        fl.setSpacing(9)

        fl.addWidget(titulo("NOVO CERTIFICADO CLIENTE"))

        linha_host = QHBoxLayout()
        linha_host.setSpacing(8)
        rotulo_host = QLabel("Host")
        rotulo_host.setFixedWidth(64)
        linha_host.addWidget(rotulo_host)
        self.campo_host = QLineEdit()
        self.campo_host.setPlaceholderText("api.exemplo.com, ou *.exemplo.com")
        self.campo_host.setFont(mono(9))
        linha_host.addWidget(self.campo_host, 1)
        fl.addLayout(linha_host)

        linha_arq = QHBoxLayout()
        linha_arq.setSpacing(8)
        rotulo_arq = QLabel("Arquivo")
        rotulo_arq.setFixedWidth(64)
        linha_arq.addWidget(rotulo_arq)
        self.campo_arquivo = CampoArquivo("pfx, p12 ou pem com a chave junto")
        self.campo_arquivo.campo.textChanged.connect(self._previa)
        linha_arq.addWidget(self.campo_arquivo, 1)
        fl.addLayout(linha_arq)

        linha_senha = QHBoxLayout()
        linha_senha.setSpacing(8)
        rotulo_senha = QLabel("Senha")
        rotulo_senha.setFixedWidth(64)
        linha_senha.addWidget(rotulo_senha)
        self.campo_senha = QLineEdit()
        self.campo_senha.setEchoMode(QLineEdit.EchoMode.Password)
        self.campo_senha.setPlaceholderText("vazio se o arquivo nao tiver senha")
        self.campo_senha.textChanged.connect(self._previa)
        linha_senha.addWidget(self.campo_senha, 1)
        self.btn_ver = QPushButton("mostrar")
        # setFlat nao tem efeito com folha de estilo global: sem objectName ele saia
        # com a moldura inteira de botao comum, empurrando o campo de senha do lado
        self.btn_ver.setObjectName("flat")
        self.btn_ver.setCheckable(True)
        self.btn_ver.toggled.connect(self._alternar_senha)
        linha_senha.addWidget(self.btn_ver)
        fl.addLayout(linha_senha)

        self.faixa_form = Faixa()
        fl.addWidget(self.faixa_form)

        acoes = QHBoxLayout()
        acoes.addStretch(1)
        cancelar = QPushButton("Cancelar")
        cancelar.clicked.connect(lambda: self._mostrar_form(False))
        acoes.addWidget(cancelar)
        self.btn_add = QPushButton("Adicionar")
        self.btn_add.setObjectName("send")
        self.btn_add.clicked.connect(self.adicionar)
        acoes.addWidget(self.btn_add)
        fl.addLayout(acoes)

        self.form.hide()
        raiz.addWidget(self.form)

        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        botoes.rejected.connect(self.accept)
        botoes.accepted.connect(self.accept)
        raiz.addWidget(botoes)

        self.recarregar()
        self._ca_mudou()
        self._mudou_selecao()


    def _lista(self) -> list:
        return self.tree.setdefault("certificates", [])

    def recarregar(self) -> None:
        itens = self._lista()
        self.tabela.setRowCount(len(itens))
        for indice, item in enumerate(itens):
            host = QTableWidgetItem(item.get("host") or "")
            host.setFont(mono(9))
            self.tabela.setItem(indice, 0, host)

            caminho = Path(item.get("file") or "")
            arquivo = QTableWidgetItem(caminho.name or "")
            arquivo.setToolTip(str(caminho))
            arquivo.setFont(mono(9))
            if not caminho.exists():
                arquivo.setForeground(QColor(theme.ERR))
                arquivo.setToolTip(f"{caminho}\nnao encontrado")
            self.tabela.setItem(indice, 1, arquivo)

            tem_senha = bool(self.cofre.get(certs.CHAVE_SENHA.format(host=item.get("host") or "")))
            senha = QTableWidgetItem("no cofre" if tem_senha else "sem senha")
            senha.setForeground(QColor(theme.OK if tem_senha else theme.FAINT))
            self.tabela.setItem(indice, 2, senha)

            ate = QTableWidgetItem(item.get("ate") or "")
            dias = item.get("dias")
            if isinstance(dias, int):
                if dias < 0:
                    ate.setForeground(QColor(theme.ERR))
                    ate.setToolTip("ja venceu")
                elif dias < 30:
                    ate.setForeground(QColor(theme.WARN))
                    ate.setToolTip(f"vence em {dias} dias")
                else:
                    ate.setForeground(QColor(theme.OK))
            self.tabela.setItem(indice, 3, ate)

            dono = QTableWidgetItem(item.get("detalhe") or "")
            dono.setForeground(QColor(theme.DIM))
            dono.setToolTip(item.get("detalhe") or "")
            self.tabela.setItem(indice, 4, dono)
            self.tabela.setRowHeight(indice, theme.medida("linha_tabela"))

    def selecionado(self) -> dict | None:
        linhas = self.tabela.selectionModel().selectedRows()
        if not linhas:
            return None
        indice = linhas[0].row()
        itens = self._lista()
        return itens[indice] if indice < len(itens) else None

    def _mudou_selecao(self) -> None:
        tem = self.selecionado() is not None
        for botao in (self.btn_senha, self.btn_testar, self.btn_remover):
            botao.setEnabled(tem)


    def _ca_mudou(self) -> None:
        caminho = self.ca.text()
        self.tree["caFile"] = caminho
        if not caminho:
            self.faixa_ca.esconder()
            return
        alvo = Path(caminho)
        if not alvo.exists():
            self.faixa_ca.mostrar("arquivo nao encontrado", theme.ERR)
            return
        dados = certs.inspecionar(caminho, "")
        if dados.get("erro"):
            self.faixa_ca.mostrar(dados["erro"], theme.ERR)
            return
        self.faixa_ca.mostrar(
            f"{dados['dono'][:70]}  ·  vale ate {dados['ate']}", theme.OK
        )


    def _mostrar_form(self, mostrar: bool) -> None:
        self.form.setVisible(mostrar)
        self.btn_novo.setEnabled(not mostrar)
        if mostrar:
            self.campo_host.setFocus()
        else:
            self.campo_host.clear()
            self.campo_arquivo.setText("")
            self.campo_senha.clear()
            self.faixa_form.esconder()

    def _alternar_senha(self, mostrar: bool) -> None:
        self.campo_senha.setEchoMode(
            QLineEdit.EchoMode.Normal if mostrar else QLineEdit.EchoMode.Password
        )
        self.btn_ver.setText("esconder" if mostrar else "mostrar")

    def _previa(self) -> None:
        """Confere o arquivo enquanto voce digita, pra nao descobrir no envio."""
        caminho = self.campo_arquivo.text()
        if not caminho:
            self.faixa_form.esconder()
            return
        dados = certs.inspecionar(caminho, self.campo_senha.text())
        if dados.get("erro"):
            self.faixa_form.mostrar(dados["erro"], theme.ERR)
            return
        dias = dados.get("dias", 0)
        cor = theme.OK if dias > 30 else (theme.WARN if dias >= 0 else theme.ERR)
        quando = f"vale ate {dados['ate']}" if dias >= 0 else f"venceu em {dados['ate']}"
        self.faixa_form.mostrar(f"{dados['dono'][:66]}  ·  {quando}", cor)


    def adicionar(self) -> None:
        host = self.campo_host.text().strip()
        arquivo = self.campo_arquivo.text()
        if not host or not arquivo:
            self.faixa_form.mostrar("host e arquivo sao obrigatorios", theme.WARN)
            return
        if not Path(arquivo).exists():
            self.faixa_form.mostrar("arquivo nao encontrado", theme.ERR)
            return

        senha = self.campo_senha.text()
        item = {"host": host, "file": arquivo, "enabled": True}
        self._lista().append(item)
        if senha:
            self.cofre.set(certs.CHAVE_SENHA.format(host=host), senha)
        self._anotar(item, senha)
        self.recarregar()
        self._mostrar_form(False)
        self.tabela.selectRow(len(self._lista()) - 1)

    def _anotar(self, item: dict, senha: str) -> None:
        dados = certs.inspecionar(item.get("file") or "", senha)
        if dados.get("erro"):
            item["detalhe"] = dados["erro"]
            item.pop("ate", None)
            item.pop("dias", None)
            return
        item["detalhe"] = dados["dono"][:120]
        item["ate"] = dados["ate"]
        item["dias"] = dados["dias"]

    def trocar_senha(self) -> None:
        item = self.selecionado()
        if not item:
            return
        from PySide6.QtWidgets import QInputDialog

        senha, ok = QInputDialog.getText(
            self,
            "Senha do certificado",
            f"Senha do certificado de {item.get('host')}",
            QLineEdit.EchoMode.Password,
        )
        if not ok:
            return
        self.cofre.set(certs.CHAVE_SENHA.format(host=item.get("host") or ""), senha)
        self._anotar(item, senha)
        self.recarregar()

    def conferir(self) -> None:
        item = self.selecionado()
        if not item:
            return
        senha = self.cofre.get(certs.CHAVE_SENHA.format(host=item.get("host") or ""))
        self._anotar(item, senha)
        self.recarregar()

    def remover(self) -> None:
        item = self.selecionado()
        if not item:
            return
        resposta = QMessageBox.question(
            self,
            "Remover certificado",
            f"Remover o certificado de {item.get('host')}?\n"
            "O arquivo no disco nao e apagado, so a associacao com o host.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resposta != QMessageBox.StandardButton.Yes:
            return
        self.cofre.set(certs.CHAVE_SENHA.format(host=item.get("host") or ""), "")
        self._lista().remove(item)
        self.recarregar()
        self._mudou_selecao()
