"""Gerenciador de workspaces: renomear, cor, duplicar, abrir pasta e excluir."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..core import workspaces as ws
from . import theme
from .request_editor import mono


def bolinha(cor: str) -> QPixmap:
    pix = QPixmap(28, 14)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(cor))
    painter.drawEllipse(9, 3, 9, 9)
    painter.end()
    return pix


class WorkspacesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Workspaces")
        self.resize(820, 520)

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(16, 14, 16, 14)
        raiz.setSpacing(10)

        texto = QLabel(
            "Cada workspace e uma pasta isolada, com collections, ambientes, cofre e "
            "historico proprios. Nada vaza de um pro outro."
        )
        texto.setObjectName("hint")
        texto.setWordWrap(True)
        raiz.addWidget(texto)

        self.tabela = QTableWidget(0, 5)
        self.tabela.setHorizontalHeaderLabels(["", "Nome", "Conteudo", "Pasta", "Ativo"])
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.setShowGrid(False)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabela.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabela.setWordWrap(False)
        cabecalho = self.tabela.horizontalHeader()
        cabecalho.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        cabecalho.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tabela.setColumnWidth(0, 34)
        self.tabela.setColumnWidth(1, 200)
        self.tabela.setColumnWidth(3, 190)
        self.tabela.setColumnWidth(4, 70)
        self.tabela.itemDoubleClicked.connect(lambda *_: self.renomear())
        raiz.addWidget(self.tabela, 1)

        barra = QHBoxLayout()
        barra.setSpacing(6)
        for rotulo, alvo in (
            ("Renomear", self.renomear),
            ("Trocar cor", self.trocar_cor),
            ("Duplicar", self.duplicar),
            ("Abrir pasta", self.abrir_pasta),
            ("Usar este", self.usar),
        ):
            botao = QPushButton(rotulo)
            botao.clicked.connect(alvo)
            barra.addWidget(botao)
        barra.addStretch(1)

        self.btn_excluir = QPushButton("Excluir")
        self.btn_excluir.setStyleSheet(f"QPushButton {{ color: {theme.ERR}; }}")
        self.btn_excluir.clicked.connect(self.excluir)
        barra.addWidget(self.btn_excluir)
        raiz.addLayout(barra)

        self.resumo = QLabel("")
        self.resumo.setObjectName("hint")
        raiz.addWidget(self.resumo)

        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        botoes.rejected.connect(self.reject)
        botoes.accepted.connect(self.accept)
        raiz.addWidget(botoes)

        self.recarregar()

    # ------------------------------------------------------------------ dados

    def recarregar(self, selecionar: str | None = None) -> None:
        registro = ws.list_workspaces()
        self.entradas = registro["workspaces"]
        ativo = registro.get("active")

        self.tabela.setRowCount(len(self.entradas))
        for indice, entrada in enumerate(self.entradas):
            cor = QTableWidgetItem()
            cor.setData(Qt.ItemDataRole.DecorationRole, bolinha(entrada.get("color") or theme.DIM))
            self.tabela.setItem(indice, 0, cor)

            nome = QTableWidgetItem(entrada.get("name") or entrada["id"])
            nome.setData(Qt.ItemDataRole.UserRole, entrada["id"])
            self.tabela.setItem(indice, 1, nome)

            self.tabela.setItem(indice, 2, QTableWidgetItem(self._contar(entrada)))

            # so o nome da pasta na tela. O caminho inteiro nao cabe e nao ajuda,
            # entao vai pra dica e tem o botao Abrir pasta ao lado
            caminho = Path(entrada.get("path") or "")
            pasta = QTableWidgetItem(caminho.name)
            pasta.setFont(mono(8))
            pasta.setForeground(QColor(theme.FAINT))
            pasta.setToolTip(str(caminho))
            self.tabela.setItem(indice, 3, pasta)

            marca = QTableWidgetItem("sim" if entrada["id"] == ativo else "")
            marca.setForeground(QColor(theme.OK))
            self.tabela.setItem(indice, 4, marca)
            self.tabela.setRowHeight(indice, 26)

        alvo = selecionar or ativo
        for indice, entrada in enumerate(self.entradas):
            if entrada["id"] == alvo:
                self.tabela.selectRow(indice)
                break

        self.resumo.setText(f"{len(self.entradas)} workspaces em {ws.WORKSPACES_DIR}")
        self.btn_excluir.setEnabled(len(self.entradas) > 1)

    @staticmethod
    def _contar(entrada: dict) -> str:
        raiz = Path(entrada.get("path") or "")
        colecoes = raiz / "collections"
        if not colecoes.exists():
            return "vazio"
        requests = len([p for p in colecoes.rglob("*.yaml") if not p.name.startswith("_")])
        pastas = len([p for p in colecoes.rglob("_folder.yaml")])
        cols = len([p for p in colecoes.glob("*/_collection.yaml")])
        segredos = 0
        cofre = raiz / ".secrets" / "vault.dbx"
        if cofre.exists():
            segredos = 1
        partes = [f"{cols} collections", f"{requests} requests"]
        if pastas:
            partes.insert(1, f"{pastas} pastas")
        if segredos:
            partes.append("cofre")
        return ", ".join(partes)

    def selecionado(self) -> dict | None:
        linhas = self.tabela.selectionModel().selectedRows()
        if not linhas:
            return None
        item = self.tabela.item(linhas[0].row(), 1)
        wid = item.data(Qt.ItemDataRole.UserRole)
        return next((e for e in self.entradas if e["id"] == wid), None)

    # ---------------------------------------------------------------- acoes

    def renomear(self) -> None:
        entrada = self.selecionado()
        if not entrada:
            return
        nome, ok = QInputDialog.getText(
            self, "Renomear workspace", "Nome", text=entrada.get("name") or ""
        )
        if ok and nome.strip():
            ws.rename_workspace(entrada["id"], nome.strip())
            self.recarregar(entrada["id"])

    def trocar_cor(self) -> None:
        entrada = self.selecionado()
        if not entrada:
            return
        nomes = ["azul", "verde", "laranja", "roxo", "vermelho", "turquesa"]
        atual = ws.COLORS.index(entrada["color"]) if entrada.get("color") in ws.COLORS else 0
        escolha, ok = QInputDialog.getItem(self, "Cor do workspace", "Cor", nomes, atual, False)
        if ok:
            ws.set_color(entrada["id"], ws.COLORS[nomes.index(escolha)])
            self.recarregar(entrada["id"])

    def duplicar(self) -> None:
        entrada = self.selecionado()
        if not entrada:
            return
        nome, ok = QInputDialog.getText(
            self, "Duplicar workspace", "Nome da copia", text=f"{entrada.get('name')} copia"
        )
        if not ok or not nome.strip():
            return
        try:
            novo = ws.duplicate_workspace(entrada["id"], nome.strip())
        except ValueError as exc:
            QMessageBox.warning(self, "Duplicar", str(exc))
            return
        QMessageBox.information(
            self,
            "Duplicado",
            "A copia levou collections, pastas, ambientes e globais.\n\n"
            "O cofre e o historico ficaram no original de proposito: segredo nao se "
            "duplica sem alguem pedir, e historico e do workspace que executou.",
        )
        self.recarregar(novo["id"])

    def abrir_pasta(self) -> None:
        entrada = self.selecionado()
        if entrada and os.name == "nt":
            os.startfile(entrada["path"])  # noqa: S606

    def usar(self) -> None:
        entrada = self.selecionado()
        if not entrada:
            return
        ws.set_active(entrada["id"])
        janela = self.parent()
        if janela is not None and hasattr(janela, "load_workspace"):
            janela.load_workspace(entrada["id"])
        self.recarregar(entrada["id"])

    def excluir(self) -> None:
        entrada = self.selecionado()
        if not entrada:
            return
        if len(self.entradas) <= 1:
            QMessageBox.information(self, "Excluir", "Nao da pra excluir o unico workspace.")
            return

        caixa = QMessageBox(self)
        caixa.setWindowTitle("Excluir workspace")
        caixa.setIcon(QMessageBox.Icon.Warning)
        caixa.setText(f"Excluir o workspace {entrada.get('name')}?")
        caixa.setInformativeText(
            f"{self._contar(entrada)}\n\n"
            "Tirar da lista deixa a pasta intacta no disco, da pra voltar depois.\n"
            "Mover pra lixeira tira a pasta do lugar, mas nao apaga: ela vai pra "
            "lixeira do DBX Wire e pode ser recuperada na mao."
        )
        so_lista = caixa.addButton("Tirar da lista", QMessageBox.ButtonRole.AcceptRole)
        com_arquivos = caixa.addButton("Mover pra lixeira", QMessageBox.ButtonRole.DestructiveRole)
        caixa.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        caixa.exec()

        clicado = caixa.clickedButton()
        if clicado not in (so_lista, com_arquivos):
            return

        resultado = ws.delete_workspace(entrada["id"], apagar_arquivos=clicado is com_arquivos)
        if resultado["lixeira"]:
            QMessageBox.information(
                self, "Excluido", f"A pasta foi movida para\n{resultado['lixeira']}"
            )
        self.recarregar()
