"""Roda os cinco testes em sequencia e devolve um resumo.

    python tests/rodar.py

Cada teste tambem roda sozinho, se voce quiser so um deles.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
SUITES = ("testa_nucleo.py", "testa_sftp.py", "testa_navegador_sftp.py", "testa_interface.py", "testa_uso.py")


def main() -> int:
    resultados = []
    for nome in SUITES:
        # cada suite num processo proprio: duas delas montam um QApplication, e o Qt nao
        # aceita dois no mesmo processo nem gosta de ser desmontado no meio
        saida = subprocess.run([sys.executable, str(AQUI / nome)], cwd=str(AQUI.parent))
        resultados.append((nome, saida.returncode))

    print("\n" + "=" * 66)
    for nome, codigo in resultados:
        print(f"  {'passou' if codigo == 0 else 'FALHOU'}  {nome}")
    ruins = [n for n, c in resultados if c != 0]
    print("=" * 66)
    print("tudo verde" if not ruins else f"{len(ruins)} suite(s) com falha")
    return 1 if ruins else 0


if __name__ == "__main__":
    sys.exit(main())
