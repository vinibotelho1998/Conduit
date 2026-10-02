"""Confere isolamento e comportamento do runner com processos de verdade."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

from comum import Placar, casa_limpa
import rodar


def main() -> int:
    p = Placar("Infraestrutura dos testes")
    anterior = os.environ.get("CONDUIT_HOME")
    try:
        primeira = casa_limpa("isolamento")
        (primeira / "marca.txt").write_text("preservar", encoding="utf-8")
        segunda = casa_limpa("isolamento")
        p.confere("execucoes com o mesmo nome tem pastas distintas", primeira != segunda)
        p.confere("nova execucao preserva a pasta da anterior", (primeira / "marca.txt").read_text() == "preservar")
        p.confere("ambiente aponta para o workspace isolado", os.environ["CONDUIT_HOME"] == str(segunda))
    finally:
        if anterior is None:
            os.environ.pop("CONDUIT_HOME", None)
        else:
            os.environ["CONDUIT_HOME"] = anterior

    with tempfile.TemporaryDirectory(prefix="conduit-runner-") as pasta:
        script = Path(pasta) / "suite.py"
        script.write_text("raise SystemExit(0)\n", encoding="utf-8")
        p.confere("processo que passa retorna zero", rodar.executar(script, 10) == 0)
        script.write_text("raise SystemExit(7)\n", encoding="utf-8")
        p.confere("falha preserva codigo do processo", rodar.executar(script, 10) == 7)
        script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
        inicio = time.monotonic()
        p.confere("processo travado retorna falha por tempo", rodar.executar(script, 0.5) == 124)
        p.confere("limite encerra o processo sem esperar os 30 segundos", time.monotonic() - inicio < 10)

    for valor in ("0", "-1", "nan", "inf", "texto"):
        try:
            rodar._limite(valor)
        except argparse.ArgumentTypeError:
            p.confere(f"limite invalido rejeitado: {valor}", True)
        else:
            p.confere(f"limite invalido rejeitado: {valor}", False)
    return p.fechar()


if __name__ == "__main__":
    sys.exit(main())
