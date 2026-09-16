"""Encanamento comum dos testes: caminho do pacote, contagem e ambiente isolado.

Sem framework de proposito. O que estes testes precisam e subir a janela de verdade,
abrir uma conexao de verdade e conferir o resultado; nada disso fica mais facil com
pytest, e uma dependencia a menos e uma dependencia a menos pra manter na maquina de
quem so quer compilar o instalador.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
if str(RAIZ / "tests") not in sys.path:
    sys.path.insert(0, str(RAIZ / "tests"))


class Placar:
    """Conta o que passou e o que nao passou, e imprime enquanto roda."""

    def __init__(self, titulo: str):
        self.titulo = titulo
        self.falhas: list[str] = []
        self.total = 0
        print(f"\n{'=' * 66}\n{titulo}\n{'=' * 66}")

    def secao(self, nome: str) -> None:
        print(f"\n-- {nome}")

    def confere(self, rotulo: str, condicao, detalhe: str = "") -> bool:
        self.total += 1
        ok = bool(condicao)
        marca = "  ok  " if ok else "  FALHA"
        print(f"{marca}  {rotulo}" + (f"   {detalhe}" if detalhe else ""))
        if not ok:
            self.falhas.append(rotulo)
        return ok

    def fechar(self) -> int:
        print()
        if self.falhas:
            print(f"{len(self.falhas)} de {self.total} falharam: {', '.join(self.falhas)}")
            return 1
        print(f"{self.total} de {self.total} passaram")
        return 0


def casa_limpa(nome: str) -> Path:
    """Pasta de dados so deste teste. Nunca encosta no Conduit de verdade."""
    destino = Path(tempfile.gettempdir()) / f"conduit-teste-{nome}"
    shutil.rmtree(destino, ignore_errors=True)
    os.environ["CONDUIT_HOME"] = str(destino)
    return destino


def sem_tela() -> None:
    """Qt desenhando na memoria, pra rodar no CI sem area de trabalho."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def girar(app, voltas: int = 60, pausa: float = 0.03) -> None:
    """Deixa a thread da interface respirar ate a tarefa de rede voltar."""
    import time

    for _ in range(voltas):
        app.processEvents()
        time.sleep(pausa)
