"""Editor de ambiente na area principal, do jeito que o Postman faz.

Abre como aba, do lado das abas de request, entao da pra ficar com o ambiente aberto
enquanto mexe nos requests, sem janela modal no caminho.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import theme, tokens
from .kvtable import KvTable
from .widgets import Faixa, conta


class EnvEditor(QWidget):
    changed = Signal()
    ativar_pedido = Signal(str)

    def __init__(self, env: dict, e_global: bool = False, parent=None):
        super().__init__(parent)
        self.env = env
        self.e_global = e_global

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(12, 10, 12, 10)
        raiz.setSpacing(10)

        cabeca = QHBoxLayout()
        cabeca.setSpacing(10)

        self.titulo = QLabel()
        self.titulo.setStyleSheet("font-size: 12pt; font-weight: 700;")
        cabeca.addWidget(self.titulo)

        self.marca = QLabel("")
        cabeca.addWidget(self.marca)
        cabeca.addStretch(1)

        self.btn_ativar = QPushButton("Usar este ambiente")
        self.btn_ativar.clicked.connect(lambda: self.ativar_pedido.emit(self.env.get("id")))
        self.btn_ativar.setVisible(not e_global)
        cabeca.addWidget(self.btn_ativar)
        raiz.addLayout(cabeca)

        explicacao = QLabel(
            "Valem para todas as collections deste workspace, e perdem para collection, "
            "pasta e ambiente."
            if e_global
            else "Marque Secreto no que nao pode aparecer em historico, log nem em codigo "
            "gerado. O valor fica na sua maquina e nunca vai pro git."
        )
        explicacao.setObjectName("hint")
        explicacao.setWordWrap(True)
        raiz.addWidget(explicacao)

        linha = QFrame()
        linha.setFixedHeight(1)
        theme.estilizar(linha, lambda: f"background: {theme.BORDER};")
        raiz.addWidget(linha)

        env.setdefault("values", [])
        self.tabela = KvTable(env["values"], ("Nome", "Valor"), with_secret=True)
        self.tabela.changed.connect(self._mudou)
        self.tabela.linha_removida.connect(self._oferecer_desfazer)
        raiz.addWidget(self.tabela, 1)

        # Aqui o X nao e rascunho: o salvamento automatico grava em meio segundo, e um
        # clique errado no X, colado na caixa Secreto, levava um token sem volta.
        self.desfazer = Faixa()
        self.desfazer.acao.connect(self._desfazer_remocao)
        raiz.addWidget(self.desfazer)
        self._removida: tuple | None = None
        self._timer_desfazer = QTimer(self)
        self._timer_desfazer.setSingleShot(True)
        self._timer_desfazer.setInterval(10000)
        self._timer_desfazer.timeout.connect(self._esquecer_remocao)

        self.resumo = QLabel("")
        self.resumo.setObjectName("hint")
        raiz.addWidget(self.resumo)

        self.atualizar()

    def focar(self, nome: str) -> bool:
        return self.tabela.focar(nome)


    def _mudou(self) -> None:
        self.atualizar()
        self.changed.emit()

    def _oferecer_desfazer(self, linha: dict, posicao: int) -> None:
        nome = (linha or {}).get("key") or ""
        if not nome:
            return
        self._removida = (linha, posicao)
        self.desfazer.mostrar(f"variavel {nome} apagada", "aviso", "desfazer")
        self._timer_desfazer.start()

    def _desfazer_remocao(self) -> None:
        """Volta a linha pro mesmo lugar. O valor, secreto ou nao, ainda estava na memoria,
        e volta pro cofre no proximo salvar."""
        if self._removida is None:
            return
        linha, posicao = self._removida
        valores = self.tabela.rows
        valores.insert(min(posicao, len(valores)), linha)
        self._esquecer_remocao()
        self.tabela.reload()
        self._mudou()

    def _esquecer_remocao(self) -> None:
        self._removida = None
        self._timer_desfazer.stop()
        self.desfazer.esconder()

    def atualizar(self, ativo: bool | None = None) -> None:
        nome = "Globais do workspace" if self.e_global else (self.env.get("name") or "sem nome")
        self.titulo.setText(nome)

        if ativo is None:
            ativo = getattr(self, "_ativo", False)
        self._ativo = ativo

        if self.e_global:
            self.marca.setText("")
        elif ativo:
            self.marca.setText("ativo")
            theme.estilizar(
                self.marca,
                lambda: f"color: {theme.OK}; background: {tokens.alfa(theme.OK, 0.15)};"
                f" border-radius: 8px; padding: 1px 9px; font-size: 8pt; font-weight: 600;",
            )
            self.btn_ativar.setEnabled(False)
            self.btn_ativar.setText("Este e o ativo")
        else:
            self.marca.setText("")
            self.btn_ativar.setEnabled(True)
            self.btn_ativar.setText("Usar este ambiente")

        valores = self.env.get("values") or []
        preenchidas = len([v for v in valores if v.get("key")])
        secretas = len([v for v in valores if v.get("secret") and v.get("key")])
        vazias = len([v for v in valores if v.get("key") and not v.get("value")])

        partes = [conta(preenchidas, "variavel", "variaveis")]
        if secretas:
            partes.append(conta(secretas, "secreta", "secretas"))
        if vazias:
            partes.append(f"{vazias} sem valor")
        self.resumo.setText("   |   ".join(partes))
