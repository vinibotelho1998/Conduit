"""Colar um curl e ver o que vai virar antes de aplicar."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)

from ..core import curl_import
from . import theme
from .highlight import CodeHighlighter
from .request_editor import mono


class CurlDialog(QDialog):
    """Mostra o comando de um lado e o que ele vira do outro, antes de sobrescrever."""

    def __init__(self, texto_inicial: str = "", nome_request: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Importar de curl")
        self.resize(880, 560)
        self.resultado: curl_import.Importado | None = None

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(16, 14, 16, 14)
        raiz.setSpacing(10)

        aviso = QLabel(
            f"O conteudo atual de {nome_request} vai ser substituido."
            if nome_request
            else "Cole o comando curl abaixo."
        )
        aviso.setObjectName("hint")
        raiz.addWidget(aviso)

        self.entrada = QPlainTextEdit(texto_inicial)
        self.entrada.setFont(mono(9))
        self.entrada.setPlaceholderText(
            "curl -X POST 'https://api.exemplo.com/recurso' \\\n"
            "  -H 'Content-Type: application/json' \\\n"
            "  -d '{\"campo\": \"valor\"}'"
        )
        self.entrada.setFrameShape(QFrame.Shape.NoFrame)
        self.entrada.setStyleSheet(
            f"QPlainTextEdit {{ background: {theme.BG}; border: 1px solid {theme.BORDER};"
            f" border-radius: 6px; padding: 8px; }}"
        )
        self.entrada.textChanged.connect(self._analisar)
        self.realce = CodeHighlighter(self.entrada.document(), "code")
        raiz.addWidget(self.entrada, 3)

        rotulo = QLabel("O QUE VAI VIRAR")
        rotulo.setObjectName("sectionTitle")
        raiz.addWidget(rotulo)

        self.previa = QPlainTextEdit()
        self.previa.setReadOnly(True)
        self.previa.setFont(mono(9))
        self.previa.setFrameShape(QFrame.Shape.NoFrame)
        raiz.addWidget(self.previa, 2)

        rodape = QHBoxLayout()
        self.aviso_erro = QLabel("")
        self.aviso_erro.setWordWrap(True)
        rodape.addWidget(self.aviso_erro, 1)
        raiz.addLayout(rodape)

        self.botoes = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.botoes.button(QDialogButtonBox.StandardButton.Ok).setText("Aplicar")
        self.botoes.accepted.connect(self.accept)
        self.botoes.rejected.connect(self.reject)
        raiz.addWidget(self.botoes)

        self._analisar()

    def _analisar(self) -> None:
        texto = self.entrada.toPlainText().strip()
        if not texto:
            self.previa.setPlainText("")
            self.aviso_erro.setText("")
            self.botoes.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
            return

        dados = curl_import.importar(texto)
        self.resultado = dados

        if dados.erro:
            self.previa.setPlainText("")
            self.aviso_erro.setText(dados.erro)
            self.aviso_erro.setStyleSheet(f"color: {theme.ERR};")
            self.botoes.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
            return

        linhas = [f"{dados.method}  {dados.url}"]
        if dados.params:
            linhas.append("")
            linhas.append("query:")
            linhas += [f"  {p['key']} = {p['value']}" for p in dados.params]
        if dados.headers:
            linhas.append("")
            linhas.append("headers:")
            linhas += [f"  {h['key']}: {h['value']}" for h in dados.headers]
        if dados.auth:
            linhas.append("")
            linhas.append(f"auth: {dados.auth.get('type')}, usuario {dados.auth.get('username')}")
        if dados.body.get("mode") != "none":
            linhas.append("")
            linhas.append(f"corpo, modo {dados.body['mode']}:")
            corpo = dados.body["raw"]
            linhas.append("  " + (corpo if len(corpo) <= 600 else corpo[:600] + " …"))
        if dados.settings:
            linhas.append("")
            linhas.append(f"ajustes: {dados.settings}")

        self.previa.setPlainText("\n".join(linhas))
        self.botoes.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

        if dados.ignorados:
            self.aviso_erro.setText(
                "nao entendi e deixei de fora: " + ", ".join(dados.ignorados)
            )
            self.aviso_erro.setStyleSheet(f"color: {theme.WARN};")
        else:
            self.aviso_erro.setText("")

    @staticmethod
    def pedir(texto: str = "", nome: str = "", parent=None) -> curl_import.Importado | None:
        dialogo = CurlDialog(texto, nome, parent)
        if dialogo.exec() == QDialog.DialogCode.Accepted:
            return dialogo.resultado
        return None
