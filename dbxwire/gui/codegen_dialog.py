"""Janela de codigo gerado a partir do request."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from ..core import codegen
from . import theme
from .highlight import CodeHighlighter
from .request_editor import mono

EXTENSAO = {
    "curl": ".sh",
    "powershell": ".ps1",
    "python-httpx": ".py",
    "python-requests": ".py",
    "javascript-fetch": ".js",
    "node-axios": ".js",
    "java": ".java",
    "csharp": ".cs",
    "go": ".go",
}


class CodegenDialog(QDialog):
    def __init__(self, construir, tem_segredo: bool, parent=None):
        """construir e um callable(revelar_segredo) que devolve method, url, headers, body."""
        super().__init__(parent)
        self.construir = construir
        self.setWindowTitle("Codigo do request")
        self.resize(900, 660)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        barra = QHBoxLayout()
        barra.setSpacing(8)

        self.combo = QComboBox()
        for chave, rotulo in codegen.LANGUAGES:
            self.combo.addItem(rotulo, chave)
        self.combo.setMinimumWidth(200)
        self.combo.currentIndexChanged.connect(self._gerar)
        barra.addWidget(self.combo)

        self.revelar = QCheckBox("incluir o valor real dos segredos")
        self.revelar.setEnabled(tem_segredo)
        self.revelar.setToolTip(
            "Sem isso, variavel secreta sai como {{nome}}. Codigo gerado costuma acabar "
            "colado em chat e em ticket, entao o padrao e nao revelar."
        )
        self.revelar.stateChanged.connect(self._gerar)
        barra.addWidget(self.revelar)
        barra.addStretch(1)

        self.btn_copiar = QPushButton("Copiar")
        self.btn_copiar.setObjectName("send")
        self.btn_copiar.clicked.connect(self._copiar)
        self.btn_salvar = QPushButton("Salvar")
        self.btn_salvar.clicked.connect(self._salvar)
        barra.addWidget(self.btn_copiar)
        barra.addWidget(self.btn_salvar)
        root.addLayout(barra)

        self.codigo = QPlainTextEdit()
        self.codigo.setReadOnly(True)
        self.codigo.setFont(mono(9))
        self.codigo.setFrameShape(QFrame.Shape.NoFrame)
        self.codigo.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.realce = CodeHighlighter(self.codigo.document(), "code")
        root.addWidget(self.codigo, 1)

        self.aviso = QLabel("")
        self.aviso.setObjectName("hint")
        self.aviso.setWordWrap(True)
        root.addWidget(self.aviso)

        rodape = QHBoxLayout()
        rodape.addStretch(1)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.accept)
        rodape.addWidget(fechar)
        root.addLayout(rodape)

        self._gerar()

    def _gerar(self) -> None:
        linguagem = self.combo.currentData()
        revelar = self.revelar.isChecked()
        method, url, headers, body = self.construir(revelar)
        texto = codegen.generate(linguagem, method, url, headers, body)
        self.codigo.setPlainText(texto)

        if revelar:
            self.aviso.setText("Atencao: este codigo contem o valor real dos segredos. Nao cole em ticket nem em chat.")
            theme.estilizar(self.aviso, lambda: f"color: {theme.ERR};")
        elif self.revelar.isEnabled():
            self.aviso.setText("Variavel secreta saiu como {{nome}}. Marque a caixa acima se precisar do valor real.")
            theme.estilizar(self.aviso, lambda: f"color: {theme.FAINT};")
        else:
            self.aviso.setText("Este request nao usa variavel secreta.")
            theme.estilizar(self.aviso, lambda: f"color: {theme.FAINT};")

    def _copiar(self) -> None:
        QGuiApplication.clipboard().setText(self.codigo.toPlainText())
        self.btn_copiar.setText("Copiado")
        self.btn_copiar.setEnabled(False)
        QTimer.singleShot(1200, self._voltar_botao)

    def _voltar_botao(self) -> None:
        self.btn_copiar.setText("Copiar")
        self.btn_copiar.setEnabled(True)

    def _salvar(self) -> None:
        sufixo = EXTENSAO.get(self.combo.currentData(), ".txt")
        destino, _ = QFileDialog.getSaveFileName(self, "Salvar codigo", f"request{sufixo}")
        if destino:
            with open(destino, "w", encoding="utf-8") as arquivo:
                arquivo.write(self.codigo.toPlainText())
