"""Bruno, pasta com bruno.json e arquivos .bru.

O .bru e uma DSL de blocos, e nao JSON nem YAML:

    meta {
      name: Consulta CEP
      type: http
      seq: 1
    }
    get {
      url: {{baseUrl}}/cep/{{cep}}
      body: none
      auth: none
    }
    headers {
      Accept: application/json
    }
    body:json {
      {"campo": "valor"}
    }

O parser aqui e proposital simples: le bloco por bloco contando chaves, porque o formato
nao tem escape e aninha no maximo um nivel de conteudo livre. Sintaxe de variavel e a
mesma, {{nome}}.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..workspaces import new_id
from . import Resultado

METODOS = ("get", "post", "put", "patch", "delete", "head", "options")


def detectar(caminho: Path) -> float:
    caminho = Path(caminho)
    if caminho.is_dir():
        if (caminho / "bruno.json").exists():
            return 1.0
        if any(caminho.rglob("*.bru")):
            return 0.8
        return 0.0
    return 0.9 if caminho.suffix.lower() == ".bru" else 0.0


def _blocos(texto: str) -> list[tuple[str, str]]:
    """Quebra o arquivo em pares de cabecalho e conteudo, contando chaves."""
    saida: list[tuple[str, str]] = []
    indice = 0
    tamanho = len(texto)

    while indice < tamanho:
        abre = texto.find("{", indice)
        if abre < 0:
            break
        cabecalho = texto[indice:abre].strip()
        profundidade = 1
        cursor = abre + 1
        while cursor < tamanho and profundidade:
            if texto[cursor] == "{":
                profundidade += 1
            elif texto[cursor] == "}":
                profundidade -= 1
            cursor += 1
        conteudo = texto[abre + 1 : cursor - 1]
        if cabecalho:
            saida.append((cabecalho, conteudo))
        indice = cursor

    return saida


def _pares(conteudo: str) -> list[tuple[str, str, bool]]:
    """Linhas `chave: valor`. Chave com ~ na frente quer dizer desligada."""
    saida = []
    for linha in conteudo.splitlines():
        limpa = linha.strip()
        if not limpa or ":" not in limpa:
            continue
        chave, _, valor = limpa.partition(":")
        chave = chave.strip()
        ativo = not chave.startswith("~")
        saida.append((chave.lstrip("~").strip(), valor.strip(), ativo))
    return saida


def _dicionario(conteudo: str) -> dict:
    return {chave: valor for chave, valor, _ in _pares(conteudo)}


def ler_bru(caminho: Path, avisos: list) -> dict | None:
    try:
        texto = Path(caminho).read_text(encoding="utf-8")
    except OSError:
        return None

    blocos = _blocos(texto)
    mapa = {cabecalho: conteudo for cabecalho, conteudo in blocos}

    meta = _dicionario(mapa.get("meta", ""))
    nome = meta.get("name") or Path(caminho).stem

    metodo = "GET"
    dados_metodo: dict = {}
    for chave in METODOS:
        if chave in mapa:
            metodo = chave.upper()
            dados_metodo = _dicionario(mapa[chave])
            break

    url = dados_metodo.get("url") or ""
    node = {
        "id": new_id("req"),
        "type": "request",
        "name": nome,
        "method": metodo,
        "url": url.split("?")[0],
        "params": [],
        "headers": [
            {"key": chave, "value": valor, "enabled": ativo}
            for chave, valor, ativo in _pares(mapa.get("headers", ""))
        ],
        "body": {"mode": "none", "raw": ""},
        "docs": (mapa.get("docs", "") or "").strip(),
        "origin": {"bruno": str(caminho.name)},
    }

    if "?" in url:
        from urllib.parse import parse_qsl

        node["params"] = [
            {"key": c, "value": v, "enabled": True}
            for c, v in parse_qsl(url.split("?", 1)[1], keep_blank_values=True)
        ]
    for chave, valor, ativo in _pares(mapa.get("params:query", "")):
        node["params"].append({"key": chave, "value": valor, "enabled": ativo})

    if "body:json" in mapa:
        node["body"] = {"mode": "json", "raw": mapa["body:json"].strip()}
    elif "body:text" in mapa:
        node["body"] = {"mode": "raw", "raw": mapa["body:text"].strip()}
    elif "body:form-urlencoded" in mapa:
        from urllib.parse import urlencode

        node["body"] = {
            "mode": "form",
            "raw": urlencode([(c, v) for c, v, ativo in _pares(mapa["body:form-urlencoded"]) if ativo]),
        }
    elif "body:graphql" in mapa:
        avisos.append("corpo GraphQL veio como texto")
        node["body"] = {"mode": "raw", "raw": mapa["body:graphql"].strip()}

    if "auth:bearer" in mapa:
        node["auth"] = {"type": "bearer", "token": _dicionario(mapa["auth:bearer"]).get("token", "")}
    elif "auth:basic" in mapa:
        dados = _dicionario(mapa["auth:basic"])
        node["auth"] = {
            "type": "basic",
            "username": dados.get("username", ""),
            "password": dados.get("password", ""),
        }
    elif "auth:apikey" in mapa:
        dados = _dicionario(mapa["auth:apikey"])
        node["auth"] = {
            "type": "apikey",
            "key": dados.get("key", ""),
            "value": dados.get("value", ""),
            "in": dados.get("placement", "header"),
        }

    if "script:pre-request" in mapa or "script:post-response" in mapa or "tests" in mapa:
        avisos.append(f"scripts e testes de {nome} nao vieram, o DBX Wire ainda nao roda script")

    try:
        node["_seq"] = int(meta.get("seq") or 999)
    except ValueError:
        node["_seq"] = 999
    return node


def _pasta(caminho: Path, avisos: list, ignorar: set | None = None) -> dict:
    node = {
        "id": new_id("fld"),
        "type": "folder",
        "name": caminho.name,
        "expanded": False,
        "variables": [],
        "items": [],
    }
    meta = caminho / "folder.bru"
    if meta.exists():
        dados = _dicionario({c: v for c, v in _blocos(meta.read_text(encoding="utf-8"))}.get("meta", ""))
        node["name"] = dados.get("name") or caminho.name

    ignorar = ignorar or set()
    filhos = []
    for item in sorted(caminho.iterdir()):
        if item.name in ignorar:
            continue
        if item.is_dir():
            filhos.append(_pasta(item, avisos))
        elif item.suffix == ".bru" and item.name != "folder.bru":
            lido = ler_bru(item, avisos)
            if lido:
                filhos.append(lido)
    filhos.sort(key=lambda n: n.pop("_seq", 999))
    node["items"] = filhos
    return node


def importar(caminho: Path) -> Resultado:
    resultado = Resultado(formato="Bruno")
    caminho = Path(caminho)

    if caminho.is_file():
        node = ler_bru(caminho, resultado.avisos)
        if node is None:
            resultado.erro = "nao consegui ler o arquivo .bru"
            return resultado
        node.pop("_seq", None)
        resultado.collections.append(
            {
                "id": new_id("col"),
                "type": "collection",
                "name": caminho.stem,
                "expanded": True,
                "variables": [],
                "items": [node],
            }
        )
        return resultado

    nome = caminho.name
    config = caminho / "bruno.json"
    if config.exists():
        try:
            nome = json.loads(config.read_text(encoding="utf-8")).get("name") or nome
        except json.JSONDecodeError:
            pass

    # environments e collection sao tratados a parte, nao sao pasta de request
    raiz = _pasta(caminho, resultado.avisos, ignorar={"environments", "collection"})
    colecao = {
        "id": new_id("col"),
        "type": "collection",
        "name": nome,
        "expanded": True,
        "variables": [],
        "items": raiz["items"],
    }

    pasta_envs = caminho / "environments"
    if pasta_envs.is_dir():
        for arquivo in sorted(pasta_envs.glob("*.bru")):
            blocos = {c: v for c, v in _blocos(arquivo.read_text(encoding="utf-8"))}
            valores = [
                {"key": chave, "value": valor, "enabled": ativo}
                for chave, valor, ativo in _pares(blocos.get("vars", ""))
            ]
            for chave, _, _ in _pares(blocos.get("vars:secret", "")):
                valores.append({"key": chave, "value": "", "enabled": True, "secret": True})
            resultado.environments.append(
                {"id": new_id("env"), "name": arquivo.stem, "values": valores}
            )

    resultado.collections.append(colecao)
    resultado.avisos = sorted(set(resultado.avisos))
    return resultado


def _escrever_bru(node: dict, destino: Path, seq: int) -> None:
    linhas = ["meta {", f"  name: {node.get('name') or ''}", "  type: http", f"  seq: {seq}", "}", ""]

    metodo = (node.get("method") or "GET").lower()
    corpo = node.get("body") or {}
    modo = {"json": "json", "raw": "text", "form": "form-urlencoded"}.get(corpo.get("mode"), "none")
    auth = (node.get("auth") or {}).get("type") or "none"
    auth_bru = {"bearer": "bearer", "basic": "basic", "apikey": "apikey"}.get(auth, "none")

    linhas += [
        f"{metodo} {{",
        f"  url: {node.get('url') or ''}",
        f"  body: {modo}",
        f"  auth: {auth_bru}",
        "}",
        "",
    ]

    params = [p for p in node.get("params") or [] if p.get("key")]
    if params:
        linhas.append("params:query {")
        for p in params:
            marca = "" if p.get("enabled", True) is not False else "~"
            linhas.append(f"  {marca}{p['key']}: {p.get('value') or ''}")
        linhas += ["}", ""]

    headers = [h for h in node.get("headers") or [] if h.get("key")]
    if headers:
        linhas.append("headers {")
        for h in headers:
            marca = "" if h.get("enabled", True) is not False else "~"
            linhas.append(f"  {marca}{h['key']}: {h.get('value') or ''}")
        linhas += ["}", ""]

    if modo == "json":
        linhas += ["body:json {", corpo.get("raw") or "", "}", ""]
    elif modo == "text":
        linhas += ["body:text {", corpo.get("raw") or "", "}", ""]
    elif modo == "form-urlencoded":
        from urllib.parse import parse_qsl

        linhas.append("body:form-urlencoded {")
        for chave, valor in parse_qsl(corpo.get("raw") or ""):
            linhas.append(f"  {chave}: {valor}")
        linhas += ["}", ""]

    config = node.get("auth") or {}
    if auth_bru == "bearer":
        linhas += ["auth:bearer {", f"  token: {config.get('token') or ''}", "}", ""]
    elif auth_bru == "basic":
        linhas += [
            "auth:basic {",
            f"  username: {config.get('username') or ''}",
            f"  password: {config.get('password') or ''}",
            "}",
            "",
        ]
    elif auth_bru == "apikey":
        linhas += [
            "auth:apikey {",
            f"  key: {config.get('key') or ''}",
            f"  value: {config.get('value') or ''}",
            f"  placement: {config.get('in') or 'header'}",
            "}",
            "",
        ]

    if node.get("docs"):
        linhas += ["docs {", node["docs"], "}", ""]

    destino.write_text("\n".join(linhas), encoding="utf-8")


def exportar(tree: dict, colecoes: list, destino: Path, com_segredo: bool = False) -> Path:
    from ..storage import slug

    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)

    nome = colecoes[0].get("name") if len(colecoes) == 1 else "DBX Wire"
    (destino / "bruno.json").write_text(
        json.dumps({"version": "1", "name": nome, "type": "collection"}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    def andar(items, pasta: Path) -> None:
        pasta.mkdir(parents=True, exist_ok=True)
        usados: set[str] = set()
        for indice, node in enumerate(items or []):
            base = slug(node.get("name") or "item", usados)
            if node.get("type") == "request":
                _escrever_bru(node, pasta / f"{base}.bru", indice + 1)
            else:
                sub = pasta / base
                sub.mkdir(parents=True, exist_ok=True)
                (sub / "folder.bru").write_text(
                    "meta {\n" f"  name: {node.get('name') or ''}\n" f"  seq: {indice + 1}\n" "}\n",
                    encoding="utf-8",
                )
                andar(node.get("items"), sub)

    if len(colecoes) == 1:
        andar(colecoes[0].get("items"), destino)
    else:
        for colecao in colecoes:
            andar(colecao.get("items"), destino / slug(colecao.get("name") or "collection"))

    envs = tree.get("environments") or []
    if envs:
        pasta_envs = destino / "environments"
        pasta_envs.mkdir(exist_ok=True)
        for env in envs:
            publicas = [v for v in env.get("values") or [] if v.get("key") and not v.get("secret")]
            secretas = [v for v in env.get("values") or [] if v.get("key") and v.get("secret")]
            linhas = ["vars {"]
            for v in publicas:
                marca = "" if v.get("enabled", True) is not False else "~"
                linhas.append(f"  {marca}{v['key']}: {v.get('value') or ''}")
            linhas.append("}")
            if secretas:
                linhas.append("vars:secret [")
                for v in secretas:
                    linhas.append(f"  {v['key']},")
                linhas.append("]")
            (pasta_envs / f"{slug(env.get('name') or 'ambiente')}.bru").write_text(
                "\n".join(linhas) + "\n", encoding="utf-8"
            )

    return destino
