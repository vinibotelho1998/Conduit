"""Registro e acesso aos workspaces do Conduit.

Cada workspace e uma pasta isolada com suas proprias collections, environments,
cofre e historico. Nada vaza de um workspace pro outro.

O conteudo vive em arquivos YAML, um por request, conforme o storage.py. O tree.json
antigo ainda e lido uma unica vez, pra migrar quem ja tinha dados, e vira backup.
"""

from __future__ import annotations

import errno
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
    """Pasta de dados. Ja mudou de nome duas vezes junto com o programa.

    Se alguma das antigas existir e a nova nao, move de uma vez. Deixar as duas
    seria pior: o app leria de uma e o usuario procuraria na outra.
    """
    definido = os.environ.get("CONDUIT_HOME")
    if definido:
        return Path(definido)

    nova = Path.home() / "Conduit"
    if not nova.exists():
        for nome in ("Dbx-Wire", "DBX-MAN"):
            antiga = Path.home() / nome
            if antiga.exists():
                try:
                    antiga.rename(nova)
                except OSError:
                    return antiga
                break
    return nova


ROOT = _raiz_de_dados()
WORKSPACES_DIR = ROOT / "workspaces"
REGISTRY = ROOT / "workspaces.json"

# Seis cores pra faixa que identifica o workspace na barra de cima. Cada uma passa de
# 3 contra o fundo dos dois temas, senao a faixa some no claro.
COLORS = ["#8e8e95", "#3ecf8e", "#ff9a3c", "#5aa9e6", "#ff5f70", "#2dd4bf"]

# O que nunca pode ir pro git de um workspace compartilhado: o environment versionado
# carrega o contrato, os nomes das variaveis, e o valor secreto fica no cofre local.
GITIGNORE = """# gerado pelo Conduit
.secrets/
certs/
history/
cookies/
ai-log/
.conduit/
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
    (ROOT / ".conduit").mkdir(exist_ok=True)
    if not REGISTRY.exists():
        _write_registry({"schemaVersion": 1, "active": None, "workspaces": []})


# Cores que ja foram usadas na faixa do workspace e sairam da lista, apontando pra
# substituta mais proxima. Sem isso, um workspace criado numa versao antiga fica com uma
# cor que nao existe mais no seletor: a lista abre sem nada marcado, e a faixa continua
# num tom que nao pertence mais ao tema.
CORES_APOSENTADAS = {
    "#a78bfa": "#8e8e95",
    "#c084fc": "#8e8e95",
    "#f472b6": "#5aa9e6",
    "#4da3ff": "#5aa9e6",
    "#49cc90": "#3ecf8e",
    "#fca130": "#ff9a3c",
    "#f93e3e": "#ff5f70",
    "#50e3c2": "#2dd4bf",
}


def _read_registry() -> dict:
    ensure_root()
    dados = json.loads(REGISTRY.read_text(encoding="utf-8"))

    trocou = False
    for entrada in dados.get("workspaces") or []:
        nova = CORES_APOSENTADAS.get((entrada.get("color") or "").lower())
        if nova:
            entrada["color"] = nova
            trocou = True
    if trocou:
        _write_registry(dados)
    return dados


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

    # Pasta que ja tem workspace dentro e um que foi tirado da lista voltando, e a tela de
    # excluir promete justamente isso. Ela e adotada como esta: gravar a arvore vazia por
    # cima apagava cada request, ambiente e global que estava la.
    tree_path = path / "tree.json"
    if not tree_path.exists() and not (path / "settings.yaml").exists():
        write_tree(wid, {"schemaVersion": 1, "environments": [], "collections": []})
    return entry


def ja_existe_no_disco(wid: str) -> bool:
    """Se a pasta desse id ja guarda um workspace, mesmo fora do registro."""
    pasta = WORKSPACES_DIR / wid
    return (pasta / "settings.yaml").exists() or (pasta / "tree.json").exists()


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
        # aconteceu nas trocas de nome da pasta, o caminho antigo aponta pro vazio
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
    """Tira do registro. Com apagar_arquivos, move a pasta pra lixeira do Conduit.

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

    # A pasta sai antes do registro. Na ordem contraria, mover que falhava deixava o
    # workspace fora da lista com a pasta ainda no lugar, e um workspace novo com o
    # mesmo nome nascia em cima dos arquivos dele.
    destino = None
    if apagar_arquivos:
        origem = Path(alvo["path"])
        if origem.exists():
            lixeira = ROOT / "lixeira" / f"{wid}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            lixeira.parent.mkdir(parents=True, exist_ok=True)
            _mover_inteiro(origem, lixeira)
            destino = lixeira

    if reg.get("active") == wid:
        reg["active"] = reg["workspaces"][0]["id"] if reg["workspaces"] else None
    _write_registry(reg)

    return {"entrada": alvo, "lixeira": str(destino) if destino else None}


def _mover_inteiro(origem: Path, destino: Path) -> None:
    """Move a pasta de uma vez, ou nao move nada.

    shutil.move cai pra copiar e apagar quando o rename falha, e no Windows o rename
    falha justo quando tem arquivo aberto la dentro, como o indice do historico. O apagar
    parava no primeiro arquivo preso e a pasta ficava metade na lixeira, metade no lugar.
    Copiar e apagar so fica pra quando a lixeira esta em outro disco.
    """
    try:
        origem.rename(destino)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        shutil.move(str(origem), str(destino))


def duplicate_workspace(wid: str, nome: str) -> dict:
    """Copia o workspace inteiro, menos o cofre e o historico.

    Cofre fora porque a copia e feita pra compartilhar ou pra testar, e segredo nao se
    duplica sem alguem pedir. Historico fora porque e do original, nao da copia.
    """
    origem = get_workspace(wid)
    registrados = {w["id"] for w in _read_registry()["workspaces"]}
    if slug(nome) not in registrados and ja_existe_no_disco(slug(nome)):
        # create_workspace adota a pasta de um workspace tirado da lista, e a copia caia
        # por cima do que estava la: collections dos dois misturadas na mesma pasta
        raise ValueError(
            f"ja existe uma pasta de workspace chamada {slug(nome)}, de um que saiu da "
            "lista. Crie com esse nome pra trazer ele de volta, ou escolha outro nome"
        )
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


PREFERENCES = ROOT / "preferencias.json"
PREFERENCES_PADRAO = {"tema": "escuro", "densidade": "confortavel"}


def read_preferences() -> dict:
    """Tema e densidade, guardados fora de qualquer workspace: sao do app, nao do
    projeto. Sem arquivo ainda, volta o padrao sem criar nada no disco."""
    if not PREFERENCES.exists():
        return dict(PREFERENCES_PADRAO)
    try:
        dados = json.loads(PREFERENCES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(PREFERENCES_PADRAO)
    saida = dict(PREFERENCES_PADRAO)
    saida.update({k: v for k, v in dados.items() if k in PREFERENCES_PADRAO})
    return saida


def write_preferences(**mudancas) -> dict:
    atuais = read_preferences()
    atuais.update({k: v for k, v in mudancas.items() if k in PREFERENCES_PADRAO})
    ROOT.mkdir(parents=True, exist_ok=True)
    tmp = PREFERENCES.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(atuais, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(PREFERENCES)
    return atuais
