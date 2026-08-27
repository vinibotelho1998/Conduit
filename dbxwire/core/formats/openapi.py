"""OpenAPI 3 e Swagger 2, em JSON ou YAML.

Importar uma spec e diferente de importar uma collection: a spec descreve o contrato, e
nao chamadas que alguem montou. Entao aqui cada operacao vira um request, o servidor vira
`{{baseUrl}}`, e parametro de caminho vira variavel, `/pets/{petId}` virando
`/pets/{{petId}}`. O agrupamento sai das tags, que e como a propria spec se organiza.

Exportar e o caminho de volta e nunca sai perfeito, porque a collection nao carrega
esquema de resposta. O que sai e o caminho, o metodo, os parametros e o exemplo de corpo,
que ja e util pra abrir conversa com quem mantem a API.
"""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urlsplit

from ..workspaces import new_id
from . import Resultado

CHAVE_CAMINHO = re.compile(r"\{([^}/]+)\}")
METODOS = ("get", "post", "put", "patch", "delete", "head", "options")


def _carregar(caminho: Path):
    texto = Path(caminho).read_text(encoding="utf-8")
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        import yaml

        return yaml.safe_load(texto)


def detectar(caminho: Path) -> float:
    caminho = Path(caminho)
    if caminho.is_dir() or caminho.suffix.lower() not in (".json", ".yaml", ".yml"):
        return 0.0
    try:
        texto = caminho.read_text(encoding="utf-8")
    except OSError:
        return 0.0
    if not re.search(r'["\']?(openapi|swagger)["\']?\s*:', texto[:4000]):
        return 0.0
    try:
        dados = _carregar(caminho)
    except Exception:  # noqa: BLE001
        return 0.0
    if isinstance(dados, dict) and (dados.get("openapi") or dados.get("swagger")):
        return 1.0
    return 0.0


def _exemplo_de_esquema(esquema: dict, profundidade: int = 0) -> object:
    """Inventa um corpo de exemplo a partir do esquema, pra o request nascer utilizavel."""
    if not isinstance(esquema, dict) or profundidade > 6:
        return {}

    if "example" in esquema:
        return esquema["example"]
    if "default" in esquema:
        return esquema["default"]
    if esquema.get("enum"):
        return esquema["enum"][0]

    tipo = esquema.get("type")
    if tipo == "object" or "properties" in esquema:
        return {
            nome: _exemplo_de_esquema(sub, profundidade + 1)
            for nome, sub in (esquema.get("properties") or {}).items()
        }
    if tipo == "array":
        return [_exemplo_de_esquema(esquema.get("items") or {}, profundidade + 1)]
    if tipo == "integer":
        return 0
    if tipo == "number":
        return 0.0
    if tipo == "boolean":
        return False
    formato = esquema.get("format") or ""
    if formato == "date":
        return "2026-01-01"
    if formato == "date-time":
        return "2026-01-01T00:00:00Z"
    return ""


def _resolver(dados: dict, no: dict, vistos=None) -> dict:
    """Segue $ref dentro do proprio arquivo."""
    vistos = vistos or set()
    if not isinstance(no, dict):
        return {}
    referencia = no.get("$ref")
    if not referencia or not referencia.startswith("#/") or referencia in vistos:
        return no
    vistos.add(referencia)
    alvo = dados
    for parte in referencia[2:].split("/"):
        if not isinstance(alvo, dict):
            return {}
        alvo = alvo.get(parte.replace("~1", "/").replace("~0", "~"), {})
    return _resolver(dados, alvo, vistos)


def importar(caminho: Path) -> Resultado:
    resultado = Resultado(formato="OpenAPI")
    try:
        dados = _carregar(caminho)
    except Exception as exc:  # noqa: BLE001
        resultado.erro = f"nao consegui ler a spec: {exc}"
        return resultado

    if not isinstance(dados, dict):
        resultado.erro = "a spec nao e um objeto"
        return resultado

    info = dados.get("info") or {}
    nome = info.get("title") or Path(caminho).stem
    versao_spec = dados.get("openapi") or dados.get("swagger") or ""

    # servidor vira baseUrl
    if dados.get("servers"):
        base = (dados["servers"][0] or {}).get("url") or ""
    elif dados.get("host"):
        esquema = (dados.get("schemes") or ["https"])[0]
        base = f"{esquema}://{dados['host']}{dados.get('basePath') or ''}"
    else:
        base = ""

    variaveis = [{"key": "baseUrl", "value": base, "enabled": True}]
    nomes_de_caminho: set[str] = set()

    grupos: "OrderedDict[str, list]" = OrderedDict()

    for rota, operacoes in (dados.get("paths") or {}).items():
        if not isinstance(operacoes, dict):
            continue
        comuns = operacoes.get("parameters") or []

        for metodo, operacao in operacoes.items():
            if metodo.lower() not in METODOS or not isinstance(operacao, dict):
                continue

            rota_com_vars = CHAVE_CAMINHO.sub(lambda m: "{{" + m.group(1) + "}}", rota)
            nomes_de_caminho.update(CHAVE_CAMINHO.findall(rota))

            parametros = [
                _resolver(dados, p) for p in list(comuns) + list(operacao.get("parameters") or [])
            ]
            query = []
            headers = []
            for parametro in parametros:
                onde = parametro.get("in")
                nome_p = parametro.get("name") or ""
                if not nome_p:
                    continue
                exemplo = parametro.get("example")
                if exemplo is None:
                    exemplo = _exemplo_de_esquema(_resolver(dados, parametro.get("schema") or {}))
                valor = "" if exemplo in ({}, [], None) else str(exemplo)
                if onde == "query":
                    query.append(
                        {"key": nome_p, "value": valor, "enabled": bool(parametro.get("required"))}
                    )
                elif onde == "header":
                    headers.append({"key": nome_p, "value": valor, "enabled": True})

            corpo = {"mode": "none", "raw": ""}
            requisicao = _resolver(dados, operacao.get("requestBody") or {})
            conteudo = (requisicao.get("content") or {}) if requisicao else {}
            if not conteudo and metodo.lower() in ("post", "put", "patch"):
                # swagger 2 poe o corpo como parametro in: body
                for parametro in parametros:
                    if parametro.get("in") == "body":
                        conteudo = {"application/json": {"schema": parametro.get("schema") or {}}}
                        break

            for tipo, definicao in (conteudo or {}).items():
                esquema = _resolver(dados, (definicao or {}).get("schema") or {})
                exemplo = (definicao or {}).get("example")
                if exemplo is None:
                    exemplo = _exemplo_de_esquema(esquema)
                if "json" in tipo:
                    corpo = {"mode": "json", "raw": json.dumps(exemplo, indent=2, ensure_ascii=False)}
                    headers.append({"key": "Content-Type", "value": tipo, "enabled": True})
                elif "urlencoded" in tipo:
                    from urllib.parse import urlencode

                    plano = exemplo if isinstance(exemplo, dict) else {}
                    corpo = {"mode": "form", "raw": urlencode({k: str(v) for k, v in plano.items()})}
                break

            titulo = operacao.get("summary") or operacao.get("operationId") or f"{metodo.upper()} {rota}"
            documentacao = operacao.get("description") or ""
            if operacao.get("operationId"):
                documentacao = f"operationId: {operacao['operationId']}\n\n{documentacao}".strip()

            node = {
                "id": new_id("req"),
                "type": "request",
                "name": titulo,
                "method": metodo.upper(),
                "url": "{{baseUrl}}" + rota_com_vars,
                "params": query,
                "headers": headers,
                "body": corpo,
                "docs": documentacao,
                "origin": {"openapi": f"{metodo.upper()} {rota}"},
            }

            tags = operacao.get("tags") or ["geral"]
            grupos.setdefault(str(tags[0]), []).append(node)

    for nome_var in sorted(nomes_de_caminho):
        variaveis.append({"key": nome_var, "value": "", "enabled": True})

    colecao = {
        "id": new_id("col"),
        "type": "collection",
        "name": nome,
        "expanded": True,
        "variables": variaveis,
        "items": [],
        "origin": {"openapi": versao_spec},
    }

    if len(grupos) == 1 and "geral" in grupos:
        colecao["items"] = grupos["geral"]
    else:
        for tag, requests in grupos.items():
            colecao["items"].append(
                {
                    "id": new_id("fld"),
                    "type": "folder",
                    "name": tag,
                    "expanded": False,
                    "variables": [],
                    "items": requests,
                }
            )

    seguranca = (dados.get("components") or {}).get("securitySchemes") or dados.get(
        "securityDefinitions"
    ) or {}
    for esquema in seguranca.values():
        tipo = (esquema or {}).get("type", "").lower()
        if tipo == "http" and esquema.get("scheme") == "bearer":
            colecao["auth"] = {"type": "bearer", "token": "{{token}}"}
            variaveis.append({"key": "token", "value": "", "enabled": True, "secret": True})
            break
        if tipo == "apikey":
            colecao["auth"] = {
                "type": "apikey",
                "key": esquema.get("name") or "X-Api-Key",
                "value": "{{apiKey}}",
                "in": esquema.get("in") or "header",
            }
            variaveis.append({"key": "apiKey", "value": "", "enabled": True, "secret": True})
            break

    resultado.collections.append(colecao)
    if not colecao["items"]:
        resultado.avisos.append("a spec nao tinha nenhuma operacao em paths")
    resultado.avisos.append(
        "esquema de resposta, exemplos nomeados e seguranca por operacao nao viraram request"
    )
    return resultado


def exportar(tree: dict, colecoes: list, destino: Path, com_segredo: bool = False) -> Path:
    """Gera uma spec a partir das collections. E aproximacao, nao contrato."""
    caminhos: dict[str, dict] = {}
    servidores: set[str] = set()

    def andar(items, prefixo: list):
        for node in items or []:
            if node.get("type") != "request":
                andar(node.get("items"), prefixo + [node.get("name") or ""])
                continue

            url = node.get("url") or ""
            partes = urlsplit(url)
            if partes.scheme:
                servidores.add(f"{partes.scheme}://{partes.netloc}")
                rota = partes.path or "/"
            else:
                rota = url
            # a variavel volta a ser parametro de caminho
            rota = re.sub(r"\{\{\s*([\w.$-]+)\s*\}\}", lambda m: "{" + m.group(1) + "}", rota)
            if not rota.startswith("/"):
                rota = "/" + rota.split("/", 1)[-1] if "/" in rota else "/"

            metodo = (node.get("method") or "GET").lower()
            operacao = {
                "summary": node.get("name") or "",
                "description": node.get("docs") or "",
                "tags": [prefixo[-1]] if prefixo else [],
                "parameters": [
                    {
                        "name": p.get("key"),
                        "in": "query",
                        "required": p.get("enabled", True) is not False,
                        "schema": {"type": "string"},
                        "example": p.get("value") or "",
                    }
                    for p in node.get("params") or []
                    if p.get("key")
                ]
                + [
                    {"name": nome, "in": "path", "required": True, "schema": {"type": "string"}}
                    for nome in CHAVE_CAMINHO.findall(rota)
                ],
                "responses": {"200": {"description": "resposta de sucesso"}},
            }

            corpo = node.get("body") or {}
            if corpo.get("mode") in ("json", "raw") and corpo.get("raw"):
                try:
                    exemplo = json.loads(corpo["raw"])
                except (json.JSONDecodeError, ValueError):
                    exemplo = corpo["raw"]
                operacao["requestBody"] = {
                    "content": {"application/json": {"example": exemplo}}
                }

            caminhos.setdefault(rota, {})[metodo] = operacao

    for colecao in colecoes:
        andar(colecao.get("items"), [])

    nome = colecoes[0].get("name") if len(colecoes) == 1 else "DBX Wire"
    spec = {
        "openapi": "3.0.3",
        "info": {
            "title": nome,
            "version": "1.0.0",
            "description": "Gerado pelo DBX Wire a partir das collections. "
            "E uma aproximacao: nao carrega esquema de resposta.",
        },
        "servers": [{"url": s} for s in sorted(servidores)] or [{"url": "{{baseUrl}}"}],
        "paths": caminhos,
    }

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.suffix.lower() in (".yaml", ".yml"):
        import yaml

        destino.write_text(
            yaml.dump(spec, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
    else:
        destino.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
    return destino
