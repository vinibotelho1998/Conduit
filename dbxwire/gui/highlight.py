"""Realce de sintaxe e o tooltip de variavel, nativos, sem dependencia externa.

As cores nao sao literais aqui dentro. Elas vem do tema em uso e sao refeitas quando ele
troca. Congeladas no import, como estavam antes, o tema claro exibia JSON em verde e azul
fluorescente sobre fundo branco.
"""

from __future__ import annotations

import html
import re
import weakref

from PySide6.QtCore import QEvent, QObject, QPoint, QRegularExpression
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextCursor

from ..core.scopes import SCOPE_LABEL
from . import theme


def _fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    if bold:
        fmt.setFontWeight(QFont.Weight.DemiBold)
    if italic:
        fmt.setFontItalic(True)
    return fmt


def cor_do_escopo(escopo: str) -> str:
    """A cor de cada escopo de variavel, sempre pela paleta do tema em uso.

    O mapa equivalente ainda existe em core/scopes.py com hex fixo, mas quem desenha
    pergunta aqui: cor de interface guardada no core nao alcanca a troca de tema, e o
    roxo do escopo collection continuava fluorescente sobre branco.
    """
    return {
        "globais": theme.P["texto_medio"],
        "collection": theme.CODIGO["palavra"],
        "pasta": theme.P["ok"],
        "ambiente": theme.P["marca"],
        "execucao": theme.P["aviso"],
    }.get(escopo, theme.P["texto_medio"])


PALAVRAS = (
    "import|from|as|with|const|let|var|function|func|return|await|async|class|def|"
    "public|private|static|void|using|new|package|if|else|for|in|nil|null|None|True|"
    "False|true|false|print|println|Console|WriteLine|console|log|panic|defer"
)

# Preenchidas por montar_regras, no fim do arquivo e a cada troca de tema.
JSON_RULES: list = []
XML_RULES: list = []
CODE_RULES: list = []

VAR_RE = QRegularExpression(r"\{\{\s*([\w.$-]+)\s*\}\}")
VAR_PY = re.compile(r"\{\{\s*([\w.$-]+)\s*\}\}")

# As tres situacoes de uma variavel, na mesma cor em todo lugar que ela aparece:
# campo de texto, grade de headers e params, e o cartao do mouse.
COR_VAR = theme.CODIGO["variavel"]
COR_VAR_SECRETA = theme.CODIGO["variavel_secreta"]
COR_VAR_SEM_DONO = theme.CODIGO["variavel_sem_dono"]

VAR_KNOWN = _fmt(COR_VAR, bold=True)
VAR_SECRET = _fmt(COR_VAR_SECRETA, bold=True)
VAR_UNKNOWN = _fmt(COR_VAR_SEM_DONO, bold=True)

# realces vivos, por referencia fraca: o realce morre junto com o campo e a lista nao
# pode segurar widget ja fechado
_documentos: list = []


def montar_regras() -> None:
    """Reconstroi regras e formatos a partir do tema em uso, e repinta o que esta na tela."""
    global COR_VAR, COR_VAR_SECRETA, COR_VAR_SEM_DONO
    global VAR_KNOWN, VAR_SECRET, VAR_UNKNOWN

    c = theme.CODIGO

    # A ordem aqui e o que decide a cor, e nao a intencao: setFormat pinta por cima do
    # que ja estava, entao a ultima regra que casa e a que fica valendo. Do mais geral
    # pro mais especifico.
    #
    # Duas coisas que estavam erradas desde sempre por causa disso. A regra de chave
    # vinha antes da regra de string, e toda chave e uma string: a cor de chave era
    # calculada e jogada fora, entao chave e valor sempre sairam do mesmo verde. E a
    # regra de numero vinha depois da de string, entao os digitos dentro de um texto
    # eram pintados como numero, e "01001000" aparecia metade verde e metade ambar.
    JSON_RULES[:] = [
        (QRegularExpression(r"[\{\}\[\]:,]"), _fmt(c["sinal"])),
        (QRegularExpression(r"\b-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b"), _fmt(c["numero"])),
        (QRegularExpression(r"\b(?:true|false|null)\b"), _fmt(c["palavra"])),
        (QRegularExpression(r'"(?:[^"\\]|\\.)*"'), _fmt(c["texto"])),
        (QRegularExpression(r'"(?:[^"\\]|\\.)*"\s*(?=:)'), _fmt(c["chave"])),
    ]

    XML_RULES[:] = [
        (QRegularExpression(r"</?[\w:.-]+"), _fmt(c["tag"])),
        (QRegularExpression(r"[\w:.-]+(?=\=)"), _fmt(c["atributo"])),
        (QRegularExpression(r'"(?:[^"\\]|\\.)*"'), _fmt(c["texto"])),
        (QRegularExpression(r"/?>"), _fmt(c["tag"])),
        (QRegularExpression(r"<!--.*-->"), _fmt(c["comentario"], italic=True)),
    ]

    CODE_RULES[:] = [
        (QRegularExpression(r"(#|//).*$"), _fmt(c["comentario"], italic=True)),
        (
            QRegularExpression(
                r'"(?:[^"\\]|\\.)*"'
                r"|'(?:[^'\\]|\\.)*'"
                r"|`(?:[^`\\]|\\.)*`"
            ),
            _fmt(c["texto"]),
        ),
        (QRegularExpression(r"\b-?\d+(?:\.\d+)?\b"), _fmt(c["numero"])),
        (QRegularExpression(rf"\b(?:{PALAVRAS})\b"), _fmt(c["palavra"])),
    ]

    COR_VAR = c["variavel"]
    COR_VAR_SECRETA = c["variavel_secreta"]
    COR_VAR_SEM_DONO = c["variavel_sem_dono"]
    VAR_KNOWN = _fmt(COR_VAR, bold=True)
    VAR_SECRET = _fmt(COR_VAR_SECRETA, bold=True)
    VAR_UNKNOWN = _fmt(COR_VAR_SEM_DONO, bold=True)

    for ref in list(_documentos):
        alvo = ref()
        if alvo is None:
            _documentos.remove(ref)
        else:
            try:
                alvo.rehighlight()
            except RuntimeError:
                # o objeto C++ ja foi embora, so o lado Python sobrou
                _documentos.remove(ref)


def cor_da_variavel(info) -> str:
    if info is None:
        return COR_VAR_SEM_DONO
    return COR_VAR_SECRETA if info.secret else COR_VAR


class CodeHighlighter(QSyntaxHighlighter):
    """Um so highlighter por documento: linguagem embaixo, variavel por cima.

    Dois QSyntaxHighlighter no mesmo documento brigam, o segundo desliga o primeiro.
    Por isso as regras convivem aqui dentro, na ordem certa.
    """

    def __init__(self, document, language: str = "none", variables: dict | None = None):
        super().__init__(document)
        self.language = language
        self.variables = variables or {}
        _documentos.append(weakref.ref(self))

    def set_language(self, language: str) -> None:
        if language != self.language:
            self.language = language
            self.rehighlight()

    def set_variables(self, variables: dict) -> None:
        self.variables = variables or {}
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        regras = []
        if self.language == "json":
            regras = JSON_RULES
        elif self.language == "xml":
            regras = XML_RULES
        elif self.language == "code":
            regras = CODE_RULES

        for pattern, fmt in regras:
            it = pattern.globalMatch(text)
            while it.hasNext():
                match = it.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)

        it = VAR_RE.globalMatch(text)
        while it.hasNext():
            match = it.next()
            nome = match.captured(1)
            info = self.variables.get(nome)
            if info is None:
                fmt = VAR_UNKNOWN
            elif getattr(info, "secret", False):
                fmt = VAR_SECRET
            else:
                fmt = VAR_KNOWN
            self.setFormat(match.capturedStart(), match.capturedLength(), fmt)


def tooltip_for(nome: str, info) -> str:
    """Balao rico com valor, escopo de origem e onde mais o nome existe."""
    p = theme.P
    if info is None:
        return (
            f"<div style='font-family:{theme.tokens.FAMILIA.split(',')[0]}'>"
            f"<b style='color:{p['erro']}'>{html.escape(nome)}</b><br>"
            f"<span style='color:{p['texto_medio']}'>nao existe em nenhum escopo</span><br>"
            f"<span style='color:{p['texto_fraco']}'>globais, collection, pasta, ambiente ou execucao</span>"
            f"</div>"
        )

    cor = cor_do_escopo(info.scope)
    rotulo = SCOPE_LABEL.get(info.scope, info.scope)
    valor = info.masked() if info.secret else info.value

    if valor == "":
        corpo = f"<span style='color:{p['aviso']}'>definida, mas sem valor</span>"
    else:
        mostrado = html.escape(valor if len(valor) <= 300 else valor[:300] + "…")
        corpo = (
            f"<span style='color:{p['texto']};"
            f"font-family:{theme.tokens.FAMILIA_MONO.split(',')[0]}'>{mostrado}</span>"
        )

    miudo = f"font-size:{theme.tokens.FONTE['micro']}pt"
    partes = [
        f"<div style='font-family:{theme.tokens.FAMILIA.split(',')[0]}'>",
        f"<b style='color:{cor}'>{html.escape(nome)}</b>",
        f" <span style='color:{cor};{miudo}'>{rotulo}</span>",
        f" <span style='color:{p['texto_fraco']};{miudo}'>{html.escape(info.origin)}</span><br>",
        corpo,
    ]
    if info.secret:
        partes.append(
            f"<br><span style='color:{COR_VAR_SECRETA};{miudo}'>"
            f"valor secreto, nunca vai pro historico em claro</span>"
        )
    if info.shadowed:
        outros = ", ".join(
            f"{SCOPE_LABEL.get(s.scope, s.scope)} {s.origin}".strip() for s in info.shadowed
        )
        partes.append(
            f"<br><span style='color:{p['texto_fraco']};{miudo}'>"
            f"tambem definida em {html.escape(outros)}, e perdeu por precedencia</span>"
        )
    partes.append("</div>")
    return "".join(partes)


class VarTooltip(QObject):
    """Mostra o cartao da variavel sob o cursor em qualquer editor de texto do Qt.

    Precisa ser QObject porque so QObject serve de filtro de evento no Qt. Anexa no
    viewport, entao serve pro campo de url e pro corpo sem duplicar codigo.

    O cartao ancora embaixo da propria variavel, e nao no cursor. Colado no cursor ele
    tapa justamente o que voce esta apontando, que era o problema do balao padrao.
    """

    def __init__(self, editor, provider):
        super().__init__(editor)
        self.editor = editor
        self.provider = provider  # callable que devolve o mapa de variaveis
        self._nome_atual = None
        editor.setMouseTracking(True)
        editor.viewport().setMouseTracking(True)
        editor.viewport().installEventFilter(self)
        editor._var_tooltip = self  # segura a referencia

    def eventFilter(self, obj, event):  # noqa: N802
        tipo = event.type()
        if tipo == QEvent.Type.MouseMove:
            self._maybe_show(event)
        elif tipo in (QEvent.Type.Leave, QEvent.Type.FocusOut, QEvent.Type.Wheel):
            self._esconder()
        return False

    def _esconder(self) -> None:
        from .var_popup import VarPopup

        self._nome_atual = None
        VarPopup.esconder()

    def _maybe_show(self, event) -> None:
        from .var_popup import VarPopup

        cursor = self.editor.cursorForPosition(event.position().toPoint())
        bloco = cursor.block()
        texto = bloco.text()
        coluna = cursor.positionInBlock()

        for match in VAR_PY.finditer(texto):
            if match.start() <= coluna <= match.end():
                nome = match.group(1)
                if nome == self._nome_atual:
                    return  # ja esta na tela, nao pisca a cada pixel de movimento
                self._nome_atual = nome

                info = (self.provider() or {}).get(nome)
                popup = VarPopup.instancia()
                popup.preencher(nome, info)

                # ancora no inicio do token, logo abaixo da linha
                inicio = QTextCursor(bloco)
                inicio.setPosition(bloco.position() + match.start())
                area = self.editor.cursorRect(inicio)
                ponto = self.editor.viewport().mapToGlobal(
                    QPoint(area.left(), area.bottom() + 4)
                )
                popup.mostrar_em(ponto)
                return

        self._esconder()


def guess_language(text: str, content_type: str = "") -> str:
    ct = (content_type or "").lower()
    stripped = (text or "").lstrip()
    if "json" in ct or stripped.startswith(("{", "[")):
        return "json"
    if "xml" in ct or "html" in ct or stripped.startswith("<"):
        return "xml"
    return "none"


montar_regras()
theme.ao_trocar(montar_regras)
