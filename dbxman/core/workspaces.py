"""Registro e acesso aos workspaces do DBX Wire.

Cada workspace e uma pasta isolada com suas proprias collections, environments,
cofre e historico. Nada vaza de um workspace pro outro.

O conteudo vive em arquivos YAML, um por request, conforme o storage.py. O tree.json
antigo ainda e lido uma unica vez, pra migrar quem ja tinha dados, e vira backup.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from . import storage
from .vault import Vault

def _raiz_de_dados() -> Path:
    """Pasta de dados. Mudou de DBX-MAN pra DBX-Wire junto com o nome do programa.

    Se a antiga existir e a nova nao, move de uma vez. Deixar as duas seria pior:
    o app leria de uma e o usuario procuraria na outra.
    """
    definido = os.environ.get("DBXMAN_HOME")
    if definido:
        return Path(definido)

    nova = Path.home() / "DBX-Wire"
    antiga = Path.home() / "DBX-MAN"
    if antiga.exists() and not nova.exists():
        try:
            antiga.rename(nova)
        except OSError:
            return antiga
    return nova


ROOT = _raiz_de_dados()
WORKSPACES_DIR = ROOT / "workspaces"
REGISTRY = ROOT / "workspaces.json"

COLORS = ["#4da3ff", "#49cc90", "#fca130", "#c084fc", "#f93e3e", "#50e3c2"]

# O que nunca pode ir pro git de um workspace compartilhado. Ver secao 5.3 do PLANO.md:
# o environment versionado carrega o contrato, os nomes das variaveis, e o valor secreto
# fica no cofre local.
GITIGNORE = """# gerado pelo DBX Wire
.secrets/
certs/
history/
cookies/
ai-log/
.dbxman/
tree.json.migrado
*.tmp
"""


def slug(name: str) -> str:
    txt = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    txt = re.sub(r"[^a-zA-Z0-9]+", "-", txt).strip("-").lower()
    return txt or "workspace"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_root() -> None:
    WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)
    (ROOT / ".dbxman").mkdir(exist_ok=True)
    if not REGISTRY.exists():
        _write_registry({"schemaVersion": 1, "active": None, "workspaces": []})


def _read_registry() -> dict:
    ensure_root()
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _write_registry(data: dict) -> None:
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(REGISTRY)


def list_workspaces() -> dict:
    return _read_registry()


def create_workspace(name: str, color: str | None = None) -> dict:
    reg = _read_registry()
    wid = slug(name)
    if any(w["id"] == wid for w in reg["workspaces"]):
        raise ValueError(f"ja existe workspace com o id {wid}")

    path = WORKSPACES_DIR / wid
    for sub in ("collections", "environments", ".secrets", "certs", "history", "cookies"):
        (path / sub).mkdir(parents=True, exist_ok=True)
    escrever_gitignore(path)

    entry = {
        "id": wid,
        "name": name,
        "color": color or COLORS[len(reg["workspaces"]) % len(COLORS)],
        "path": str(path),
        "createdAt": _now(),
        "lastOpenedAt": None,
    }
    reg["workspaces"].append(entry)
    if reg.get("active") is None:
        reg["active"] = wid
    _write_registry(reg)

    tree_path = path / "tree.json"
    if not tree_path.exists():
        write_tree(wid, {"schemaVersion": 1, "environments": [], "collections": []})
    return entry


def escrever_gitignore(path: Path) -> bool:
    """Cria o .gitignore do workspace se ele ainda nao existir."""
    alvo = Path(path) / ".gitignore"
    if alvo.exists():
        return False
    alvo.write_text(GITIGNORE, encoding="utf-8")
    return True


def get_workspace(wid: str) -> dict:
    reg = _read_registry()
    for w in reg["workspaces"]:
        if w["id"] != wid:
            continue
        # O registro guarda caminho absoluto. Se a pasta de dados mudou de lugar, como
        # aconteceu na troca de DBX-MAN pra DBX-Wire, o caminho antigo aponta pro vazio
        # e o app leria um workspace em branco. Conserta na hora e grava de volta.
        caminho = Path(w.get("path", ""))
        esperado = WORKSPACES_DIR / wid
        if not caminho.exists() and esperado.exists():
            w["path"] = str(esperado)
            _write_registry(reg)
        return w
    raise KeyError(f"workspace {wid} nao encontrado")


def rename_workspace(wid: str, nome: str) -> dict:
    """Troca so o nome de exibicao. A pasta continua com o id antigo de proposito:
    renomear pasta quebraria caminho gravado em qualquer lugar, e o id nao aparece
    na tela."""
    reg = _read_registry()
    for entrada in reg["workspaces"]:
        if entrada["id"] == wid:
            entrada["name"] = nome
            _write_registry(reg)
            return entrada
    raise KeyError(f"workspace {wid} nao encontrado")


def set_color(wid: str, cor: str) -> dict:
    reg = _read_registry()
    for entrada in reg["workspaces"]:
        if entrada["id"] == wid:
            entrada["color"] = cor
            _write_registry(reg)
            return entrada
    raise KeyError(f"workspace {wid} nao encontrado")


def delete_workspace(wid: str, apagar_arquivos: bool = False) -> dict:
    """Tira do registro. Com apagar_arquivos, move a pasta pra lixeira do DBX Wire.

    Nao apaga de vez nem com apagar_arquivos ligado. Workspace guarda meses de trabalho,
    e uma confirmacao errada nao pode ser irreversivel.
    """
    reg = _read_registry()
    alvo = None
    for entrada in list(reg["workspaces"]):
        if entrada["id"] == wid:
            alvo = entrada
            reg["workspaces"].remove(entrada)
    if alvo is None:
        raise KeyError(f"workspace {wid} nao encontrado")

    if reg.get("active") == wid:
        reg["active"] = reg["workspaces"][0]["id"] if reg["workspaces"] else None
    _write_registry(reg)

    destino = None
    if apagar_arquivos:
        origem = Path(alvo["path"])
        if origem.exists():
            lixeira = ROOT / "lixeira" / f"{wid}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            lixeira.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(origem), str(lixeira))
            destino = lixeira

    return {"entrada": alvo, "lixeira": str(destino) if destino else None}


def duplicate_workspace(wid: str, nome: str) -> dict:
    """Copia o workspace inteiro, menos o cofre e o historico.

    Cofre fora porque a copia e feita pra compartilhar ou pra testar, e segredo nao se
    duplica sem alguem pedir. Historico fora porque e do original, nao da copia.
    """
    origem = get_workspace(wid)
    novo = create_workspace(nome)
    destino = Path(novo["path"])

    for sub in ("collections", "environments"):
        alvo = Path(origem["path"]) / sub
        if alvo.exists():
            shutil.copytree(alvo, destino / sub, dirs_exist_ok=True)
    for arquivo in ("settings.yaml", "globals.yaml"):
        alvo = Path(origem["path"]) / arquivo
        if alvo.exists():
            shutil.copy2(alvo, destino / arquivo)

    return novo


def set_active(wid: str) -> None:
    reg = _read_registry()
    get_workspace(wid)
    reg["active"] = wid
    for w in reg["workspaces"]:
        if w["id"] == wid:
            w["lastOpenedAt"] = _now()
    _write_registry(reg)


def tree_path(wid: str) -> Path:
    """Compatibilidade: o caminho do arquivo antigo, so pra migracao e backup."""
    return Path(get_workspace(wid)["path"]) / "tree.json"


def _migrar_do_json(raiz: Path) -> dict | None:
    """Le o tree.json uma unica vez, grava em YAML e guarda o original como backup."""
    antigo = raiz / "tree.json"
    if not antigo.exists():
        return None
    try:
        tree = json.loads(antigo.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    storage.gravar_workspace(raiz, tree)
    shutil.move(str(antigo), str(raiz / "tree.json.migrado"))
    return tree


def cofre(wid: str) -> Vault:
    return Vault(Path(get_workspace(wid)["path"]))


def read_tree(wid: str) -> dict:
    raiz = Path(get_workspace(wid)["path"])
    if not (raiz / "settings.yaml").exists():
        _migrar_do_json(raiz)

    tree = storage.ler_workspace(raiz)
    _recolher_segredos_soltos(raiz, tree)
    return tree


def _recolher_segredos_soltos(raiz: Path, tree: dict) -> int:
    """Tira do arquivo versionado qualquer segredo que ainda esteja em texto puro.

    Vale pra quem ja tinha workspace antes do cofre existir. Roda uma vez: acha valor
    secreto no YAML, manda pro cofre e regrava o arquivo sem ele.
    """
    soltos = 0
    for env in tree.get("environments") or []:
        for item in env.get("values") or []:
            if item.get("secret") and item.get("value"):
                soltos += 1
    if soltos:
        storage.gravar_workspace(raiz, tree)
    return soltos


def assinatura(wid: str) -> dict:
    return storage.assinatura(Path(get_workspace(wid)["path"]))


def write_tree(wid: str, tree: dict, anterior: dict | None = None) -> dict:
    return storage.gravar_workspace(Path(get_workspace(wid)["path"]), tree, anterior)

def new_id(prefix: str = "id") -> str:
    """Id curto e estavel para item de arvore."""
    return f"{prefix}-{secrets.token_hex(4)}"
