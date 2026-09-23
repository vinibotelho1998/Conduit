"""Escolhe o conversor certo e aplica o resultado no workspace.

A deteccao e por conteudo, e nao por extensao: `.json` serve pra Postman, Insomnia e
OpenAPI, e olhar so o nome do arquivo erraria na maioria das vezes. Cada conversor
devolve uma nota de confianca e o mais confiante ganha.
"""

from __future__ import annotations

from pathlib import Path

from . import curl_import
from .formats import Resultado, bruno, insomnia, openapi, postman

CONVERSORES = [
    ("Postman", postman),
    ("Insomnia", insomnia),
    ("Bruno", bruno),
    ("OpenAPI", openapi),
]

EXPORTADORES = {
    "postman": "Postman Collection v2.1, um arquivo .json",
    "insomnia": "Insomnia v4, um arquivo .json",
    "bruno": "Bruno, uma pasta com arquivos .bru",
    "openapi": "OpenAPI 3, um arquivo .json ou .yaml",
}


def detectar(caminho: str | Path) -> list[tuple[str, float]]:
    """Devolve os formatos possiveis, do mais provavel pro menos."""
    caminho = Path(caminho)
    notas = []
    for nome, modulo in CONVERSORES:
        try:
            nota = modulo.detectar(caminho)
        except Exception:  # noqa: BLE001
            nota = 0.0
        if nota > 0:
            notas.append((nome, nota))
    notas.sort(key=lambda par: -par[1])
    return notas


def _rodar(modulo, caminho: Path) -> Resultado:
    """Arquivo torto vira erro legivel na tela de importar.

    Cada conversor pega o erro que conhece, mas um recurso do Insomnia sem _id ou um
    arquivo que nao e UTF-8 escapavam como KeyError e UnicodeDecodeError, e a tela de
    importar caia no tratador de tombo em vez de dizer o que houve com o arquivo.
    """
    try:
        return modulo.importar(caminho)
    except Exception as exc:  # noqa: BLE001
        saida = Resultado()
        saida.erro = f"nao consegui ler o arquivo: {type(exc).__name__}: {exc}"
        return saida


def importar(caminho: str | Path, formato: str | None = None) -> Resultado:
    caminho = Path(caminho)
    if not caminho.exists():
        saida = Resultado()
        saida.erro = f"nao encontrei {caminho}"
        return saida

    if formato:
        modulo = dict(CONVERSORES).get(formato)
        if modulo is None:
            saida = Resultado()
            saida.erro = f"formato {formato} nao suportado"
            return saida
        return _rodar(modulo, caminho)

    possiveis = detectar(caminho)
    if not possiveis:
        saida = Resultado()
        saida.erro = (
            "nao reconheci o formato. Aceito Postman v2.1, Insomnia v4, Bruno e OpenAPI 3"
        )
        return saida

    nome = possiveis[0][0]
    resultado = _rodar(dict(CONVERSORES)[nome], caminho)
    if len(possiveis) > 1:
        outros = ", ".join(f"{n} {int(v * 100)}%" for n, v in possiveis[1:])
        resultado.avisos.append(f"o arquivo tambem parecia {outros}, escolhi {nome}")
    return resultado


def aplicar(tree: dict, resultado: Resultado, prefixo_nome: bool = False) -> dict:
    """Junta o que veio na arvore do workspace, sem apagar o que ja existia."""
    contagem = {"collections": 0, "ambientes": 0, "renomeados": 0}

    existentes = {c.get("name") for c in tree.get("collections") or []}
    for colecao in resultado.collections:
        nome = colecao.get("name") or "importada"
        if nome in existentes:
            base, conta = nome, 2
            while nome in existentes:
                nome = f"{base} {conta}"
                conta += 1
            colecao["name"] = nome
            contagem["renomeados"] += 1
        existentes.add(nome)
        tree.setdefault("collections", []).append(colecao)
        contagem["collections"] += 1

    nomes_env = {e.get("name") for e in tree.get("environments") or []}
    for env in resultado.environments:
        nome = env.get("name") or "ambiente"
        if nome in nomes_env:
            base, conta = nome, 2
            while nome in nomes_env:
                nome = f"{base} {conta}"
                conta += 1
            env["name"] = nome
            contagem["renomeados"] += 1
        nomes_env.add(nome)
        tree.setdefault("environments", []).append(env)
        contagem["ambientes"] += 1

    return contagem


def exportar(tree: dict, colecoes: list, formato: str, destino: str | Path, com_segredo: bool = False):
    destino = Path(destino)

    if formato == "postman":
        if len(colecoes) == 1:
            return postman.exportar_collection(colecoes[0], destino)
        destino.mkdir(parents=True, exist_ok=True)
        from .storage import slug

        # nomes que dao o mesmo slug, como "Pagamentos v1" e "Pagamentos (v1)", gravavam
        # no mesmo arquivo, e so a ultima collection sobrava na pasta exportada
        usados: set[str] = set()
        for colecao in colecoes:
            postman.exportar_collection(
                colecao,
                destino / f"{slug(colecao.get('name') or 'collection', usados)}.postman_collection.json",
            )
        usados = set()
        for env in tree.get("environments") or []:
            postman.exportar_environment(
                env,
                destino / f"{slug(env.get('name') or 'ambiente', usados)}.postman_environment.json",
                com_segredo,
            )
        return destino

    if formato == "insomnia":
        return insomnia.exportar(tree, colecoes, destino, com_segredo)

    if formato == "bruno":
        return bruno.exportar(tree, colecoes, destino, com_segredo)

    if formato == "openapi":
        return openapi.exportar(tree, colecoes, destino, com_segredo)

    raise ValueError(f"formato {formato} nao suportado")


def importar_curl(comando: str):
    return curl_import.importar(comando)
