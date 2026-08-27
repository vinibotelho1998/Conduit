"""Aba Auth do request, da pasta e da collection."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.auth import TIPOS
from . import theme
from .highlight import CodeHighlighter, VarTooltip
from .request_editor import UrlEdit, mono


class CampoVar(UrlEdit):
    """Campo de uma linha com realce de {{variavel}} e o cartao no mouse."""

    def __init__(self, dica: str = "", segredo: bool = False, parent=None):
        super().__init__("", parent)
        self.setPlaceholderText(dica)
        self.setFont(mono(9))
        self.setFixedHeight(34)
        self.segredo = segredo


class AuthEditor(QWidget):
    changed = Signal()

    def __init__(self, dono: dict, mostrar_heranca: bool = True, parent=None):
        super().__init__(parent)
        self.dono = dono
        self._variaveis: dict = {}
        self._plano: dict = {}
        self._carregando = True
        dono.setdefault("auth", {"type": "inherit" if mostrar_heranca else "none"})

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(14, 12, 14, 12)
        raiz.setSpacing(10)

        topo = QHBoxLayout()
        topo.setSpacing(10)
        rotulo = QLabel("Tipo")
        rotulo.setObjectName("hint")
        topo.addWidget(rotulo)

        self.combo = QComboBox()
        for chave, texto in TIPOS.items():
            if chave == "inherit" and not mostrar_heranca:
                continue
            self.combo.addItem(texto, chave)
        self.combo.setMinimumWidth(230)
        self.combo.currentIndexChanged.connect(self._trocou_tipo)
        topo.addWidget(self.combo)

        self.heranca = QLabel("")
        self.heranca.setObjectName("hint")
        topo.addWidget(self.heranca, 1)
        raiz.addLayout(topo);

        linha = QFrame()
        linha.setFixedHeight(1)
        linha.setStyleSheet(f"background: {theme.BORDER};")
        raiz.addWidget(linha)

        self.paginas = QStackedWidget()
        self.campos: dict[str, CampoVar] = {}
        self.indices: dict[str, int] = {}

        self.indices["none"] = self.paginas.addWidget(
            self._aviso("Este request sai sem credencial nenhuma.")
        )
        self.indices["inherit"] = self.paginas.addWidget(
            self._aviso("Usa a auth da pasta mais proxima, e se ela tambem herdar, da collection.")
        )
        self.indices["bearer"] = self.paginas.addWidget(
            self._formulario([("token", "Token", "cole o token ou use {{variavel}}", True)])
        )
        self.indices["basic"] = self.paginas.addWidget(
            self._formulario(
                [
                    ("username", "Usuario", "usuario", False),
                    ("password", "Senha", "senha ou {{variavel}}", True),
                ]
            )
        )
        self.indices["apikey"] = self.paginas.addWidget(self._pagina_apikey())
        self.indices["oauth2"] = self.paginas.addWidget(
            self._formulario(
                [
                    ("tokenUrl", "URL do token", "https://idp/oauth2/token", False),
                    ("clientId", "Client id", "{{clientId}}", False),
                    ("clientSecret", "Client secret", "{{clientSecret}}", True),
                    ("scope", "Scope", "opcional", False),
                    ("audience", "Audience", "opcional", False),
                ],
                rodape="O token fica no cofre e e reaproveitado ate perto de expirar.",
            )
        )
        raiz.addWidget(self.paginas, 1)

        self.resumo = QLabel("")
        self.resumo.setObjectName("hint")
        self.resumo.setWordWrap(True)
        raiz.addWidget(self.resumo)

        self._carregar()
        self._carregando = False

    # ---------------------------------------------------------------- montagem

    def _aviso(self, texto: str) -> QWidget:
        caixa = QWidget()
        layout = QVBoxLayout(caixa)
        layout.setContentsMargins(0, 8, 0, 0)
        cartao = QFrame()
        cartao.setObjectName("card")
        interno = QVBoxLayout(cartao)
        interno.setContentsMargins(16, 14, 16, 14)
        rotulo = QLabel(texto)
        rotulo.setObjectName("hint")
        rotulo.setWordWrap(True)
        interno.addWidget(rotulo)
        layout.addWidget(cartao)
        layout.addStretch(1)
        return caixa

    def _formulario(self, campos, rodape: str = "") -> QWidget:
        caixa = QWidget()
        layout = QVBoxLayout(caixa)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        for nome, rotulo, dica, segredo in campos:
            campo = CampoVar(dica, segredo)
            campo.textChanged.connect(self._campo_mudou)
            campo.url_hl = CodeHighlighter(campo.document(), "none")
            VarTooltip(campo, lambda: self._variaveis)
            self.campos[nome] = campo
            form.addRow(rotulo, campo)
        layout.addLayout(form)

        if rodape:
            nota = QLabel(rodape)
            nota.setObjectName("hint")
            nota.setWordWrap(True)
            layout.addWidget(nota)
        layout.addStretch(1)
        return caixa

    def _pagina_apikey(self) -> QWidget:
        caixa = QWidget()
        layout = QVBoxLayout(caixa)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        form = QFormLayout()
        form.setSpacing(8)
        for nome, rotulo, dica, segredo in (
            ("key", "Nome", "X-Api-Key", False),
            ("value", "Valor", "{{apiKey}}", True),
        ):
            campo = CampoVar(dica, segredo)
            campo.textChanged.connect(self._campo_mudou)
            campo.url_hl = CodeHighlighter(campo.document(), "none")
            VarTooltip(campo, lambda: self._variaveis)
            self.campos[nome] = campo
            form.addRow(rotulo, campo)

        self.onde = QComboBox()
        self.onde.addItem("no header", "header")
        self.onde.addItem("na query", "query")
        self.onde.currentIndexChanged.connect(self._campo_mudou)
        form.addRow("Mandar", self.onde)
        layout.addLayout(form)
        layout.addStretch(1)
        return caixa

    # ------------------------------------------------------------------ dados

    def _carregar(self) -> None:
        config = self.dono.get("auth") or {}
        tipo = config.get("type") or "none"
        indice = self.combo.findData(tipo)
        self.combo.setCurrentIndex(indice if indice >= 0 else 0)

        for nome, campo in self.campos.items():
            campo.setPlainText(config.get(nome) or "")
        if hasattr(self, "onde"):
            posicao = self.onde.findData(config.get("in") or "header")
            self.onde.setCurrentIndex(max(0, posicao))
        self._mostrar_pagina(tipo)

    def _mostrar_pagina(self, tipo: str) -> None:
        self.paginas.setCurrentIndex(self.indices.get(tipo, self.indices["none"]))

    def _trocou_tipo(self) -> None:
        tipo = self.combo.currentData()
        self._mostrar_pagina(tipo)
        if not self._carregando:
            self.dono.setdefault("auth", {})["type"] = tipo
            self._guardar()

    def _campo_mudou(self) -> None:
        if not self._carregando:
            self._guardar()

    def _guardar(self) -> None:
        config = self.dono.setdefault("auth", {})
        config["type"] = self.combo.currentData()
        for nome, campo in self.campos.items():
            texto = campo.toPlainText()
            if texto:
                config[nome] = texto
            else:
                config.pop(nome, None)
        # `in` so faz sentido pra api key. Deixar sempre gravado sujava o arquivo do
        # request com um campo que nao vale pro tipo escolhido.
        if config["type"] == "apikey" and hasattr(self, "onde"):
            config["in"] = self.onde.currentData()
        else:
            config.pop("in", None)
        self._atualizar_resumo()
        self.changed.emit()

    def _atualizar_resumo(self) -> None:
        from ..core import auth as authmod

        config = self.dono.get("auth") or {}
        tipo = config.get("type") or "none"
        if tipo in ("none", "inherit"):
            self.resumo.setText("")
            return

        # OAuth2 nao entra aqui. Chamar aplicar faria uma requisicao de rede ao provedor
        # de identidade a cada tecla digitada, o que e lento e queima rate limit.
        if tipo == "oauth2":
            url = config.get("tokenUrl") or ""
            if not url or not config.get("clientId"):
                self.resumo.setText("faltando: OAuth2 precisa de URL do token e client id")
                self.resumo.setStyleSheet(f"color: {theme.WARN}; font-size: 8pt;")
            else:
                self.resumo.setText(
                    f"vai pedir token em {url} e mandar como Authorization: "
                    f"{config.get('prefix') or 'Bearer'}"
                )
                self.resumo.setStyleSheet(f"color: {theme.FAINT}; font-size: 8pt;")
            return

        aplicada = authmod.aplicar(config, self._plano)
        if aplicada.erro:
            self.resumo.setText(f"faltando: {aplicada.erro}")
            self.resumo.setStyleSheet(f"color: {theme.WARN}; font-size: 8pt;")
        else:
            self.resumo.setText(f"vai sair como {aplicada.detalhe}")
            self.resumo.setStyleSheet(f"color: {theme.FAINT}; font-size: 8pt;")

    # --------------------------------------------------------------- publico

    def set_variables(self, variaveis: dict) -> None:
        from ..core import scopes

        # o realce e o cartao usam o mapa com escopo, o resolvedor usa o formato simples
        self._variaveis = variaveis or {}
        self._plano = scopes.as_plain(self._variaveis) if self._variaveis else {}
        for campo in self.campos.values():
            if hasattr(campo, "url_hl"):
                campo.url_hl.set_variables(self._variaveis)
        self._atualizar_resumo()

    def set_heranca(self, texto: str) -> None:
        self.heranca.setText(texto)
