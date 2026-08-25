"""Conversores de e para os formatos das outras ferramentas.

Cada modulo aqui sabe fazer tres coisas com um formato: reconhecer, importar e exportar.
O `importer` escolhe qual usar olhando o arquivo, entao voce so aponta o que quer trazer
e nao precisa dizer de onde veio.

Modelo comum: a mesma arvore de dicionarios que o resto do app usa, com collection,
folder e request. Todo conversor entra e sai por ela, entao formato novo nao mexe em
mais nada.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Resultado:
    """O que um import trouxe, e o que ele nao conseguiu trazer."""

    collections: list = field(default_factory=list)
    environments: list = field(default_factory=list)
    globals: list = field(default_factory=list)
    formato: str = ""
    avisos: list = field(default_factory=list)
    erro: str | None = None

    def contar(self) -> dict:
        requests = 0
        pastas = 0

        def andar(items):
            nonlocal requests, pastas
            for node in items or []:
                if node.get("type") == "request":
                    requests += 1
                else:
                    pastas += 1
                    andar(node.get("items"))

        for colecao in self.collections:
            andar(colecao.get("items"))

        return {
            "collections": len(self.collections),
            "pastas": pastas,
            "requests": requests,
            "ambientes": len(self.environments),
        }

    def resumo(self) -> str:
        c = self.contar()
        partes = [f"{c['collections']} collections", f"{c['requests']} requests"]
        if c["pastas"]:
            partes.insert(1, f"{c['pastas']} pastas")
        if c["ambientes"]:
            partes.append(f"{c['ambientes']} ambientes")
        return ", ".join(partes)
