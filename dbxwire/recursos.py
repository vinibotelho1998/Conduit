"""Onde estao os arquivos que acompanham o programa, rodando do codigo ou instalado.

Do repositorio, CHANGELOG.md e LICENSE ficam ao lado do pacote. Dentro do executavel
montado pelo PyInstaller nao existe "ao lado do pacote": o conteudo e descompactado numa
pasta temporaria cujo caminho vem em `sys._MEIPASS`, e `__file__` aponta pra dentro do
pacote empacotado. Por isso a janela de Novidades abria vazia no app instalado e cheia
rodando do fonte, que e o jeito mais facil de um defeito nunca aparecer em teste.
"""

from __future__ import annotations

import sys
from pathlib import Path


def raiz() -> Path:
    """Pasta onde procurar os arquivos avulsos do programa."""
    empacotado = getattr(sys, "_MEIPASS", None)
    if empacotado:
        return Path(empacotado)
    return Path(__file__).resolve().parent.parent


def arquivo(nome: str) -> Path | None:
    """Caminho do recurso, ou None quando ele nao foi junto no pacote."""
    alvo = raiz() / nome
    return alvo if alvo.exists() else None
