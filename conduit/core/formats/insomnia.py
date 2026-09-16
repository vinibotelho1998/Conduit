"""Insomnia, formato de exportacao v4.

O Insomnia grava uma lista plana de recursos e amarra a hierarquia pelo `parentId`.
Entao importar e remontar a arvore a partir dos pais, e exportar e achatar de volta.

A sintaxe de variavel do Insomnia e `{{ nome }}`, com espaco, e a nossa aceita os dois,
entao nada precisa ser reescrito.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from ..workspaces import new_id
from . import Resultado


def detectar(caminho: Path) -> float:
    if caminho.is_dir() or caminho.suffix.lower() not in (".json", ".yaml", ".yml"):
        return 0.0
    try:
        texto = caminho.read_text(encoding="utf-8")
    except OSError:
        return 0.0
    if "__export_format" not in texto:
        return 0.0
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError:
        try:
            import yaml

            dados = yaml.safe_load(texto)
        except Exception:  # noqa: BLE001
            return 0.0
    if isinstance(dados, dict) and dados.get("_type") == "export":
        return 1.0
    return 0.6 if isinstance(dados, dict) and "resources" in dados else 0.0


def _carregar(caminho: Path):
    texto = Path(caminho).read_text(encoding="utf-8")
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        import yaml

        return yaml.safe_load(texto)


def _corpo_de(bruto, avisos: list) -> dict:
    if not isinstance(bruto, dict) or not bruto:
        return {"mode": "none", "raw": ""}

    tipo = (bruto.get("mimeType") or "").lower()
    texto = bruto.get("text") or ""

    if bruto.get("params") and "urlencoded" in tipo:
        from urllib.parse import urlencode

        pares = [
            (p.get("name") or "", p.get("value") or "")
            for p in bruto["params"]
            if not p.get("disabled")
        ]
        return {"mode": "form", "raw": urlencode(pares)}

    if "graphql" in tipo:
        avisos.append("corpo GraphQL veio como texto, o Conduit ainda nao tem aba propria")
        return {"mode": "raw", "raw": texto}

    if not texto:
        return {"mode": "none", "raw": ""}
    eh_json = "json" in tipo or texto.lstrip().startswith(("{", "["))
    return {"mode": "json" if eh_json else "raw", "raw": texto}


def _auth_de(bruto) -> dict | None:
    if not isinstance(bruto, dict) or not bruto:
        return None
    tipo = bruto.get("type")
    if bruto.get("disabled"):
        return {"type": "none"}
    if tipo == "bearer":
        return {"type": "bearer", "token": bruto.get("token") or ""}
    if tipo == "basic":
        return {
            "type": "basic",
            "username": bruto.get("username") or "",
            "password": bruto.get("password") or "",
        }
    if tipo == "apikey":
        return {
            "type": "apikey",
            "key": bruto.get("key") or "",
            "value": bruto.get("value") or "",
            "in": bruto.get("addTo") or "header",
        }
    if tipo == "oauth2":
        return {
            "type": "oauth2",
            "tokenUrl": bruto.get("accessTokenUrl") or "",
            "clientId": bruto.get("clientId") or "",
            "clientSecret": bruto.get("clientSecret") or "",
            "scope": bruto.get("scope") or "",
        }
    return None


def importar(caminho: Path) -> Resultado:
    resultado = Resultado(formato="Insomnia")
    try:
        dados = _carregar(caminho)
    except Exception as exc:  # noqa: BLE001
        resultado.erro = f"nao consegui ler o arquivo: {exc}"
        return resultado

    recursos = dados.get("resources") or []
    por_id: dict[str, dict] = {}
    filhos: dict[str, list] = {}

    for recurso in recursos:
        tipo = recurso.get("_type")
        pai = recurso.get("parentId")

        if tipo in ("workspace", "request_group"):
            node = {
                "id": new_id("fld"),
                "type": "folder",
                "name": recurso.get("name") or "sem nome",
                "expanded": False,
                "variables": [],
                "items": [],
                "origin": {"insomnia": recurso.get("_id")},
            }
            auth = _auth_de(recurso.get("authentication"))
            if auth:
                node["auth"] = auth
            por_id[recurso["_id"]] = node
            filhos.setdefault(pai, []).append(recurso["_id"])

        elif tipo == "request":
            url = recurso.get("url") or ""
            node = {
                "id": new_id("req"),
                "type": "request",
                "name": recurso.get("name") or "sem nome",
                "method": (recurso.get("method") or "GET").upper(),
                "url": url.split("?")[0],
                "params": [
                    {
                        "key": p.get("name") or "",
                        "value": p.get("value") or "",
                        "enabled": not p.get("disabled"),
                    }
                    for p in recurso.get("parameters") or []
                    if p.get("name")
                ],
                "headers": [
                    {
                        "key": h.get("name") or "",
                        "value": h.get("value") or "",
                        "enabled": not h.get("disabled"),
                    }
                    for h in recurso.get("headers") or []
                    if h.get("name")
                ],
                "body": _corpo_de(recurso.get("body"), resultado.avisos),
                "docs": recurso.get("description") or "",
                "origin": {"insomnia": recurso.get("_id")},
            }
            if "?" in url:
                from urllib.parse import parse_qsl

                for chave, valor in parse_qsl(url.split("?", 1)[1], keep_blank_values=True):
                    node["params"].append({"key": chave, "value": valor, "enabled": True})
            auth = _auth_de(recurso.get("authentication"))
            if auth:
                node["auth"] = auth
            por_id[recurso["_id"]] = node
            filhos.setdefault(pai, []).append(recurso["_id"])

        elif tipo == "environment":
            valores = recurso.get("data") or {}
            if not isinstance(valores, dict):
                continue
            resultado.environments.append(
                {
                    "id": new_id("env"),
                    "name": recurso.get("name") or "ambiente",
                    "values": [
                        {"key": chave, "value": str(valor), "enabled": True}
                        for chave, valor in valores.items()
                    ],
                }
            )

    def montar(identificador: str) -> None:
        node = por_id.get(identificador)
        if node is None:
            return
        for filho_id in filhos.get(identificador, []):
            filho = por_id.get(filho_id)
            if filho is None:
                continue
            montar(filho_id)
            node.setdefault("items", []).append(filho)

    raizes = [
        recurso["_id"]
        for recurso in recursos
        if recurso.get("_type") == "workspace"
    ]
    if not raizes:
        raizes = [
            identificador
            for identificador in por_id
            if identificador not in {f for lista in filhos.values() for f in lista}
        ]

    for raiz in raizes:
        montar(raiz)
        node = por_id.get(raiz)
        if node:
            node["type"] = "collection"
            resultado.collections.append(node)

    resultado.avisos = sorted(set(resultado.avisos))
    return resultado


def _auth_para(config: dict | None) -> dict:
    if not config or config.get("type") in (None, "none", "inherit"):
        return {}
    tipo = config["type"]
    if tipo == "bearer":
        return {"type": "bearer", "token": config.get("token", "")}
    if tipo == "basic":
        return {
            "type": "basic",
            "username": config.get("username", ""),
            "password": config.get("password", ""),
        }
    if tipo == "apikey":
        return {
            "type": "apikey",
            "key": config.get("key", ""),
            "value": config.get("value", ""),
            "addTo": config.get("in", "header"),
        }
    if tipo == "oauth2":
        return {
            "type": "oauth2",
            "grantType": "client_credentials",
            "accessTokenUrl": config.get("tokenUrl", ""),
            "clientId": config.get("clientId", ""),
            "clientSecret": config.get("clientSecret", ""),
            "scope": config.get("scope", ""),
        }
    return {}


def exportar(tree: dict, colecoes: list, destino: Path, com_segredo: bool = False) -> Path:
    agora = int(time.time() * 1000)
    recursos = []
    contador = {"n": 0}

    def identificador(prefixo: str) -> str:
        contador["n"] += 1
        return f"{prefixo}_conduit{contador['n']:04d}"

    def andar(node: dict, pai: str) -> None:
        if node.get("type") == "request":
            corpo = node.get("body") or {}
            recurso = {
                "_id": identificador("req"),
                "_type": "request",
                "parentId": pai,
                "name": node.get("name") or "",
                "method": node.get("method") or "GET",
                "url": node.get("url") or "",
                "description": node.get("docs") or "",
                "headers": [
                    {"name": h.get("key"), "value": h.get("value"), "disabled": h.get("enabled") is False}
                    for h in node.get("headers") or []
                    if h.get("key")
                ],
                "parameters": [
                    {"name": p.get("key"), "value": p.get("value"), "disabled": p.get("enabled") is False}
                    for p in node.get("params") or []
                    if p.get("key")
                ],
                "authentication": _auth_para(node.get("auth")),
                "body": {},
                "created": agora,
                "modified": agora,
            }
            if corpo.get("mode") == "form":
                from urllib.parse import parse_qsl

                recurso["body"] = {
                    "mimeType": "application/x-www-form-urlencoded",
                    "params": [{"name": c, "value": v} for c, v in parse_qsl(corpo.get("raw") or "")],
                }
            elif corpo.get("raw"):
                recurso["body"] = {
                    "mimeType": "application/json" if corpo.get("mode") == "json" else "text/plain",
                    "text": corpo["raw"],
                }
            recursos.append(recurso)
            return

        meu = identificador("fld")
        recursos.append(
            {
                "_id": meu,
                "_type": "request_group",
                "parentId": pai,
                "name": node.get("name") or "",
                "authentication": _auth_para(node.get("auth")),
                "created": agora,
                "modified": agora,
            }
        )
        for filho in node.get("items") or []:
            andar(filho, meu)

    for colecao in colecoes:
        raiz = identificador("wrk")
        recursos.append(
            {
                "_id": raiz,
                "_type": "workspace",
                "parentId": None,
                "name": colecao.get("name") or "collection",
                "scope": "collection",
                "created": agora,
                "modified": agora,
            }
        )
        for filho in colecao.get("items") or []:
            andar(filho, raiz)

        for env in tree.get("environments") or []:
            recursos.append(
                {
                    "_id": identificador("env"),
                    "_type": "environment",
                    "parentId": raiz,
                    "name": env.get("name") or "ambiente",
                    "data": {
                        v.get("key"): (v.get("value") or "")
                        if (com_segredo or not v.get("secret"))
                        else ""
                        for v in env.get("values") or []
                        if v.get("key")
                    },
                    "created": agora,
                    "modified": agora,
                }
            )

    saida = {
        "_type": "export",
        "__export_format": 4,
        "__export_date": time.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "__export_source": "conduit",
        "resources": recursos,
    }
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(saida, indent=2, ensure_ascii=False), encoding="utf-8")
    return destino
