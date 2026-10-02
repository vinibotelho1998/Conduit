"""Executa suites isoladas, com progresso imediato e limite de tempo por processo.

    python tests/rodar.py
    python tests/rodar.py nucleo interface --timeout 300
"""

from __future__ import annotations

import argparse
import math
import os
import subprocess
import sys
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
SUITES = {
    "infra": "testa_infra.py",
    "nucleo": "testa_nucleo.py",
    "refinamento": "testa_refinamento_core.py",
    "sftp": "testa_sftp.py",
    "navegador": "testa_navegador_sftp.py",
    "interface": "testa_interface.py",
    "uso": "testa_uso.py",
}


def _limite(valor: str) -> float:
    try:
        numero = float(valor)
    except ValueError as erro:
        raise argparse.ArgumentTypeError("informe os segundos do limite") from erro
    if not math.isfinite(numero) or numero <= 0:
        raise argparse.ArgumentTypeError("o limite precisa ser maior que zero e finito")
    return numero


def executar(arquivo: Path, limite: float) -> int:
    """Mantem a saida da suite visivel e transforma um travamento em falha."""
    ambiente = os.environ.copy()
    ambiente["PYTHONIOENCODING"] = "utf-8"
    try:
        resultado = subprocess.run(
            [sys.executable, "-u", str(arquivo)], cwd=str(AQUI.parent),
            env=ambiente, timeout=limite,
        )
        return resultado.returncode
    except subprocess.TimeoutExpired:
        print(f"\nTEMPO ESGOTADO: {arquivo.name} excedeu {limite:g} s", flush=True)
        return 124
    except OSError as erro:
        print(f"\nFALHA ao iniciar {arquivo.name}: {erro}", flush=True)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suites", nargs="*", metavar="SUITE",
                        help="suites para executar: " + ", ".join(SUITES))
    parser.add_argument("--timeout", type=_limite, default=300.0,
                        help="limite em segundos por suite (padrao: 300)")
    parser.add_argument("--list", action="store_true", help="lista as suites e sai")
    args = parser.parse_args(argv)
    if args.list:
        for nome, arquivo in SUITES.items():
            print(f"{nome:<12} {arquivo}")
        return 0
    desconhecidas = [nome for nome in args.suites if nome not in SUITES]
    if desconhecidas:
        parser.error("suite desconhecida: " + ", ".join(desconhecidas))

    resultados = []
    try:
        for nome in dict.fromkeys(args.suites or SUITES):
            arquivo = SUITES[nome]
            print(f"\n>>> {arquivo} (limite {args.timeout:g} s)", flush=True)
            inicio = time.monotonic()
            codigo = executar(AQUI / arquivo, args.timeout)
            resultados.append((arquivo, codigo, time.monotonic() - inicio))
    except KeyboardInterrupt:
        print("\nTestes interrompidos.", flush=True)
        return 130

    print("\n" + "=" * 66)
    for arquivo, codigo, duracao in resultados:
        print(f"  {'passou' if codigo == 0 else 'FALHOU'}  {arquivo}  ({duracao:.1f} s)")
    ruins = [nome for nome, codigo, _ in resultados if codigo != 0]
    print("=" * 66)
    print("tudo verde" if not ruins else f"{len(ruins)} suite(s) com falha")
    return 1 if ruins else 0


if __name__ == "__main__":
    sys.exit(main())
