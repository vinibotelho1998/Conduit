"""Um arquivo por item no disco, em YAML legivel.

Formato:

    workspace/
      settings.yaml            ambiente ativo e versao do formato
      globals.yaml             variaveis globais do workspace
      environments/
        publico.yaml
        local.yaml
      collections/
        brasilapi/
          _collection.yaml     nome, ordem, variaveis da collection
          localidade/
            _folder.yaml
            cep-v2.yaml
            ddd.yaml
          veiculos-fipe/
            _folder.yaml

Por que assim, e nao um JSON so. Diff limpo: mexer num request muda um arquivo, e o
git mostra exatamente o que mudou. Reparo simples: um item corrompido nao leva junto o
resto. E o incidente de 24/08, onde um arrastar e soltar reorganizou a arvore inteira
num unico arquivo sem deixar rastro, simplesmente aparece como movimentacao de arquivo.

A ordem vive no campo `seq` dentro do arquivo, e nao no nome. Numerar o nome faria
qualquer reordenacao renomear meio mundo de arquivo, e o diff ficaria ilegivel.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import yaml

from .vault import Vault, chave_de

SCHEMA_VERSION = 1

# Ordem fixa de chave na gravacao. Sem isso o YAML sai na ordem do dicionario e o diff
# do git fica cheio de ruido que nao e mudanca de verdade.
ORDEM_REQUEST = [
    "schemaVersion", "id", "seq", "name", "method", "url", "favorite",
    "params", "headers", "body", "auth", "settings", "docs", "examples", "origin",
]
ORDEM_GRUPO = [
    "schemaVersion", "id", "seq", "name", "expanded", "variables", "auth", "origin",
]
ORDEM_ENV = ["schemaVersion", "id", "seq", "name", "values"]


class OrdenadoDumper(yaml.SafeDumper):
    """Nao reordena chave e nao usa ancora, entao o arquivo sai igual ao que se espera."""

    def ignore_aliases(self, data):
        return True


def _bloco_str(dumper, data):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


OrdenadoDumper.add_representer(str, _bloco_str)


def slug(nome: str, usados: set[str] | None = None) -> str:
    texto = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode()
    texto = re.sub(r"[^a-zA-Z0-9]+", "-", texto).strip("-").lower()
    texto = texto[:60] or "item"
    if usados is None:
        return texto
    base, conta = texto, 2
    while texto in usados:
        texto = f"{base}-{conta}"
        conta += 1
    usados.add(texto)
    return texto


def _ordenar(dados: dict, ordem: list[str]) -> dict:
    saida = {chave: dados[chave] for chave in ordem if chave in dados and dados[chave] not in (None, [], {})}
    for chave, valor in dados.items():
        if chave not in saida and chave not in ("items", "type") and valor not in (None, [], {}):
            saida[chave] = valor
    return saida


def _escrever(caminho: Path, dados: dict) -> bool:
    """Grava so se o conteudo mudou. Devolve True quando escreveu."""
    texto = yaml.dump(
        dados, Dumper=OrdenadoDumper, sort_keys=False, allow_unicode=True, width=100
    )
    if caminho.exists() and caminho.read_text(encoding="utf-8") == texto:
        return False
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(caminho.suffix + ".tmp")
    temporario.write_text(texto, encoding="utf-8")
    temporario.replace(caminho)
    return True


def assinatura(raiz: str | Path) -> dict[str, int]:
    """Foto de quando cada arquivo foi tocado, pra detectar escrita de fora.

    Existe por causa do incidente de 24/08: com o app aberto e um script gravando no
    mesmo workspace, quem salvou por ultimo apagou o trabalho do outro em silencio.
    """
    raiz = Path(raiz)
    saida: dict[str, int] = {}
    for caminho in raiz.rglob("*.yaml"):
        try:
            saida[caminho.relative_to(raiz).as_posix()] = caminho.stat().st_mtime_ns
        except OSError:
            continue
    return saida


def _guardar_conflito(raiz: Path, caminho: Path) -> Path:
    """Salva o arquivo que mudou por fora antes de sobrescrever."""
    from datetime import datetime

    destino = raiz / ".dbxwire" / "conflitos" / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    destino.mkdir(parents=True, exist_ok=True)
    alvo = destino / caminho.name
    alvo.write_bytes(caminho.read_bytes())
    return alvo


def _ler(caminho: Path) -> dict:
    try:
        return yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def ler_workspace(raiz: str | Path, cofre: Vault | None = None) -> dict:
    raiz = Path(raiz)
    cofre = cofre if cofre is not None else Vault(raiz)
    settings = _ler(raiz / "settings.yaml")

    tree = {
        "schemaVersion": settings.get("schemaVersion", SCHEMA_VERSION),
        "activeEnv": settings.get("activeEnv"),
        "sortMode": settings.get("sortMode") or "manual",
        "certificates": settings.get("certificates") or [],
        "caFile": settings.get("caFile") or "",
        "globals": _ler(raiz / "globals.yaml").get("values") or [],
        "environments": [],
        "collections": [],
    }

    pasta_envs = raiz / "environments"
    if pasta_envs.is_dir():
        envs = []
        for arquivo in sorted(pasta_envs.glob("*.yaml")):
            dados = _ler(arquivo)
            if not dados:
                continue
            env_id = dados.get("id") or arquivo.stem
            valores = dados.get("values") or []
            # O arquivo versionado guarda so o contrato: nome da variavel e a marca de
            # secreta. O valor secreto vem do cofre, que fica fora do git.
            for item in valores:
                if item.get("secret") and not item.get("value"):
                    item["value"] = cofre.get(chave_de(env_id, item.get("key") or ""))
            envs.append(
                {
                    "id": env_id,
                    "name": dados.get("name") or arquivo.stem,
                    "values": valores,
                    "_seq": dados.get("seq", 999),
                }
            )
        envs.sort(key=lambda e: e.pop("_seq"))
        tree["environments"] = envs

    pasta_cols = raiz / "collections"
    if pasta_cols.is_dir():
        colecoes = []
        for diretorio in sorted(p for p in pasta_cols.iterdir() if p.is_dir()):
            node = _ler_grupo(diretorio, "collection")
            if node:
                colecoes.append(node)
        colecoes.sort(key=lambda n: n.pop("_seq", 999))
        tree["collections"] = colecoes

    return tree


def _ler_grupo(diretorio: Path, tipo: str) -> dict | None:
    arquivo = diretorio / ("_collection.yaml" if tipo == "collection" else "_folder.yaml")
    dados = _ler(arquivo) if arquivo.exists() else {}
    if not dados and not any(diretorio.iterdir()):
        return None

    node = {
        "id": dados.get("id") or diretorio.name,
        "type": tipo,
        "name": dados.get("name") or diretorio.name,
        "expanded": bool(dados.get("expanded")),
        "variables": dados.get("variables") or [],
        "items": [],
        "_seq": dados.get("seq", 999),
    }
    if dados.get("auth"):
        node["auth"] = dados["auth"]
    if dados.get("origin"):
        node["origin"] = dados["origin"]

    filhos = []
    for caminho in sorted(diretorio.iterdir()):
        if caminho.is_dir():
            filho = _ler_grupo(caminho, "folder")
            if filho:
                filhos.append(filho)
        elif caminho.suffix == ".yaml" and not caminho.name.startswith("_"):
            filho = _ler_request(caminho)
            if filho:
                filhos.append(filho)

    filhos.sort(key=lambda n: n.pop("_seq", 999))
    node["items"] = filhos
    return node


def _ler_request(caminho: Path) -> dict | None:
    dados = _ler(caminho)
    if not dados:
        return None
    node = {
        "id": dados.get("id") or caminho.stem,
        "type": "request",
        "name": dados.get("name") or caminho.stem,
        "method": dados.get("method") or "GET",
        "url": dados.get("url") or "",
        "params": dados.get("params") or [],
        "headers": dados.get("headers") or [],
        "body": dados.get("body") or {"mode": "none", "raw": ""},
        "docs": dados.get("docs") or "",
        "_seq": dados.get("seq", 999),
    }
    for extra in ("favorite", "auth", "settings", "examples", "origin"):
        if dados.get(extra):
            node[extra] = dados[extra]
    return node


def gravar_workspace(
    raiz: str | Path, tree: dict, anterior: dict | None = None, cofre: Vault | None = None
) -> dict:
    """Grava a arvore inteira e apaga o que sobrou. Devolve um resumo do que mexeu.

    Com `anterior`, que e a assinatura de quando o workspace foi lido, qualquer arquivo
    que tenha mudado por fora e copiado pra .dbxwire/conflitos antes de ser sobrescrito.
    Nada se perde em silencio.
    """
    raiz = Path(raiz)
    raiz.mkdir(parents=True, exist_ok=True)

    resumo = {"escritos": 0, "apagados": 0, "conflitos": [], "segredos": 0}
    vivos: set[Path] = set()
    cofre = cofre if cofre is not None else Vault(raiz)

    if anterior is not None:
        agora = assinatura(raiz)
        for relativo, marca in agora.items():
            se_conhecia = anterior.get(relativo)
            if se_conhecia is not None and se_conhecia != marca:
                caminho = raiz / relativo
                _guardar_conflito(raiz, caminho)
                resumo["conflitos"].append(relativo)

    caminho = raiz / "settings.yaml"
    if _escrever(
        caminho,
        {
            "schemaVersion": SCHEMA_VERSION,
            "activeEnv": tree.get("activeEnv"),
            "sortMode": tree.get("sortMode") or "manual",
            "certificates": tree.get("certificates") or [],
            "caFile": tree.get("caFile") or "",
        },
    ):
        resumo["escritos"] += 1
    vivos.add(caminho)

    caminho = raiz / "globals.yaml"
    if _escrever(caminho, {"schemaVersion": SCHEMA_VERSION, "values": tree.get("globals") or []}):
        resumo["escritos"] += 1
    vivos.add(caminho)

    pasta_envs = raiz / "environments"
    pasta_envs.mkdir(exist_ok=True)
    usados: set[str] = set()
    segredos: dict[str, str] = {}

    for indice, env in enumerate(tree.get("environments") or []):
        nome = slug(env.get("name") or env.get("id") or "ambiente", usados)
        caminho = pasta_envs / f"{nome}.yaml"
        env_id = env.get("id") or nome

        # Separa o valor secreto antes de escrever. O que vai pro arquivo e o contrato,
        # o valor vai pro cofre cifrado.
        publicos = []
        for item in env.get("values") or []:
            copia = dict(item)
            if copia.get("secret"):
                segredos[chave_de(env_id, copia.get("key") or "")] = copia.get("value") or ""
                copia["value"] = ""
            publicos.append(copia)

        dados = _ordenar(
            {
                "schemaVersion": SCHEMA_VERSION,
                "id": env.get("id"),
                "seq": indice,
                "name": env.get("name"),
                "values": publicos,
            },
            ORDEM_ENV,
        )
        if _escrever(caminho, dados):
            resumo["escritos"] += 1
        vivos.add(caminho)

    if segredos:
        try:
            resumo["segredos"] = cofre.set_muitos(segredos)
        except Exception as exc:  # noqa: BLE001
            resumo["erro_cofre"] = f"{type(exc).__name__}: {exc}"

    pasta_cols = raiz / "collections"
    pasta_cols.mkdir(exist_ok=True)
    usados = set()
    diretorios_vivos: set[Path] = set()
    for indice, colecao in enumerate(tree.get("collections") or []):
        destino = pasta_cols / slug(colecao.get("name") or "collection", usados)
        _gravar_grupo(destino, colecao, indice, "collection", vivos, diretorios_vivos, resumo)

    # Limpeza do que nao pertence mais a arvore. So mexe dentro de collections e de
    # environments: settings.yaml, globals.yaml e qualquer outra coisa na raiz do
    # workspace ficam de fora por seguranca.
    for caminho in sorted(raiz.rglob("*.yaml"), reverse=True):
        if caminho in vivos:
            continue
        dentro_de_collections = pasta_cols in caminho.parents
        dentro_de_environments = caminho.parent == pasta_envs
        if dentro_de_collections or dentro_de_environments:
            caminho.unlink(missing_ok=True)
            resumo["apagados"] += 1

    for caminho in sorted((p for p in pasta_cols.rglob("*") if p.is_dir()), reverse=True):
        if caminho not in diretorios_vivos:
            try:
                caminho.rmdir()
                resumo["apagados"] += 1
            except OSError:
                pass

    for caminho in sorted((p for p in pasta_cols.iterdir() if p.is_dir()), reverse=True):
        if caminho not in diretorios_vivos:
            try:
                caminho.rmdir()
                resumo["apagados"] += 1
            except OSError:
                pass

    return resumo


def _gravar_grupo(destino: Path, node: dict, seq: int, tipo: str, vivos, diretorios, resumo) -> None:
    destino.mkdir(parents=True, exist_ok=True)
    diretorios.add(destino)

    arquivo = destino / ("_collection.yaml" if tipo == "collection" else "_folder.yaml")
    dados = _ordenar(
        {
            "schemaVersion": SCHEMA_VERSION,
            "id": node.get("id"),
            "seq": seq,
            "name": node.get("name"),
            "expanded": bool(node.get("expanded")),
            "variables": node.get("variables") or [],
            "auth": node.get("auth") or None,
            "origin": node.get("origin"),
        },
        ORDEM_GRUPO,
    )
    if _escrever(arquivo, dados):
        resumo["escritos"] += 1
    vivos.add(arquivo)

    usados: set[str] = set()
    for indice, filho in enumerate(node.get("items") or []):
        nome = slug(filho.get("name") or "item", usados)
        if filho.get("type") == "request":
            caminho = destino / f"{nome}.yaml"
            corpo = _ordenar(
                {
                    "schemaVersion": SCHEMA_VERSION,
                    "id": filho.get("id"),
                    "seq": indice,
                    "name": filho.get("name"),
                    "method": filho.get("method") or "GET",
                    "url": filho.get("url") or "",
                    "favorite": bool(filho.get("favorite")) or None,
                    "params": filho.get("params") or [],
                    "headers": filho.get("headers") or [],
                    "body": filho.get("body") or None,
                    "auth": filho.get("auth"),
                    "settings": filho.get("settings"),
                    "docs": filho.get("docs") or "",
                    "examples": filho.get("examples") or None,
                    "origin": filho.get("origin"),
                },
                ORDEM_REQUEST,
            )
            if _escrever(caminho, corpo):
                resumo["escritos"] += 1
            vivos.add(caminho)
        else:
            _gravar_grupo(destino / nome, filho, indice, "folder", vivos, diretorios, resumo)
