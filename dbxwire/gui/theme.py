"""O tema do app: paleta ativa, folha de estilo e troca em tempo real.

Este arquivo e a unica fonte de cor da interface. Ele nao guarda valor cru, isso mora em
`tokens.py`: aqui so vive a paleta que esta em uso agora e a folha montada a partir dela.

Como o resto do app continua funcionando sem mudar. Os nomes antigos, `theme.BG`,
`theme.ACCENT` e companhia, continuam existindo e sao reescritos quando o tema muda. Como
quase todo desenho a mao le `theme.ALGUMA_COISA` na hora de pintar, e nao na hora de
importar, trocar o tema e repintar ja basta pra tela inteira virar. Quem cacheia cor no
import, como o realce de sintaxe, se registra em `ao_trocar` e reconstroi o que precisa.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from . import tokens
from .tokens import ESPACO, FAMILIA, FAMILIA_MONO, FONTE, RAIO, alfa, mistura

# ------------------------------------------------------------------- estado do tema

# nome do tema e da densidade em uso. Trocados por `aplicar`.
NOME = "escuro"
DENSIDADE = "confortavel"
P: dict = dict(tokens.ESCURO)
D: dict = dict(tokens.DENSIDADE["confortavel"])
CODIGO: dict = dict(tokens.CODIGO_ESCURO)

_ouvintes: list = []


def ao_trocar(funcao) -> None:
    """Registra quem precisa refazer cor cacheada quando o tema muda."""
    if funcao not in _ouvintes:
        _ouvintes.append(funcao)


# ---------------------------------------------------- nomes antigos, ainda em uso
# Sao rebatizados a cada troca de tema por `_espalhar`. Ficam aqui pra que os vinte e
# poucos arquivos que ja falam essa lingua nao precisem mudar de uma vez.

BG = P["fundo"]
PANEL = P["superficie"]
PANEL2 = P["superficie_alta"]
RAISE = P["elevado"]
BORDER = P["borda"]
TEXT = P["texto"]
DIM = P["texto_medio"]
FAINT = P["texto_fraco"]
ACCENT = P["marca"]
SEL = P["selecao"]
OK = P["ok"]
WARN = P["aviso"]
ERR = P["erro"]
INFO = P["info"]
FOCO = P["foco"]
METHOD_COLORS = dict(tokens.METODOS_ESCURO)
MONO = FAMILIA_MONO

# abreviacao usada na pilula quando o nome do metodo nao cabe
ABREVIACAO_METODO = {"DELETE": "DEL", "OPTIONS": "OPT"}


def _espalhar() -> None:
    """Reescreve os nomes antigos a partir da paleta ativa."""
    g = globals()
    g["BG"] = P["fundo"]
    g["PANEL"] = P["superficie"]
    g["PANEL2"] = P["superficie_alta"]
    g["RAISE"] = P["elevado"]
    g["BORDER"] = P["borda"]
    g["TEXT"] = P["texto"]
    g["DIM"] = P["texto_medio"]
    g["FAINT"] = P["texto_fraco"]
    g["ACCENT"] = P["marca"]
    g["SEL"] = P["selecao"]
    g["OK"] = P["ok"]
    g["WARN"] = P["aviso"]
    g["ERR"] = P["erro"]
    g["INFO"] = P["info"]
    g["FOCO"] = P["foco"]
    g["METHOD_COLORS"] = dict(
        tokens.METODOS_CLARO if P.get("claro") else tokens.METODOS_ESCURO
    )


# ------------------------------------------------------------------ leitura de estado


def cor(nome: str) -> str:
    """Uma cor da paleta ativa pelo papel dela."""
    return P.get(nome, P["texto"])


def medida(nome: str) -> int:
    """Uma medida da densidade ativa."""
    return D.get(nome, 0)


def escuro() -> bool:
    return not P.get("claro", False)


def tom_do_status(status, ok: bool = True) -> tuple[str, str]:
    """A cor do texto e a do fundo da pilula de status, num lugar so.

    Antes existiam quatro copias disso: no painel de resposta, no historico, na arvore e
    nos icones, com tres azuis diferentes pro 3xx. Agora quem quiser a cor de um status
    pergunta aqui.
    """
    if not ok or not isinstance(status, int):
        return P["erro"], mistura(P["erro"], P["superficie"], 0.16)
    familia = status // 100
    base = {2: P["ok"], 3: P["info"], 4: P["aviso"], 5: P["erro"]}.get(familia)
    if base is None:
        return P["texto_medio"], P["elevado"]
    return base, mistura(base, P["superficie"], 0.16)


def cor_do_status(status, ok: bool = True) -> str:
    return tom_do_status(status, ok)[0]


def cor_do_metodo(metodo: str) -> str:
    return METHOD_COLORS.get((metodo or "").upper(), P["texto_medio"])


# ------------------------------------------------------------------- folha de estilo


def _qss() -> str:
    p = P
    r = RAIO
    e = ESPACO
    d = D

    campo = d["altura_campo"]
    linha_grade = d["linha_grade"]

    # o azul de selecao de texto precisa aguentar o texto por cima; no claro ele e um
    # azul palido e a tinta continua escura, no escuro e o contrario
    selecao_texto = p["selecao_texto"]

    return f"""
QWidget {{
    background: {p["fundo"]};
    color: {p["texto"]};
    font-family: "{FAMILIA.split(",")[0]}";
    font-size: {FONTE["corpo"]}pt;
}}
QWidget:disabled {{ color: {p["texto_apagado"]}; }}

QMainWindow::separator {{ background: {p["borda"]}; width: 1px; height: 1px; }}

/* ------------------------------------------------------------------ menu e barra */

QMenuBar {{ background: {p["superficie"]}; border: 0; padding: {e[2]}px {e[3]}px; }}
QMenuBar::item {{
    padding: {e[3]}px {e[5]}px; background: transparent; border-radius: {r["medio"]}px;
    color: {p["texto_medio"]};
}}
QMenuBar::item:selected {{ background: {p["elevado"]}; color: {p["texto"]}; }}
QMenuBar::item:pressed {{ background: {p["elevado"]}; color: {p["texto"]}; }}

QMenu {{
    background: {p["flutuante"]}; border: 1px solid {p["borda_forte"]};
    border-radius: {r["grande"]}px; padding: {e[3]}px;
}}
QMenu::item {{
    padding: {e[3]}px {e[8]}px {e[3]}px {e[7]}px; border-radius: {r["pequeno"]}px;
    color: {p["texto"]};
}}
QMenu::item:selected {{ background: {p["marca_fundo"]}; color: {p["texto"]}; }}
QMenu::item:disabled {{ color: {p["texto_apagado"]}; }}
QMenu::separator {{ height: 1px; background: {p["borda"]}; margin: {e[3]}px {e[4]}px; }}
QMenu::right-arrow {{ image: url(__SETA__); width: 10px; height: 10px; margin-right: {e[4]}px; }}

QToolBar {{
    background: {p["superficie"]}; border: 0; border-bottom: 1px solid {p["borda"]};
    padding: {e[3]}px {e[4]}px; spacing: {e[4]}px;
}}
QToolBar::separator {{ background: {p["borda"]}; width: 1px; margin: {e[3]}px {e[4]}px; }}
QToolBar QToolButton {{
    background: transparent; border: 1px solid transparent; border-radius: {r["medio"]}px;
    padding: {e[3]}px {e[4]}px; color: {p["texto_medio"]};
}}
QToolBar QToolButton:hover {{ background: {p["elevado"]}; color: {p["texto"]}; }}
QToolBar QToolButton:pressed {{ background: {p["superficie_alta"]}; }}
QToolBar QToolButton:checked {{ background: {p["marca_fundo"]}; color: {p["marca"]}; }}
QToolBar QToolButton:focus {{ border-color: {p["foco"]}; }}
QToolBar QToolButton::menu-indicator {{ image: none; }}

/* ------------------------------------------------------------------------ campos */

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDateEdit {{
    background: {p["superficie_alta"]}; border: 1px solid {p["borda"]};
    border-radius: {r["medio"]}px; padding: {e[3]}px {e[5]}px;
    color: {p["texto"]};
    selection-background-color: {selecao_texto};
    selection-color: {p["texto"]};
}}
QLineEdit:hover, QPlainTextEdit:hover, QComboBox:hover {{ border-color: {p["borda_forte"]}; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border-color: {p["foco"]};
    background: {p["superficie"]};
}}
QLineEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled {{
    background: {p["fundo"]}; color: {p["texto_apagado"]};
}}
QComboBox::drop-down {{ border: 0; width: 20px; }}
QComboBox::down-arrow {{ image: url(__CHEVRON__); width: 12px; height: 12px; margin-right: {e[4]}px; }}
QComboBox QAbstractItemView {{
    background: {p["flutuante"]}; border: 1px solid {p["borda_forte"]};
    border-radius: {r["medio"]}px; selection-background-color: {p["marca_fundo"]};
    selection-color: {p["texto"]}; outline: 0; padding: {e[3]}px;
}}

/* ------------------------------------------------------------------------ botoes */

QPushButton {{
    background: {p["superficie_alta"]}; border: 1px solid {p["borda"]};
    border-radius: {r["medio"]}px; padding: {e[4]}px {e[6]}px; color: {p["texto"]};
}}
QPushButton:hover {{ background: {p["elevado"]}; border-color: {p["borda_forte"]}; }}
QPushButton:pressed {{ background: {p["superficie"]}; }}
QPushButton:focus {{ border-color: {p["foco"]}; }}
QPushButton:disabled {{ color: {p["texto_apagado"]}; background: {p["fundo"]}; }}

/* o unico botao cheio de cor da tela. Se outra coisa ficar azul solida, ele deixa de
   ser o lugar pra onde o olho vai */
QPushButton#send {{
    background: {p["marca"]}; color: {p["marca_tinta"]}; border: 1px solid {p["marca"]};
    border-radius: {r["medio"]}px; font-weight: 700; padding: {e[4]}px {e[8]}px;
}}
QPushButton#send:hover {{ background: {p["marca_clara"]}; border-color: {p["marca_clara"]}; }}
QPushButton#send:focus {{ border-color: {p["texto"]}; }}
QPushButton#send:disabled {{
    background: {mistura(p["marca"], p["fundo"], 0.35)};
    border-color: transparent; color: {p["texto_apagado"]};
}}

QPushButton#salvar {{
    background: {p["superficie_alta"]}; border: 1px solid {p["borda"]};
    border-radius: {r["medio"]}px; padding: 0 {e[6]}px; color: {p["texto"]}; font-weight: 600;
}}
QPushButton#salvar:hover {{ background: {p["elevado"]}; border-color: {p["borda_forte"]}; }}
QPushButton#salvar:disabled {{
    background: transparent; border-color: {p["borda"]}; color: {p["texto_apagado"]};
}}

QPushButton#perigo {{
    background: transparent; border: 1px solid {alfa(p["erro"], 0.45)}; color: {p["erro"]};
}}
QPushButton#perigo:hover {{ background: {alfa(p["erro"], 0.14)}; border-color: {p["erro"]}; }}

QPushButton#flat, QPushButton#link {{
    background: transparent; border: 1px solid transparent; color: {p["marca"]};
    padding: {e[3]}px {e[4]}px;
}}
QPushButton#flat:hover, QPushButton#link:hover {{
    color: {p["marca_clara"]}; background: {p["elevado"]};
}}
QPushButton#flat:focus, QPushButton#link:focus {{ border-color: {p["foco"]}; }}

/* botao sem moldura fora da toolbar: rodape, cabecalho de painel, barra da resposta.
   Antes cada painel escrevia a propria versao com setStyleSheet, cinco vezes, com cinco
   raios diferentes. */
QToolButton#silencioso {{
    background: transparent; border: 1px solid transparent; border-radius: {r["medio"]}px;
    padding: {e[3]}px {e[4]}px; color: {p["texto_medio"]};
}}
QToolButton#silencioso:hover {{ background: {p["elevado"]}; color: {p["texto"]}; }}
QToolButton#silencioso:pressed {{ background: {p["superficie_alta"]}; }}
QToolButton#silencioso:checked {{ background: {p["marca_fundo"]}; color: {p["marca"]}; }}
QToolButton#silencioso:focus {{ border-color: {p["foco"]}; }}
QToolButton#silencioso:disabled {{ color: {p["texto_apagado"]}; }}

/* ------------------------------------------------------------- listas e arvores */

QTreeWidget, QTreeView, QTableWidget, QTableView, QListWidget, QListView {{
    background: {p["superficie"]}; border: 0; outline: 0;
    alternate-background-color: {p["superficie"]};
    selection-background-color: {p["selecao"]};
    selection-color: {p["texto"]};
}}
QTreeWidget::item, QListWidget::item {{
    height: {d["linha_arvore"]}px; border-radius: {r["pequeno"]}px; color: {p["texto"]};
}}
QTreeWidget::item:hover, QListWidget::item:hover {{ background: {p["hover"]}; }}
QTreeWidget::item:selected, QListWidget::item:selected {{
    background: {p["selecao"]}; color: {p["texto"]};
}}
/* A arvore de collections pinta a linha inteira por conta propria. Deixando o estilo
   pintar tambem, a coluna do recuo virava um bloco arredondado solto na esquerda. */
QTreeWidget#arvore::item, QTreeWidget#arvore::branch {{ background: transparent; }}
QTreeWidget#arvore::item:hover, QTreeWidget#arvore::branch:hover {{ background: transparent; }}
QTreeWidget#arvore::item:selected, QTreeWidget#arvore::branch:selected {{
    background: transparent; color: {p["texto"]};
}}

QHeaderView::section {{
    background: {p["superficie"]}; color: {p["texto_fraco"]}; border: 0;
    border-bottom: 1px solid {p["borda"]};
    padding: {e[3]}px {e[4]}px; font-size: {FONTE["micro"]}pt;
    text-transform: uppercase; letter-spacing: 0.6px; font-weight: 600;
}}
QHeaderView::section:hover {{ color: {p["texto_medio"]}; }}

QTableWidget, QTableView {{ background: {p["superficie"]}; gridline-color: {p["borda"]}; }}
QTableWidget::item, QTableView::item {{ padding: {e[2]}px {e[4]}px; }}
QTableWidget::item:selected, QTableView::item:selected {{
    background: {p["selecao"]}; color: {p["texto"]};
}}
/* caixa de marcar e botao de apagar moram dentro da celula. Sem fundo transparente eles
   pintam o proprio retangulo por cima da marca da linha escolhida. */
QTableWidget QCheckBox, QTableWidget QAbstractButton {{ background: transparent; }}
/* O campo que nasce ao editar uma celula e um QLineEdit comum, e herdava o respiro dos
   campos grandes: dentro de uma linha de 30 o texto saia esmagado. */
QAbstractItemView QLineEdit, QAbstractItemView QPlainTextEdit {{
    padding: 0 {e[3]}px; border-radius: {r["pequeno"]}px;
    border: 1px solid {p["foco"]}; background: {p["superficie_alta"]};
    min-height: {linha_grade - 6}px;
}}

/* ---------------------------------------------------------------------- abas */

QTabWidget::pane {{ border: 0; border-top: 1px solid {p["borda"]}; }}
QTabBar {{ qproperty-drawBase: 0; background: transparent; }}
QTabBar::tab {{
    background: transparent; color: {p["texto_medio"]};
    padding: {e[4]}px {e[5]}px; margin-right: {e[1]}px;
    border: 1px solid transparent; border-bottom: 2px solid transparent;
    border-top-left-radius: {r["pequeno"]}px; border-top-right-radius: {r["pequeno"]}px;
}}
QTabBar::tab:hover {{ color: {p["texto"]}; background: {p["hover"]}; }}
QTabBar::tab:selected {{ color: {p["texto"]}; border-bottom-color: {p["marca"]}; }}
QTabBar::tab:disabled {{ color: {p["texto_apagado"]}; }}
QTabBar::tab:focus {{ border: 1px solid {p["foco"]}; border-bottom: 2px solid {p["marca"]}; }}
QTabBar QToolButton {{
    background: {p["superficie_alta"]}; border: 1px solid {p["borda"]};
    border-radius: {r["pequeno"]}px; color: {p["texto_medio"]}; margin: {e[2]}px;
}}
QTabBar QToolButton:hover {{ background: {p["elevado"]}; color: {p["texto"]}; }}

/* a lateral tem quatro abas em pouco espaco, entao aperta o respiro horizontal */
QTabWidget#sideTabs > QTabBar::tab {{ padding: {e[4]}px {e[4]}px; margin-right: 0px; }}

/* --------------------------------------------------------------- divisor e rolagem */

QSplitter::handle {{ background: transparent; }}

QScrollBar:vertical {{ background: transparent; width: 11px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {p["barra_rolagem"]}; border-radius: 4px; min-height: 32px; margin: 2px;
}}
QScrollBar::handle:vertical:hover {{ background: {p["barra_rolagem_sob"]}; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 0; }}
QScrollBar::handle:horizontal {{
    background: {p["barra_rolagem"]}; border-radius: 4px; min-width: 32px; margin: 2px;
}}
QScrollBar::handle:horizontal:hover {{ background: {p["barra_rolagem_sob"]}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ------------------------------------------------------------- marcar e escolher */

QCheckBox {{ spacing: {e[4]}px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border: 1px solid {p["borda_forte"]};
    border-radius: {r["micro"]}px; background: {p["superficie_alta"]};
}}
QCheckBox::indicator:hover {{ border-color: {p["texto_fraco"]}; }}
QCheckBox::indicator:checked {{
    background: {p["marca"]}; border-color: {p["marca"]}; image: url(__VISTO__);
}}
QCheckBox::indicator:checked:hover {{
    background: {p["marca_clara"]}; border-color: {p["marca_clara"]};
}}
QCheckBox:focus::indicator, QCheckBox::indicator:focus {{ border-color: {p["foco"]}; }}

QRadioButton {{ spacing: {e[4]}px; }}
QRadioButton::indicator {{
    width: 15px; height: 15px; border: 1px solid {p["borda_forte"]};
    border-radius: 8px; background: {p["superficie_alta"]};
}}
QRadioButton::indicator:hover {{ border-color: {p["texto_fraco"]}; }}
QRadioButton::indicator:checked {{
    background: {p["superficie_alta"]}; border-color: {p["marca"]}; image: url(__PONTO__);
}}
QRadioButton:focus::indicator, QRadioButton::indicator:focus {{ border-color: {p["foco"]}; }}

/* ---------------------------------------------------------------- textos avulsos */

QLabel {{ background: transparent; }}
QLabel#hint {{ color: {p["texto_fraco"]}; }}
QLabel#sectionTitle {{
    color: {p["texto_fraco"]}; font-size: {FONTE["micro"]}pt; letter-spacing: 1px;
    font-weight: 600; text-transform: uppercase;
}}
QLabel#titulo {{ color: {p["texto"]}; font-size: {FONTE["titulo"]}pt; font-weight: 600; }}
QLabel#vazio {{ color: {p["texto_fraco"]}; font-size: {FONTE["medio"]}pt; }}

QFrame#card {{
    background: {p["superficie"]}; border: 1px solid {p["borda"]};
    border-radius: {r["cartao"]}px;
}}
QFrame#divisorH {{ background: {p["borda"]}; max-height: 1px; min-height: 1px; border: 0; }}
QFrame#divisorV {{ background: {p["borda"]}; max-width: 1px; min-width: 1px; border: 0; }}

QToolTip {{
    background: {p["flutuante"]}; color: {p["texto"]}; border: 1px solid {p["borda_forte"]};
    border-radius: {r["medio"]}px; padding: {e[3]}px {e[4]}px;
}}

QDialog {{ background: {p["fundo"]}; }}
QDialogButtonBox QPushButton {{ min-width: 86px; }}

QProgressBar {{
    background: {p["superficie_alta"]}; border: 0; border-radius: 3px;
    height: 4px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {p["marca"]}; border-radius: 3px; }}

QGroupBox {{
    border: 1px solid {p["borda"]}; border-radius: {r["grande"]}px;
    margin-top: {e[5]}px; padding-top: {e[5]}px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: {e[5]}px; padding: 0 {e[3]}px;
    color: {p["texto_fraco"]}; font-size: {FONTE["micro"]}pt;
    text-transform: uppercase; letter-spacing: 1px;
}}
"""


# ------------------------------------------------------------------- desenhos em png
# A folha de estilo do Qt nao desenha forma nenhuma: triangulo feito com borda vira
# quadradinho e caixa marcada sem imagem fica um bloco azul liso. Entao estes tres saem
# de um QPainter e viram arquivo. O nome do arquivo carrega o tema, senao o visto do
# escuro continua no claro depois de trocar.


def _caneta(painter, cor_traco: str, largura: float):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPen

    caneta = QPen(QColor(cor_traco))
    caneta.setWidthF(largura)
    caneta.setCapStyle(Qt.PenCapStyle.RoundCap)
    caneta.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(caneta)
    return caneta


def _novo_pixmap(lado: int):
    """Pixmap com o dobro da resolucao, pra nao sair borrado em tela 4K com escala."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPainter, QPixmap

    pix = QPixmap(lado * 2, lado * 2)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(2.0, 2.0)
    return pix, painter


def _desenhar_chevron(destino: Path) -> bool:
    from PySide6.QtCore import QPointF

    pix, painter = _novo_pixmap(12)
    _caneta(painter, P["texto_fraco"], 1.6)
    painter.drawPolyline([QPointF(3, 4.8), QPointF(6, 7.8), QPointF(9, 4.8)])
    painter.end()
    return pix.save(str(destino))


def _desenhar_seta(destino: Path) -> bool:
    from PySide6.QtCore import QPointF

    pix, painter = _novo_pixmap(10)
    _caneta(painter, P["texto_fraco"], 1.5)
    painter.drawPolyline([QPointF(3.6, 2.6), QPointF(6.8, 5.0), QPointF(3.6, 7.4)])
    painter.end()
    return pix.save(str(destino))


def _desenhar_visto(destino: Path) -> bool:
    from PySide6.QtCore import QPointF

    pix, painter = _novo_pixmap(16)
    _caneta(painter, tokens.tinta_sobre(P["marca"]), 2.1)
    painter.drawPolyline([QPointF(4.0, 8.3), QPointF(6.9, 11.2), QPointF(12.0, 5.2)])
    painter.end()
    return pix.save(str(destino))


def _desenhar_ponto(destino: Path) -> bool:
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor

    pix, painter = _novo_pixmap(15)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(P["marca"]))
    painter.drawEllipse(QRectF(3.6, 3.6, 7.8, 7.8))
    painter.end()
    return pix.save(str(destino))


_DESENHOS = (
    ("__CHEVRON__", "chevron", _desenhar_chevron),
    ("__VISTO__", "visto", _desenhar_visto),
    ("__PONTO__", "ponto", _desenhar_ponto),
    ("__SETA__", "seta", _desenhar_seta),
)


def folha() -> str:
    """A folha de estilo pronta, com os desenhos ja resolvidos em arquivo.

    Precisa ser funcao e nao constante porque desenhar exige o QApplication de pe.
    """
    pasta = Path(tempfile.gettempdir())
    pronta = _qss()
    for marca, nome, desenho in _DESENHOS:
        destino = pasta / f"dbx-wire-{nome}-{NOME}.png"
        try:
            if not destino.exists():
                desenho(destino)
            if destino.exists():
                pronta = pronta.replace(marca, destino.as_posix())
                continue
        except Exception:  # noqa: BLE001
            pass
        # sem o arquivo, some com a regra e o Qt desenha do jeito padrao dele
        pronta = pronta.replace(f"image: url({marca});", "")
    return pronta


# ------------------------------------------------------------------------- aplicar


def paleta_qt():
    """QPalette na cor do tema.

    Tudo que a folha de estilo nao cobre cai na palete do estilo Fusion, que e cinza
    claro. Era por isso que menu de contexto de campo de texto, seletor de arquivo e
    cabecalho de rolagem apareciam brancos no meio do tema escuro.
    """
    from PySide6.QtGui import QColor, QPalette

    pal = QPalette()
    c = QColor
    grupos = (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive)
    for grupo in grupos:
        pal.setColor(grupo, QPalette.ColorRole.Window, c(P["fundo"]))
        pal.setColor(grupo, QPalette.ColorRole.WindowText, c(P["texto"]))
        pal.setColor(grupo, QPalette.ColorRole.Base, c(P["superficie_alta"]))
        pal.setColor(grupo, QPalette.ColorRole.AlternateBase, c(P["superficie"]))
        pal.setColor(grupo, QPalette.ColorRole.Text, c(P["texto"]))
        pal.setColor(grupo, QPalette.ColorRole.Button, c(P["superficie_alta"]))
        pal.setColor(grupo, QPalette.ColorRole.ButtonText, c(P["texto"]))
        pal.setColor(grupo, QPalette.ColorRole.ToolTipBase, c(P["flutuante"]))
        pal.setColor(grupo, QPalette.ColorRole.ToolTipText, c(P["texto"]))
        pal.setColor(grupo, QPalette.ColorRole.Highlight, c(P["selecao"]))
        pal.setColor(grupo, QPalette.ColorRole.HighlightedText, c(P["texto"]))
        pal.setColor(grupo, QPalette.ColorRole.Link, c(P["marca"]))
        pal.setColor(grupo, QPalette.ColorRole.PlaceholderText, c(P["texto_apagado"]))
    apagado = QPalette.ColorGroup.Disabled
    pal.setColor(apagado, QPalette.ColorRole.Text, c(P["texto_apagado"]))
    pal.setColor(apagado, QPalette.ColorRole.ButtonText, c(P["texto_apagado"]))
    pal.setColor(apagado, QPalette.ColorRole.WindowText, c(P["texto_apagado"]))
    return pal


def aplicar(app, nome: str | None = None, densidade: str | None = None) -> None:
    """Troca tema ou densidade e repinta o app inteiro, sem reabrir a janela."""
    global NOME, DENSIDADE, P, D, CODIGO

    if nome and nome in tokens.PALETAS:
        NOME = nome
    if densidade and densidade in tokens.DENSIDADE:
        DENSIDADE = densidade

    P = dict(tokens.PALETAS[NOME])
    D = dict(tokens.DENSIDADE[DENSIDADE])
    CODIGO = dict(tokens.CODIGO_CLARO if P.get("claro") else tokens.CODIGO_ESCURO)
    _espalhar()

    for ouvinte in list(_ouvintes):
        try:
            ouvinte()
        except Exception:  # noqa: BLE001
            pass

    if app is not None:
        app.setPalette(paleta_qt())
        app.setStyleSheet(folha())
        for janela in app.topLevelWidgets():
            _repintar(janela)


def _repintar(widget) -> None:
    """Manda o widget e tudo dentro dele se redesenhar depois da troca de tema."""
    from PySide6.QtWidgets import QApplication

    estilo = widget.style()
    estilo.unpolish(widget)
    estilo.polish(widget)
    widget.update()
    for filho in widget.findChildren(object):
        if hasattr(filho, "update") and hasattr(filho, "style"):
            try:
                filho.style().unpolish(filho)
                filho.style().polish(filho)
                filho.update()
            except Exception:  # noqa: BLE001
                pass
    QApplication.processEvents()


_espalhar()
