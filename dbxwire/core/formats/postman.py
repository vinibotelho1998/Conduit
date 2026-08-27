"""Postman Collection v2.1 e environment do Postman.

A sintaxe de variavel e a mesma, {{nome}}, entao nada precisa ser reescrito no meio do
caminho. O que muda de verdade e a forma da url, que no Postman as vezes vem como objeto
com host e path separados, e a auth, que tem nome de campo proprio.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..workspaces import new_id
from . import Resultado

SCHEMA = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"


# ------------------------------------------------------------------ deteccao


def detectar(caminho: Path) -> float:
    if caminho.is_dir() or caminho.suffix.lower() != ".json":
        return 0.0
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0.0
    if isinstance(dados, dict):
        if "collection/v2" in str((dados.get("info") or {}).get("schema") or ""):
            return 1.0
        if "info" in dados and "item" in dados:
            return 0.8
        # environment do Postman
        if "values" in dados and dados.get("_postman_variable_scope"):
            return 0.9
    return 0.0


# ----------------------------------------------------------------- importacao


def _url_de(bruto) -> tuple[str, list]:
    if isinstance(bruto, str):
        return bruto, []
    if not isinstance(bruto, dict):
        return "", []

    query = [
        {
            "key": item.get("key") or "",
            "value": item.get("value") or "",
            "enabled": not item.get("disabled"),
        }
        for item in bruto.get("query") or []
        if item.get("key")
    ]

    crua = bruto.get("raw") or ""
    if crua:
        return crua.split("?")[0], query

    esquema = bruto.get("protocol") or "https"
    host = bruto.get("host")
    host = ".".join(host) if isinstance(host, list) else (host or "")
    caminho = bruto.get("path")
    caminho = "/".join(str(p) for p in caminho) if isinstance(caminho, list) else (caminho or "")
    return f"{esquema}://{host}/{caminho}".rstrip("/"), query


def _auth_de(bruto) -> dict | None:
    if not isinstance(bruto, dict):
        return None
    tipo = bruto.get("type")

    def campo(lista, nome, padrao=""):
        for item in lista or []:
            if item.get("key") == nome:
                return item.get("value") or padrao
        return padrao

    if tipo == "bearer":
        return {"type": "bearer", "token": campo(bruto.get("bearer"), "token")}
    if tipo == "basic":
        return {
            "type": "basic",
            "username": campo(bruto.get("basic"), "username"),
            "password": campo(bruto.get("basic"), "password"),
        }
    if tipo == "apikey":
        dados = bruto.get("apikey")
        return {
            "type": "apikey",
            "key": campo(dados, "key"),
            "value": campo(dados, "value"),
            "in": campo(dados, "in", "header"),
        }
    if tipo == "oauth2":
        dados = bruto.get("oauth2")
        return {
            "type": "oauth2",
            "tokenUrl": campo(dados, "accessTokenUrl"),
            "clientId": campo(dados, "clientId"),
            "clientSecret": campo(dados, "clientSecret"),
            "scope": campo(dados, "scope"),
        }
    if tipo == "noauth":
        return {"type": "none"}
    return None


def _corpo_de(bruto, avisos: list) -> dict:
    if not isinstance(bruto, dict):
        return {"mode": "none", "raw": ""}

    modo = bruto.get("mode")
    if modo == "raw":
        crua = bruto.get("raw") or ""
        linguagem = ((bruto.get("options") or {}).get("raw") or {}).get("language")
        eh_json = linguagem == "json" or crua.lstrip().startswith(("{", "["))
        return {"mode": "json" if eh_json else "raw", "raw": crua}

    if modo == "urlencoded":
        from urllib.parse import urlencode

        pares = [
            (item.get("key") or "", item.get("value") or "")
            for item in bruto.get("urlencoded") or []
            if not item.get("disabled")
        ]
        return {"mode": "form", "raw": urlencode(pares)}

    if modo == "formdata":
        avisos.append("corpo multipart virou form urlencoded, arquivo anexado nao vem junto")
        from urllib.parse import urlencode

        pares = [
            (item.get("key") or "", item.get("value") or "")
            for item in bruto.get("formdata") or []
            if not item.get("disabled") and item.get("type") != "file"
        ]
        return {"mode": "form", "raw": urlencode(pares)}

    if modo in ("graphql", "file"):
        avisos.append(f"corpo do tipo {modo} ainda nao tem suporte, veio vazio")

    return {"mode": "none", "raw": ""}


def _item(bruto: dict, avisos: list) -> dict | None:
    nome = bruto.get("name") or "sem nome"

    if "item" in bruto:
        filhos = [_item(f, avisos) for f in bruto.get("item") or []]
        pasta = {
            "id": new_id("fld"),
            "type": "folder",
            "name": nome,
            "expanded": False,
            "variables": [],
            "items": [f for f in filhos if f],
        }
        auth = _auth_de(bruto.get("auth"))
        if auth:
            pasta["auth"] = auth
        return pasta

    pedido = bruto.get("request")
    if pedido is None:
        return None
    if isinstance(pedido, str):
        pedido = {"method": "GET", "url": pedido}

    url, query = _url_de(pedido.get("url"))
    node = {
        "id": new_id("req"),
        "type": "request",
        "name": nome,
        "method": (pedido.get("method") or "GET").upper(),
        "url": url,
        "params": query,
        "headers": [
            {
                "key": h.get("key") or "",
                "value": h.get("value") or "",
                "enabled": not h.get("disabled"),
            }
            for h in pedido.get("header") or []
            if h.get("key")
        ],
        "body": _corpo_de(pedido.get("body"), avisos),
        "docs": (pedido.get("description") or "") if isinstance(pedido.get("description"), str) else "",
        "origin": {"postman": bruto.get("id") or ""},
    }

    auth = _auth_de(pedido.get("auth"))
    if auth:
        node["auth"] = auth

    if bruto.get("event"):
        avisos.append(f"scripts de {nome} nao vieram, o DBX Wire ainda nao roda script")

    return node


def importar(caminho: Path) -> Resultado:
    resultado = Resultado(formato="Postman")
    try:
        dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        resultado.erro = f"nao consegui ler o arquivo: {exc}"
        return resultado

    # arquivo de environment
    if "values" in dados and "item" not in dados:
        resultado.environments.append(
            {
                "id": new_id("env"),
                "name": dados.get("name") or Path(caminho).stem,
                "values": [
                    {
                        "key": item.get("key") or "",
                        "value": item.get("value") or "",
                        "enabled": item.get("enabled", True),
                        "secret": item.get("type") == "secret",
                    }
                    for item in dados.get("values") or []
                    if item.get("key")
                ],
            }
        )
        return resultado

    info = dados.get("info") or {}
    colecao = {
        "id": new_id("col"),
        "type": "collection",
        "name": info.get("name") or Path(caminho).stem,
        "expanded": True,
        "variables": [
            {
                "key": v.get("key") or "",
                "value": str(v.get("value") or ""),
                "enabled": not v.get("disabled"),
            }
            for v in dados.get("variable") or []
            if v.get("key")
        ],
        "items": [],
        "origin": {"postman": info.get("_postman_id") or ""},
    }

    auth = _auth_de(dados.get("auth"))
    if auth:
        colecao["auth"] = auth

    for bruto in dados.get("item") or []:
        node = _item(bruto, resultado.avisos)
        if node:
            colecao["items"].append(node)

    resultado.collections.append(colecao)
    resultado.avisos = sorted(set(resultado.avisos))
    return resultado


# ------------------------------------------------------------------ exportacao


def _auth_para(config: dict | None):
    if not config or config.get("type") in (None, "none", "inherit"):
        return None
    tipo = config["type"]
    if tipo == "bearer":
        return {"type": "bearer", "bearer": [{"key": "token", "value": config.get("token", "")}]}
    if tipo == "basic":
        return {
            "type": "basic",
            "basic": [
                {"key": "username", "value": config.get("username", "")},
                {"key": "password", "value": config.get("password", "")},
            ],
        }
    if tipo == "apikey":
        return {
            "type": "apikey",
            "apikey": [
                {"key": "key", "value": config.get("key", "")},
                {"key": "value", "value": config.get("value", "")},
                {"key": "in", "value": config.get("in", "header")},
            ],
        }
    if tipo == "oauth2":
        return {
            "type": "oauth2",
            "oauth2": [
                {"key": "accessTokenUrl", "value": config.get("tokenUrl", "")},
                {"key": "clientId", "value": config.get("clientId", "")},
                {"key": "clientSecret", "value": config.get("clientSecret", "")},
                {"key": "scope", "value": config.get("scope", "")},
                {"key": "grant_type", "value": "client_credentials"},
            ],
        }
    return None


def _item_para(node: dict) -> dict:
    if node.get("type") != "request":
        saida = {"name": node.get("name") or "", "item": [_item_para(f) for f in node.get("items") or []]}
        auth = _auth_para(node.get("auth"))
        if auth:
            saida["auth"] = auth
        return saida

    base = node.get("url") or ""
    query = [
        {"key": p.get("key"), "value": p.get("value"), "disabled": p.get("enabled") is False}
        for p in node.get("params") or []
        if p.get("key")
    ]
    crua = base
    ativos = [p for p in query if not p["disabled"]]
    if ativos:
        crua = base + "?" + "&".join(f"{p['key']}={p['value']}" for p in ativos)

    pedido = {
        "method": node.get("method") or "GET",
        "header": [
            {"key": h.get("key"), "value": h.get("value"), "disabled": h.get("enabled") is False}
            for h in node.get("headers") or []
            if h.get("key")
        ],
        "url": {"raw": crua, "query": query},
    }

    corpo = node.get("body") or {}
    if corpo.get("mode") == "form":
        from urllib.parse import parse_qsl

        pedido["body"] = {
            "mode": "urlencoded",
            "urlencoded": [
                {"key": c, "value": v} for c, v in parse_qsl(corpo.get("raw") or "")
            ],
        }
    elif corpo.get("mode") in ("json", "raw") and corpo.get("raw"):
        pedido["body"] = {
            "mode": "raw",
            "raw": corpo["raw"],
            "options": {"raw": {"language": "json" if corpo["mode"] == "json" else "text"}},
        }

    auth = _auth_para(node.get("auth"))
    if auth:
        pedido["auth"] = auth
    if node.get("docs"):
        pedido["description"] = node["docs"]

    return {"name": node.get("name") or "", "request": pedido}


def exportar_collection(colecao: dict, destino: Path) -> Path:
    saida = {
        "info": {
            "name": colecao.get("name") or "collection",
            "schema": SCHEMA,
            "_exporter_id": "dbx-wire",
        },
        "item": [_item_para(f) for f in colecao.get("items") or []],
    }
    variaveis = [
        {"key": v.get("key"), "value": v.get("value") or "", "disabled": v.get("enabled") is False}
        for v in colecao.get("variables") or []
        if v.get("key")
    ]
    if variaveis:
        saida["variable"] = variaveis
    auth = _auth_para(colecao.get("auth"))
    if auth:
        saida["auth"] = auth

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(saida, indent=2, ensure_ascii=False), encoding="utf-8")
    return destino


def exportar_environment(env: dict, destino: Path, com_segredo: bool = False) -> Path:
    saida = {
        "id": env.get("id"),
        "name": env.get("name") or "ambiente",
        "values": [
            {
                "key": v.get("key"),
                "value": (v.get("value") or "") if (com_segredo or not v.get("secret")) else "",
                "enabled": v.get("enabled", True) is not False,
                "type": "secret" if v.get("secret") else "default",
            }
            for v in env.get("values") or []
            if v.get("key")
        ],
        "_postman_variable_scope": "environment",
        "_postman_exported_using": "dbx-wire",
    }
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(saida, indent=2, ensure_ascii=False), encoding="utf-8")
    return destino
