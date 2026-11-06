"""Cadastro de servidor SFTP e as duas perguntas que a conexao pode fazer.

Sao tres telas pequenas e uma so ideia: nada de segredo entra aqui sem a pessoa saber
onde ele vai parar. O editor diz, em texto, que a senha vai pro cofre. A pergunta da
chave do servidor mostra a impressao digital inteira, porque conferir metade nao serve
de nada.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core import sftp
from . import theme
from .request_editor import mono


class PerfilDialog(QDialog):
    """Cria ou edita um servidor. Devolve o perfil e a senha digitada, se houver."""

    def __init__(self, perfil: sftp.Perfil | None, parent=None, guardada: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Servidor SFTP" if perfil else "Novo servidor SFTP")
        self.setMinimumWidth(520)
        self.perfil = perfil or sftp.Perfil(id=sftp.novo_id())
        # None deixa o cofre como esta, texto vazio apaga, texto grava
        self.senha_nova: str | None = None
        self.frase_nova: str | None = None
        self._guardada = guardada
        self._esquecer = False

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(18, 16, 18, 14)
        raiz.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(9)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.nome = QLineEdit(self.perfil.nome)
        self.nome.setPlaceholderText("como voce chama esse servidor")
        form.addRow("Nome", self.nome)

        linha_host = QHBoxLayout()
        linha_host.setSpacing(8)
        self.host = QLineEdit(self.perfil.host)
        self.host.setPlaceholderText("sftp.parceiro.com.br")
        self.porta = QSpinBox()
        self.porta.setRange(1, 65535)
        self.porta.setValue(self.perfil.porta or sftp.PORTA_PADRAO)
        self.porta.setFixedWidth(84)
        # a folha do tema nao desenha as setas do QSpinBox, e sobravam dois retangulos
        # vazios; porta se digita, e a seta do teclado continua valendo
        self.porta.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.porta.setToolTip("Porta SSH. O padrao e 22.")
        linha_host.addWidget(self.host, 1)
        linha_host.addWidget(QLabel("porta"))
        linha_host.addWidget(self.porta)
        form.addRow("Servidor", linha_host)

        self.usuario = QLineEdit(self.perfil.usuario)
        form.addRow("Usuario", self.usuario)

        self.modo = QComboBox()
        for chave, rotulo in sftp.AUTH.items():
            self.modo.addItem(rotulo, chave)
        indice = self.modo.findData(self.perfil.auth)
        self.modo.setCurrentIndex(indice if indice >= 0 else 0)
        self.modo.currentIndexChanged.connect(self._trocar_modo)
        form.addRow("Autenticar com", self.modo)

        self.senha = QLineEdit()
        self.senha.setEchoMode(QLineEdit.EchoMode.Password)
        self.rotulo_senha = QLabel("Senha")
        # Com credencial ja no cofre, a dica antiga mandava deixar em branco pra
        # perguntar a cada conexao, e deixar em branco mantinha a guardada.
        linha_senha = QHBoxLayout()
        linha_senha.setSpacing(6)
        linha_senha.addWidget(self.senha, 1)
        self.btn_esquecer = QPushButton("Esquecer a guardada")
        self.btn_esquecer.setToolTip("Apaga do cofre a senha e a frase guardadas deste servidor")
        self.btn_esquecer.clicked.connect(self._esquecer_guardada)
        self.btn_esquecer.setVisible(guardada)
        linha_senha.addWidget(self.btn_esquecer)
        form.addRow(self.rotulo_senha, linha_senha)
        self._dica_senha()

        self.caixa_chave = QWidget()
        linha_chave = QHBoxLayout(self.caixa_chave)
        linha_chave.setContentsMargins(0, 0, 0, 0)
        linha_chave.setSpacing(6)
        self.chave = QLineEdit(self.perfil.chave)
        self.chave.setPlaceholderText(r"C:\Users\voce\.ssh\id_ed25519")
        procurar = QPushButton("Procurar")
        procurar.clicked.connect(self._escolher_chave)
        linha_chave.addWidget(self.chave, 1)
        linha_chave.addWidget(procurar)
        self.rotulo_chave = QLabel("Chave privada")
        form.addRow(self.rotulo_chave, self.caixa_chave)

        self.frase = QLineEdit()
        self.frase.setEchoMode(QLineEdit.EchoMode.Password)
        self.frase.setPlaceholderText("so se a chave for protegida")
        self.rotulo_frase = QLabel("Frase da chave")
        form.addRow(self.rotulo_frase, self.frase)

        self.raiz = QLineEdit(self.perfil.raiz)
        self.raiz.setPlaceholderText("/ ou a pasta em que abrir, por exemplo /home/voce/entrada")
        form.addRow("Abrir em", self.raiz)
        raiz.addLayout(form)

        self.guardar = QCheckBox("Guardar a credencial no cofre deste workspace")
        self.guardar.setChecked(True)
        self.guardar.setToolTip(
            "O cofre e o mesmo das variaveis secretas: AES-256-GCM, com a chave presa a "
            "sua conta local. O arquivo versionado do workspace fica so com host, "
            "porta e usuario."
        )
        raiz.addWidget(self.guardar)

        self.aviso = QLabel("")
        self.aviso.setWordWrap(True)
        self.aviso.setObjectName("hint")
        theme.estilizar(self.aviso, lambda: f"color: {theme.WARN}; font-size: 8pt;")
        raiz.addWidget(self.aviso)

        botoes = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        botoes.button(QDialogButtonBox.StandardButton.Ok).setText("Salvar")
        botoes.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        botoes.accepted.connect(self._aceitar)
        botoes.rejected.connect(self.reject)
        raiz.addWidget(botoes)

        for campo in (self.host, self.usuario, self.nome):
            campo.textChanged.connect(self._conferir)
        self.chave.textChanged.connect(self._conferir)
        self._trocar_modo()

    def _dica_senha(self) -> None:
        if self._guardada and not self._esquecer:
            self.senha.setPlaceholderText("guardada no cofre, digite pra trocar")
        else:
            self.senha.setPlaceholderText("deixe em branco pra perguntar a cada conexao")

    def _esquecer_guardada(self) -> None:
        self._esquecer = True
        self.btn_esquecer.setEnabled(False)
        self.btn_esquecer.setText("sera esquecida ao salvar")
        self._dica_senha()

    def _trocar_modo(self) -> None:
        modo = self.modo.currentData()
        for alvo in (self.rotulo_senha, self.senha):
            alvo.setVisible(modo == "senha")
        for alvo in (self.rotulo_chave, self.caixa_chave, self.rotulo_frase, self.frase):
            alvo.setVisible(modo == "chave")
        self.guardar.setVisible(modo in ("senha", "chave"))
        self.btn_esquecer.setVisible(self._guardada and modo == "senha")
        self._conferir()

    def _escolher_chave(self) -> None:
        from pathlib import Path

        inicio = str(Path.home() / ".ssh")
        caminho, _ = QFileDialog.getOpenFileName(self, "Escolher a chave privada", inicio)
        if caminho:
            self.chave.setText(caminho)

    def _montar(self) -> sftp.Perfil:
        return sftp.Perfil(
            id=self.perfil.id,
            nome=self.nome.text().strip() or self.host.text().strip() or "servidor",
            host=self.host.text().strip(),
            porta=self.porta.value(),
            usuario=self.usuario.text().strip(),
            auth=self.modo.currentData(),
            chave=self.chave.text().strip(),
            raiz=self.raiz.text().strip(),
        )

    def _conferir(self) -> str:
        problema = self._montar().problema()
        self.aviso.setText(problema)
        self.aviso.setVisible(bool(problema))
        return problema

    def _aceitar(self) -> None:
        if self._conferir():
            return
        self.perfil = self._montar()
        if self._esquecer or not self.guardar.isChecked():
            # desmarcar Guardar tambem esquece: antes a senha antiga seguia no cofre e
            # continuava sendo usada em toda conexao
            self.senha_nova = ""
            self.frase_nova = ""
        if self.guardar.isChecked():
            if self.perfil.auth == "senha" and self.senha.text():
                self.senha_nova = self.senha.text()
            if self.perfil.auth == "chave" and self.frase.text():
                self.frase_nova = self.frase.text()
        self.accept()

    @staticmethod
    def pedir(perfil: sftp.Perfil | None, parent=None, guardada: bool = False):
        dialogo = PerfilDialog(perfil, parent, guardada)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialogo


class SenhaDialog(QDialog):
    """Pergunta a credencial na hora de conectar, quando ela nao esta guardada."""

    def __init__(self, perfil: sftp.Perfil, frase: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Conectar")
        self.setMinimumWidth(400)

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(18, 16, 18, 14)
        raiz.setSpacing(10)

        alvo = QLabel(perfil.rotulo())
        alvo.setFont(mono(9))
        raiz.addWidget(alvo)

        self.campo = QLineEdit()
        self.campo.setEchoMode(QLineEdit.EchoMode.Password)
        self.campo.setPlaceholderText("frase da chave privada" if frase else "senha")
        raiz.addWidget(self.campo)

        self.guardar = QCheckBox("Guardar no cofre e nao perguntar de novo")
        raiz.addWidget(self.guardar)

        botoes = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        botoes.button(QDialogButtonBox.StandardButton.Ok).setText("Conectar")
        botoes.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)
        raiz.addWidget(botoes)
        self.campo.setFocus()

    @staticmethod
    def pedir(perfil: sftp.Perfil, frase: bool = False, parent=None):
        """Devolve (texto, guardar) ou (None, False) quando a pessoa desiste."""
        dialogo = SenhaDialog(perfil, frase, parent)
        if dialogo.exec() != QDialog.DialogCode.Accepted or not dialogo.campo.text():
            return None, False
        return dialogo.campo.text(), dialogo.guardar.isChecked()


class ChaveDialog(QDialog):
    """A impressao digital do servidor, pra alguem olhar antes de confiar."""

    def __init__(self, erro, parent=None):
        super().__init__(parent)
        trocou = isinstance(erro, sftp.ChaveTrocada)
        self.setWindowTitle("Chave trocada" if trocou else "Servidor desconhecido")
        self.setMinimumWidth(560)

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(18, 16, 18, 14)
        raiz.setSpacing(11)

        titulo = QLabel(
            f"A chave de {erro.host} nao e a mesma da ultima conexao."
            if trocou
            else f"E a primeira vez que este workspace conecta em {erro.host}."
        )
        titulo.setWordWrap(True)
        theme.estilizar(
            titulo, lambda: f"font-size: 11pt; font-weight: 600; color: {theme.TEXT};"
        )
        raiz.addWidget(titulo)

        digital = QLabel(erro.digital)
        digital.setFont(mono(9))
        digital.setWordWrap(True)
        digital.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        theme.estilizar(
            digital,
            lambda: f"background: {theme.PANEL2}; border: 1px solid {theme.BORDER};"
            f" border-radius: 8px; padding: 10px 12px; color: {theme.TEXT};",
        )
        raiz.addWidget(digital)

        explicacao = QLabel(
            "A chave do servidor mudar sem aviso e o sinal classico de alguem no meio do "
            "caminho se passando por ele. Se a troca nao foi combinada, pare aqui e "
            "confirme com quem cuida do servidor."
            if trocou
            else "Compare essa impressao digital com a que o responsavel pelo servidor "
            "informou. Confiar sem conferir aceita qualquer maquina que atenda por esse "
            "endereco, inclusive uma que nao seja a certa."
        )
        explicacao.setWordWrap(True)
        explicacao.setObjectName("hint")
        raiz.addWidget(explicacao)

        botoes = QDialogButtonBox()
        confiar = botoes.addButton(
            "Confiar e conectar", QDialogButtonBox.ButtonRole.AcceptRole
        )
        botoes.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)
        # o botao de confiar nao e o padrao de proposito: Enter no susto nao pode ser
        # o gesto que aceita uma chave que ninguem olhou
        confiar.setAutoDefault(False)
        confiar.setDefault(False)
        raiz.addWidget(botoes)

    @staticmethod
    def confia(erro, parent=None) -> bool:
        return ChaveDialog(erro, parent).exec() == QDialog.DialogCode.Accepted
