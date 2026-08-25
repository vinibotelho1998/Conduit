"""Paleta de comandos e busca rapida, no estilo Ctrl+P de editor de codigo."""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from . import theme
from .request_editor import mono


@dataclass
class PaletteItem:
    label: str
    sub: str = ""
    badge: str = ""
    badge_color: str = ""
    action: object = None
    hint: str = ""
    payload: object = None
    score: int = field(default=0, compare=False)


def fuzzy(consulta: str, texto: str) -> int | None:
    """Pontuacao simples de subsequencia. Devolve None quando nao casa.

    Casamento no comeco de palavra vale mais, e caracteres seguidos valem mais ainda.
    E o suficiente pra uma lista de algumas centenas de requests e nao precisa de lib.
    """
    if not consulta:
        return 0
    alvo = texto.lower()
    busca = consulta.lower()

    pontos = 0
    posicao = 0
    anterior = -2
    for letra in busca:
        achou = alvo.find(letra, posicao)
        if achou < 0:
            return None
        if achou == anterior + 1:
            pontos += 6
        if achou == 0 or alvo[achou - 1] in " /-_.":
            pontos += 8
        pontos += max(0, 4 - (achou - posicao))
        anterior = achou
        posicao = achou + 1
    pontos += max(0, 20 - len(alvo) // 4)

    # Substring inteira vale muito mais que subsequencia espalhada, senao buscar
    # "banco" traz "Basic auth" quase no mesmo nivel de "Banco por codigo".
    if busca in alvo:
        pontos += 120
        if alvo.startswith(busca):
            pontos += 60
    return pontos


class Palette(QDialog):
    def __init__(self, itens: list[PaletteItem], titulo: str, parent=None):
        super().__init__(parent)
        self.itens = itens
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        self.resize(720, 460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        self.setStyleSheet(
            f"QDialog {{ background: {theme.PANEL2}; border: 1px solid {theme.ACCENT}; border-radius: 10px; }}"
        )

        self.busca = QLineEdit()
        self.busca.setPlaceholderText(titulo)
        self.busca.setStyleSheet(
            f"QLineEdit {{ border: 0; border-bottom: 1px solid {theme.BORDER}; border-radius: 0;"
            f" padding: 12px 14px; font-size: 11pt; background: transparent; }}"
        )
        self.busca.textChanged.connect(self._filtrar)
        self.busca.returnPressed.connect(self._aceitar)
        layout.addWidget(self.busca)

        self.lista = QListWidget()
        self.lista.setStyleSheet(
            f"QListWidget {{ border: 0; background: transparent; padding: 6px; }}"
            f"QListWidget::item {{ padding: 6px 10px; border-radius: 6px; }}"
            f"QListWidget::item:selected {{ background: {theme.RAISE}; }}"
        )
        self.lista.itemActivated.connect(lambda _: self._aceitar())
        self.lista.itemDoubleClicked.connect(lambda _: self._aceitar())
        layout.addWidget(self.lista, 1)

        self.rodape = QLabel("  Enter abre   ·   Esc fecha   ·   setas navegam")
        self.rodape.setObjectName("hint")
        self.rodape.setStyleSheet(f"color: {theme.FAINT}; border-top: 1px solid {theme.BORDER}; padding: 6px 12px;")
        layout.addWidget(self.rodape)

        self.escolhido: PaletteItem | None = None
        self._filtrar("")

    # ----------------------------------------------------------------- lista

    def _filtrar(self, consulta: str) -> None:
        pontuados = []
        for item in self.itens:
            alvo = f"{item.label} {item.sub} {item.badge}"
            nota = fuzzy(consulta, alvo)
            if nota is not None:
                item.score = nota
                pontuados.append(item)
        pontuados.sort(key=lambda i: -i.score)

        self.lista.clear()
        for item in pontuados[:200]:
            linha = QListWidgetItem()
            texto = item.label
            if item.badge:
                texto = f"{item.badge:<7}{texto}"
            if item.sub:
                texto = f"{texto}\n{item.sub}"
            linha.setText(texto)
            linha.setData(Qt.ItemDataRole.UserRole, item)
            if item.badge_color:
                linha.setForeground(QColor(theme.TEXT))
            if item.hint:
                linha.setToolTip(item.hint)
            linha.setFont(mono(8) if item.badge else linha.font())
            self.lista.addItem(linha)

        if self.lista.count():
            self.lista.setCurrentRow(0)
        self.rodape.setText(f"  {self.lista.count()} de {len(self.itens)}   ·   Enter abre   ·   Esc fecha")

    def _aceitar(self) -> None:
        atual = self.lista.currentItem()
        if atual is None:
            return
        self.escolhido = atual.data(Qt.ItemDataRole.UserRole)
        self.accept()

    # ---------------------------------------------------------------- teclas

    def keyPressEvent(self, event):  # noqa: N802
        tecla = event.key()
        if tecla == Qt.Key.Key_Escape:
            self.reject()
            return
        if tecla in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            linha = self.lista.currentRow()
            total = self.lista.count()
            if total:
                passo = 1 if tecla == Qt.Key.Key_Down else -1
                self.lista.setCurrentRow((linha + passo) % total)
            return
        if tecla in (Qt.Key.Key_PageDown, Qt.Key.Key_PageUp):
            linha = self.lista.currentRow()
            passo = 8 if tecla == Qt.Key.Key_PageDown else -8
            self.lista.setCurrentRow(max(0, min(self.lista.count() - 1, linha + passo)))
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------- utilidade

    @staticmethod
    def escolher(itens: list[PaletteItem], titulo: str, parent=None) -> PaletteItem | None:
        dialogo = Palette(itens, titulo, parent)
        if parent is not None:
            geo = parent.geometry()
            dialogo.move(
                geo.center().x() - dialogo.width() // 2,
                geo.top() + max(60, geo.height() // 8),
            )
        if dialogo.exec() == QDialog.DialogCode.Accepted:
            return dialogo.escolhido
        return None
