"""Paleta e folha de estilo do app."""

from __future__ import annotations

import tempfile
from pathlib import Path

BG = "#14161b"
PANEL = "#1a1d24"
PANEL2 = "#1f232b"
RAISE = "#252a33"
BORDER = "#2a2f3a"
TEXT = "#d8dde5"
DIM = "#98a1b0"
FAINT = "#6b7484"
ACCENT = "#4da3ff"
# azul da marca de escolhido, ja misturado com o fundo. rgba na folha de estilo do
# Qt e traicoeiro: quando ele nao entende o valor, joga a regra fora e cai no azul
# chapado do sistema, que na grade vira uma tarja acesa
SEL = "#1d3149"
OK = "#49cc90"
WARN = "#fca130"
ERR = "#f9506b"

# Sete metodos, sete matizes espacadas no circulo de cor. As anteriores colidiam:
# PUT quase igual ao azul da interface, PATCH quase igual ao verde do GET, e OPTIONS
# em cinza parecia campo desligado em vez de metodo.
#
#   GET      145 graus   verde
#   PATCH    177 graus   turquesa
#   PUT      210 graus   azul
#   HEAD     275 graus   violeta
#   DELETE   355 graus   vermelho
#   POST      25 graus   laranja
#   OPTIONS   48 graus   amarelo
METHOD_COLORS = {
    "GET": "#38d47a",
    "POST": "#ff8c42",
    "PUT": "#4d9bff",
    "PATCH": "#16d0c4",
    "DELETE": "#ff4d5e",
    "HEAD": "#b06bff",
    "OPTIONS": "#ecc94b",
}

MONO = "Cascadia Code, Consolas, Courier New, monospace"

QSS = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: "Segoe UI";
    font-size: 10pt;
}}

QMainWindow::separator {{ background: {BORDER}; width: 1px; height: 1px; }}

QMenuBar {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; padding: 2px; }}
QMenuBar::item {{ padding: 5px 12px; background: transparent; border-radius: 7px; }}
QMenuBar::item:selected {{ background: {RAISE}; }}
QMenu {{ background: {PANEL2}; border: 1px solid {BORDER}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 28px 7px 22px; border-radius: 7px; }}
QMenu::item:selected {{ background: {RAISE}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 6px; }}

QToolBar {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; padding: 4px 8px; spacing: 8px; }}
QToolBar QToolButton {{
    background: {PANEL2}; border: 1px solid {BORDER}; border-radius: 6px;
    padding: 5px 10px; color: {TEXT};
}}
QToolBar QToolButton:hover {{ border-color: {ACCENT}; }}
QToolBar QToolButton::menu-indicator {{ image: none; }}

QStatusBar {{ background: {PANEL}; border-top: 1px solid {BORDER}; color: {FAINT}; }}
QStatusBar::item {{ border: 0; }}

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {{
    background: {PANEL2}; border: 1px solid {BORDER}; border-radius: 9px;
    padding: 7px 11px; selection-background-color: #2f6fb5;
}}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: 0; width: 18px; }}
QComboBox::down-arrow {{ image: url(__CHEVRON__); width: 12px; height: 12px; margin-right: 6px; }}
QComboBox QAbstractItemView {{
    background: {PANEL2}; border: 1px solid {BORDER}; border-radius: 9px;
    selection-background-color: {RAISE}; outline: 0; padding: 5px;
}}

QPushButton {{
    background: {PANEL2}; border: 1px solid {BORDER}; border-radius: 9px; padding: 8px 17px;
}}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {FAINT}; }}
QPushButton#send {{
    background: {ACCENT}; color: #0d1017; border: 0; font-weight: 700; padding: 6px 24px;
}}
QPushButton#send:hover {{ background: #66b0ff; }}
QPushButton#send:disabled {{ background: #2f4a68; color: #7d8794; }}
QPushButton#flat {{ background: transparent; border: 0; color: {ACCENT}; padding: 4px 8px; }}
QPushButton#flat:hover {{ color: #7dbcff; }}

QTreeWidget, QTableWidget, QListWidget {{
    background: {PANEL}; border: 0; outline: 0;
    alternate-background-color: {PANEL};
}}
QTreeWidget::item {{ height: 30px; border-radius: 7px; }}
QTreeWidget::item:hover {{ background: {PANEL2}; }}
QTreeWidget::item:selected {{ background: {RAISE}; color: {TEXT}; }}
/* A arvore de collections pinta a linha inteira por conta propria. Deixando o estilo
   pintar tambem, a coluna do recuo virava um bloco arredondado solto na esquerda e o
   nome ficava num retangulo separado, com costura no meio. */
QTreeWidget#arvore::item {{ background: transparent; }}
QTreeWidget#arvore::item:hover {{ background: transparent; }}
QTreeWidget#arvore::item:selected {{ background: transparent; color: {TEXT}; }}
QTreeWidget#arvore::branch {{ background: transparent; }}
QTreeWidget#arvore::branch:hover {{ background: transparent; }}
QTreeWidget#arvore::branch:selected {{ background: transparent; }}

QHeaderView::section {{
    background: {BG}; color: {FAINT}; border: 0; border-bottom: 1px solid {BORDER};
    padding: 7px 10px; font-size: 8.5pt; text-transform: uppercase; letter-spacing: 0.5px;
}}
QTableWidget {{ background: {BG}; gridline-color: {PANEL2}; }}
/* caixa de marcar e botao de apagar moram dentro da celula. Sem fundo transparente
   eles pintam o proprio retangulo por cima da marca da linha escolhida. */
QTableWidget QCheckBox, QTableWidget QAbstractButton {{ background: transparent; }}
QTableWidget::item {{ padding: 3px 8px; }}
/* O campo que nasce ao editar uma celula e um QLineEdit comum, entao herdava o respiro
   dos campos grandes: 7px em cima e embaixo dentro de uma linha de 28 nao cabe, e o
   texto saia esmagado. Dentro de grade ele fica rente. */
QAbstractItemView QLineEdit, QAbstractItemView QPlainTextEdit {{
    padding: 0 7px; border-radius: 8px; border: 1px solid {ACCENT}; background: {BG};
}}
/* Sem raio aqui de proposito: a marca cobre a linha inteira, e canto redondo por
   celula abre um entalhe entre uma celula e a outra. */
QTableWidget::item:selected {{ background: {SEL}; color: {TEXT}; }}

QTabWidget::pane {{ border: 0; border-top: 1px solid {BORDER}; }}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{
    background: transparent; color: {DIM}; padding: 8px 15px; margin-right: 2px;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:hover {{ color: {TEXT}; }}
/* aba desligada, como Preview quando a resposta nao tem o que mostrar, precisa parecer
   desligada. No cinza de antes ela era igual a uma aba comum e so nao respondia. */
QTabBar::tab:disabled {{ color: #454b58; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom-color: {ACCENT}; }}

/* a lateral tem quatro abas em pouco espaco, entao aperta o respiro horizontal */
QTabWidget#sideTabs > QTabBar::tab {{ padding: 8px 10px; margin-right: 0px; }}

/* A alca de um pixel era bonita e impossivel de pegar com o mouse. Agora ela tem
   sete pixels de area de pega e continua parecendo um risco fino, porque quem
   desenha e a classe Divisor: risco no meio e o resto na cor do fundo. */
QSplitter::handle {{ background: transparent; }}

QScrollBar:vertical {{ background: transparent; width: 11px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #2c313b; border-radius: 5px; min-height: 30px; margin: 2px; }}
QScrollBar::handle:vertical:hover {{ background: #3a4150; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; }}
QScrollBar::handle:horizontal {{ background: #2c313b; border-radius: 5px; min-width: 30px; margin: 2px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* Marcada, a caixa era um quadrado azul liso: sem visto dentro, nao le como caixa
   marcada, le como celula pintada. O visto e um png desenhado uma vez, porque folha de
   estilo do Qt nao desenha forma nenhuma. Mesma historia pro miolo do radio. */
QCheckBox::indicator {{
    width: 16px; height: 16px; border: 1px solid {BORDER}; border-radius: 5px;
    background: {PANEL2};
}}
QCheckBox::indicator:hover {{ border-color: {FAINT}; }}
QCheckBox::indicator:checked {{
    background: {ACCENT}; border-color: {ACCENT}; image: url(__VISTO__);
}}
QCheckBox::indicator:checked:hover {{ background: #66b1ff; border-color: #66b1ff; }}

QRadioButton::indicator {{
    width: 15px; height: 15px; border: 1px solid {BORDER}; border-radius: 8px;
    background: {PANEL2};
}}
QRadioButton::indicator:hover {{ border-color: {FAINT}; }}
/* Borda de cinco pixels aumenta a caixa e o raio de oito para de fechar o circulo:
   sai um quadrado de canto redondo. O miolo entao e desenhado, igual ao visto. */
QRadioButton::indicator:checked {{
    background: {PANEL2}; border-color: {ACCENT}; image: url(__PONTO__);
}}

QPushButton#salvar {{
    background: {PANEL2}; border: 1px solid {BORDER}; border-radius: 11px;
    padding: 0 16px; color: {TEXT}; font-weight: 600;
}}
QPushButton#salvar:hover {{ background: {RAISE}; border-color: {ACCENT}; }}
QPushButton#salvar:disabled {{ background: transparent; border-color: {BORDER}; color: {FAINT}; }}

QLabel#hint {{ color: {FAINT}; }}
QLabel#sectionTitle {{ color: {FAINT}; font-size: 8.5pt; letter-spacing: 1px; }}
QFrame#card {{ background: {PANEL}; border: 1px dashed {BORDER}; border-radius: 12px; }}
QToolTip {{ background: {PANEL2}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 7px; padding: 6px 8px; }}
"""


# --------------------------------------------------------------- a setinha


def _desenhar_chevron(destino: Path) -> bool:
    """Desenha a setinha do combo num png.

    O truque de CSS de fazer triangulo com tres bordas nao funciona em folha de estilo
    do Qt: em vez do triangulo sai um quadradinho, que era o simbolo estranho em cima
    do metodo. Entao a seta e desenhada de verdade, uma vez, e a folha aponta pro
    arquivo.
    """
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QPainter, QPen, QPixmap

    pix = QPixmap(12, 12)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    caneta = QPen(QColor(FAINT))
    caneta.setWidthF(1.6)
    caneta.setCapStyle(Qt.PenCapStyle.RoundCap)
    caneta.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(caneta)
    painter.drawPolyline([QPointF(3, 4.8), QPointF(6, 7.8), QPointF(9, 4.8)])
    painter.end()
    return pix.save(str(destino))


def _desenhar_visto(destino: Path) -> bool:
    """O visto que vai dentro da caixa marcada."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QPainter, QPen, QPixmap

    pix = QPixmap(16, 16)
    pix.setDevicePixelRatio(1.0)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    caneta = QPen(QColor("#0e1b2b"))
    caneta.setWidthF(2.1)
    caneta.setCapStyle(Qt.PenCapStyle.RoundCap)
    caneta.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(caneta)
    painter.drawPolyline([QPointF(4.0, 8.3), QPointF(6.9, 11.2), QPointF(12.0, 5.2)])
    painter.end()
    return pix.save(str(destino))


def _desenhar_ponto(destino: Path) -> bool:
    """O miolo do radio marcado."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QPainter, QPixmap

    pix = QPixmap(15, 15)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(ACCENT))
    painter.drawEllipse(QRectF(3.6, 3.6, 7.8, 7.8))
    painter.end()
    return pix.save(str(destino))


def folha() -> str:
    """A folha de estilo pronta pra uso, com o caminho da setinha ja resolvido.

    Precisa ser funcao e nao constante porque desenhar exige o QApplication de pe, e a
    constante nasce no import do modulo.
    """
    pasta = Path(tempfile.gettempdir())
    folha_pronta = QSS
    for marca, arquivo, desenho in (
        ("__CHEVRON__", "dbx-wire-chevron.png", _desenhar_chevron),
        ("__VISTO__", "dbx-wire-visto.png", _desenhar_visto),
        ("__PONTO__", "dbx-wire-ponto.png", _desenhar_ponto),
    ):
        destino = pasta / arquivo
        try:
            if not destino.exists():
                desenho(destino)
            if destino.exists():
                folha_pronta = folha_pronta.replace(marca, destino.as_posix())
                continue
        except Exception:  # noqa: BLE001
            pass
        # sem o arquivo, some com a regra e o Qt desenha do jeito padrao dele
        folha_pronta = folha_pronta.replace(f"image: url({marca});", "")
    return folha_pronta
