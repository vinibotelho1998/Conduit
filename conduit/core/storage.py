"""Um arquivo por item no disco, em YAML legivel.

Formato:

    workspace/
      settings.yaml            certificados, servidores SFTP e versao do formato
      .conduit/estado.json     ambiente ativo, ordem e pasta aberta, de cada pessoa
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

import json
import re
import unicodedata
from pathlib import Path

import yaml

from .vault import Vault, chave_de

SCHEMA_VERSION = 1

# O que e de cada pessoa, e nao do projeto: ambiente ativo, ordem da arvore e pasta
# aberta. Mora em .conduit, que fica fora do git. No settings.yaml e no _folder.yaml,
# cada clique virava diff, e o colega que puxava o repo depois de voce trocar pra prd
# abria o app ja em prd sem ter escolhido.
ESTADO_LOCAL = Path(".conduit") / "estado.json"

# Dono das globais no cofre. Ambiente, collection e pasta usam o proprio id.
DONO_GLOBAIS = "__globais__"

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


def _legivel(texto: str) -> bool:
    """Se o texto e um YAML que o app sabe ler, ou seja, um mapa. Vazio conta como lido."""
    if not texto.strip():
        return True
    try:
        return isinstance(yaml.safe_load(texto), dict)
    except yaml.YAMLError:
        return False


def _texto_do_disco(caminho: Path) -> str | None:
    try:
        return caminho.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None


def _guardar_ilegivel(raiz: Path, caminho: Path, resumo: dict | None) -> None:
    """Copia pra .conduit/conflitos o arquivo que o app nao conseguiu ler.

    Arquivo que nao le e arquivo que nao entrou na arvore. Um _collection.yaml com erro
    de digitacao, ou com marca de conflito do git, era regravado no salvar seguinte com
    o que o app tinha na memoria, e as variaveis e a auth de dentro dele iam embora sem
    copia nenhuma.
    """
    try:
        _guardar_conflito(raiz, caminho)
    except OSError:
        return
    if resumo is not None:
        relativo = caminho.relative_to(raiz).as_posix()
        if relativo not in resumo["conflitos"]:
            resumo["conflitos"].append(relativo)


def _escrever(caminho: Path, dados: dict, raiz: Path | None = None, resumo: dict | None = None) -> bool:
    """Grava so se o conteudo mudou. Devolve True quando escreveu.

    Com `raiz`, o que estava no disco e nao se le como YAML vai pra .conduit/conflitos
    antes de ser sobrescrito.
    """
    texto = yaml.dump(
        dados, Dumper=OrdenadoDumper, sort_keys=False, allow_unicode=True, width=100
    )
    if caminho.exists():
        # lido como texto, e nao como bytes, pra comparar do mesmo jeito que sempre se
        # comparou: o arquivo foi gravado em modo texto, com a quebra de linha do Windows
        atual = _texto_do_disco(caminho)
        if atual == texto:
            return False
        if raiz is not None and (atual is None or not _legivel(atual)):
            _guardar_ilegivel(raiz, caminho, resumo)
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

    destino = raiz / ".conduit" / "conflitos" / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    # o caminho relativo vem junto: so pelo nome, dois _folder.yaml guardados no mesmo
    # segundo viravam um arquivo so, e a copia do primeiro se perdia
    alvo = destino / caminho.relative_to(raiz)
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_bytes(caminho.read_bytes())
    return alvo


def _ler(caminho: Path) -> dict:
    # UnicodeDecodeError e ValueError: arquivo salvo por fora em ANSI derrubava a leitura
    # do workspace inteiro, e o app nem abria. Lista ou texto solto no lugar do mapa, idem.
    try:
        dados = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError):
        return {}
    return dados if isinstance(dados, dict) else {}


def _texto(valor) -> str:
    """O YAML le `8080` como numero e `true` como booleano, e o app so conhece texto.

    Valor tipado assim so aparece quando alguem edita o arquivo na mao, e derrubava o
    envio com TypeError na hora de trocar a variavel, alem de sumir da grade.
    """
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "true" if valor else "false"
    return valor if isinstance(valor, str) else str(valor)


def _ordem(valor) -> int:
    """O `seq` do arquivo. Texto misturado com numero fazia o sort estourar TypeError."""
    try:
        return int(valor)
    except (TypeError, ValueError):
        return 999


def _mapas(lista) -> list:
    """Lista de mapas, como a de certificados e a de servidores SFTP do settings.yaml.

    Escrita na mao, ela pode chegar como texto solto ou com item que nao e mapa, e o
    primeiro .get em cima disso derrubava a abertura do workspace inteiro.
    """
    return [item for item in lista if isinstance(item, dict)] if isinstance(lista, list) else []


def _pares(lista) -> list:
    """Linhas de chave e valor, com o que o YAML tipou de volta em texto."""
    saida = []
    for item in lista if isinstance(lista, list) else []:
        if not isinstance(item, dict):
            continue
        for campo in ("key", "value"):
            # nulo fica nulo: quem le ja trata como vazio, e trocar faria o proximo
            # salvar reescrever um arquivo que ninguem mexeu
            if item.get(campo) is not None and not isinstance(item[campo], str):
                item[campo] = _texto(item[campo])
        saida.append(item)
    return saida


def _preencher_do_cofre(valores: list, dono: str, cofre) -> list:
    """Traz do cofre o valor de cada variavel secreta que o arquivo guardou vazia."""
    for item in valores:
        if item.get("secret") and not item.get("value"):
            item["value"] = cofre.get(chave_de(dono, item.get("key") or ""))
    return valores


def _separar_segredos(valores, dono: str, segredos: dict) -> list:
    """Copia das linhas pro arquivo, com o valor secreto tirado e posto em `segredos`."""
    publicos = []
    for item in valores or []:
        copia = dict(item)
        if copia.get("secret"):
            segredos[chave_de(dono, copia.get("key") or "")] = copia.get("value") or ""
            copia["value"] = ""
        publicos.append(copia)
    return publicos


def ler_workspace(raiz: str | Path, cofre: Vault | None = None) -> dict:
    raiz = Path(raiz)
    cofre = cofre if cofre is not None else Vault(raiz)
    settings = _ler(raiz / "settings.yaml")

    tree = {
        "schemaVersion": settings.get("schemaVersion", SCHEMA_VERSION),
        "activeEnv": _texto(settings.get("activeEnv")) or None,
        "sortMode": settings.get("sortMode") or "manual",
        "certificates": _mapas(settings.get("certificates")),
        "caFile": _texto(settings.get("caFile")),
        # so o contrato do servidor SFTP: host, porta e usuario. Senha e frase da chave
        # ficam no cofre, exatamente como o valor de variavel secreta.
        "sftp": _mapas(settings.get("sftp")),
        # global, collection e pasta seguem a mesma regra do ambiente: o arquivo guarda
        # o nome e a marca de secreta, e o valor secreto mora no cofre
        "globals": _preencher_do_cofre(
            _pares(_ler(raiz / "globals.yaml").get("values")), DONO_GLOBAIS, cofre
        ),
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
            env_id = _texto(dados.get("id")) or arquivo.stem
            # O arquivo versionado guarda so o contrato: nome da variavel e a marca de
            # secreta. O valor secreto vem do cofre, que fica fora do git.
            valores = _preencher_do_cofre(_pares(dados.get("values")), env_id, cofre)
            envs.append(
                {
                    "id": env_id,
                    "name": _texto(dados.get("name")) or arquivo.stem,
                    "values": valores,
                    "_seq": _ordem(dados.get("seq")),
                }
            )
        envs.sort(key=lambda e: e.pop("_seq"))
        tree["environments"] = envs

    pasta_cols = raiz / "collections"
    if pasta_cols.is_dir():
        colecoes = []
        for diretorio in sorted(p for p in pasta_cols.iterdir() if p.is_dir()):
            node = _ler_grupo(diretorio, "collection", cofre)
            if node:
                colecoes.append(node)
        colecoes.sort(key=lambda n: n.pop("_seq", 999))
        tree["collections"] = colecoes

    # Workspace gravado por versao anterior nao tem o estado local: fica valendo o que
    # esta no settings.yaml e no _folder.yaml, e o primeiro salvar ja cria o arquivo.
    estado = _ler_estado(raiz)
    if "activeEnv" in estado:
        tree["activeEnv"] = _texto(estado.get("activeEnv")) or None
    if "sortMode" in estado:
        tree["sortMode"] = _texto(estado.get("sortMode")) or "manual"
    if isinstance(estado.get("expandidos"), list):
        abertos = {str(i) for i in estado["expandidos"]}
        for node in _grupos(tree["collections"]):
            node["expanded"] = node.get("id") in abertos

    return tree


def _grupos(nos):
    for node in nos or []:
        if node.get("type") in ("collection", "folder"):
            yield node
            yield from _grupos(node.get("items"))


def _ler_estado(raiz: Path) -> dict:
    try:
        dados = json.loads((raiz / ESTADO_LOCAL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dados if isinstance(dados, dict) else {}


def _gravar_estado(raiz: Path, tree: dict) -> None:
    dados = {
        "activeEnv": tree.get("activeEnv"),
        "sortMode": tree.get("sortMode") or "manual",
        "expandidos": sorted(
            str(n.get("id")) for n in _grupos(tree.get("collections")) if n.get("expanded")
        ),
    }
    caminho = raiz / ESTADO_LOCAL
    texto = json.dumps(dados, indent=2, ensure_ascii=False)
    try:
        if caminho.exists() and caminho.read_text(encoding="utf-8") == texto:
            return
        caminho.parent.mkdir(parents=True, exist_ok=True)
        temporario = caminho.with_name(caminho.name + ".tmp")
        temporario.write_text(texto, encoding="utf-8")
        temporario.replace(caminho)
    except OSError:
        # e conforto de quem usa, e nao dado do projeto: sem ele o app abre como antes
        pass


def _ler_grupo(diretorio: Path, tipo: str, cofre=None) -> dict | None:
    arquivo = diretorio / ("_collection.yaml" if tipo == "collection" else "_folder.yaml")
    dados = _ler(arquivo) if arquivo.exists() else {}
    if not dados and not any(diretorio.iterdir()):
        return None

    grupo_id = _texto(dados.get("id")) or diretorio.name
    variaveis = _pares(dados.get("variables"))
    if cofre is not None:
        _preencher_do_cofre(variaveis, grupo_id, cofre)
    node = {
        "id": grupo_id,
        "type": tipo,
        "name": _texto(dados.get("name")) or diretorio.name,
        "expanded": bool(dados.get("expanded")),
        "variables": variaveis,
        "items": [],
        "_seq": _ordem(dados.get("seq")),
    }
    for extra in ("auth", "origin"):
        if dados.get(extra) and isinstance(dados[extra], dict):
            node[extra] = dados[extra]

    filhos = []
    for caminho in sorted(diretorio.iterdir()):
        if caminho.is_dir():
            filho = _ler_grupo(caminho, "folder", cofre)
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
    corpo = dados.get("body")
    if isinstance(corpo, dict):
        corpo = dict(corpo)
        for campo in ("mode", "raw"):
            if corpo.get(campo) is not None and not isinstance(corpo[campo], str):
                corpo[campo] = _texto(corpo[campo])
    elif corpo:
        corpo = {"mode": "raw", "raw": _texto(corpo)}
    else:
        corpo = {"mode": "none", "raw": ""}
    node = {
        "id": _texto(dados.get("id")) or caminho.stem,
        "type": "request",
        "name": _texto(dados.get("name")) or caminho.stem,
        "method": _texto(dados.get("method")) or "GET",
        "url": _texto(dados.get("url")),
        "params": _pares(dados.get("params")),
        "headers": _pares(dados.get("headers")),
        "body": corpo,
        "docs": _texto(dados.get("docs")),
        "_seq": _ordem(dados.get("seq")),
    }
    # Cada extra so entra com o tipo que o app sabe ler. Uma auth escrita como texto na
    # mao derrubava a abertura da aba, porque a heranca faz auth.get em cima dela.
    for extra, tipo in (("favorite", object), ("auth", dict), ("settings", dict),
                        ("examples", list), ("origin", dict)):
        if dados.get(extra) and isinstance(dados[extra], tipo):
            node[extra] = dados[extra]
    if "examples" in node:
        node["examples"] = [e for e in node["examples"] if isinstance(e, dict)]
    return node


def gravar_workspace(
    raiz: str | Path, tree: dict, anterior: dict | None = None, cofre: Vault | None = None
) -> dict:
    """Grava a arvore inteira e apaga o que sobrou. Devolve um resumo do que mexeu.

    Com `anterior`, que e a assinatura de quando o workspace foi lido, qualquer arquivo
    que tenha mudado por fora e copiado pra .conduit/conflitos antes de ser sobrescrito.
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

    # ambiente ativo e ordem da arvore sao de quem usa, e vao pro estado local
    _gravar_estado(raiz, tree)
    caminho = raiz / "settings.yaml"
    if _escrever(
        caminho,
        {
            "schemaVersion": SCHEMA_VERSION,
            "certificates": tree.get("certificates") or [],
            "caFile": tree.get("caFile") or "",
            "sftp": tree.get("sftp") or [],
        },
        raiz,
        resumo,
    ):
        resumo["escritos"] += 1
    vivos.add(caminho)

    segredos: dict[str, str] = {}
    globais = _separar_segredos(tree.get("globals"), DONO_GLOBAIS, segredos)
    globais_tem_segredo = bool(segredos)
    _segredos_dos_grupos(tree.get("collections"), segredos)

    pasta_envs = raiz / "environments"
    pasta_envs.mkdir(exist_ok=True)
    usados: set[str] = set()
    arquivos_env: list[tuple[Path, dict]] = []

    for indice, env in enumerate(tree.get("environments") or []):
        nome = slug(env.get("name") or env.get("id") or "ambiente", usados)
        caminho = pasta_envs / f"{nome}.yaml"
        env_id = env.get("id") or nome

        # Separa o valor secreto antes de escrever. O que vai pro arquivo e o contrato,
        # o valor vai pro cofre cifrado.
        publicos = _separar_segredos(env.get("values"), env_id, segredos)

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
        arquivos_env.append((caminho, dados))

    # O cofre vai antes dos arquivos. Com o cofre falhando, regravar o ambiente com o
    # valor secreto em branco apagava o unico lugar onde ele ainda existia: e o caso de
    # quem ainda tinha segredo em texto puro no YAML, recolhido na primeira leitura.
    cofre_ok = True
    if segredos:
        try:
            resumo["segredos"] = cofre.set_muitos(segredos)
        except Exception as exc:  # noqa: BLE001
            resumo["erro_cofre"] = f"{type(exc).__name__}: {exc}"
            cofre_ok = False

    if cofre_ok:
        for caminho, dados in arquivos_env:
            if _escrever(caminho, dados, raiz, resumo):
                resumo["escritos"] += 1
            vivos.add(caminho)
    else:
        vivos.update(pasta_envs.glob("*.yaml"))

    caminho = raiz / "globals.yaml"
    if cofre_ok or not globais_tem_segredo or not caminho.exists():
        if _escrever(caminho, {"schemaVersion": SCHEMA_VERSION, "values": globais}, raiz, resumo):
            resumo["escritos"] += 1
    vivos.add(caminho)

    pasta_cols = raiz / "collections"
    pasta_cols.mkdir(exist_ok=True)
    usados = set()
    diretorios_vivos: set[Path] = set()
    for indice, colecao in enumerate(tree.get("collections") or []):
        destino = pasta_cols / slug(colecao.get("name") or "collection", usados)
        _gravar_grupo(
            destino, colecao, indice, "collection", vivos, diretorios_vivos, resumo, raiz, cofre_ok
        )

    # Limpeza do que nao pertence mais a arvore. So mexe dentro de collections e de
    # environments: settings.yaml, globals.yaml e qualquer outra coisa na raiz do
    # workspace ficam de fora por seguranca.
    for caminho in sorted(raiz.rglob("*.yaml"), reverse=True):
        if caminho in vivos:
            continue
        dentro_de_collections = pasta_cols in caminho.parents
        dentro_de_environments = caminho.parent == pasta_envs
        if dentro_de_collections or dentro_de_environments:
            # O que nao se le nunca entrou na arvore, entao nao foi voce que tirou de la.
            # Fica onde esta, esperando o conserto: e o estado normal de quem edita o YAML
            # por fora com salvamento automatico, ou de um merge do git com conflito.
            texto = _texto_do_disco(caminho)
            if texto is None or not _legivel(texto):
                continue
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


def _segredos_dos_grupos(nos, segredos: dict) -> None:
    """Junta o valor secreto das variaveis de collection e pasta, pra ir pro cofre."""
    for node in nos or []:
        if node.get("type") == "request":
            continue
        _separar_segredos(node.get("variables"), node.get("id") or "", segredos)
        _segredos_dos_grupos(node.get("items"), segredos)


def _gravar_grupo(
    destino: Path, node: dict, seq: int, tipo: str, vivos, diretorios, resumo,
    raiz: Path | None = None, cofre_ok: bool = True,
) -> None:
    destino.mkdir(parents=True, exist_ok=True)
    diretorios.add(destino)

    arquivo = destino / ("_collection.yaml" if tipo == "collection" else "_folder.yaml")
    descartados: dict[str, str] = {}
    variaveis = _separar_segredos(node.get("variables"), node.get("id") or "", descartados)
    dados = _ordenar(
        {
            "schemaVersion": SCHEMA_VERSION,
            "id": node.get("id"),
            "seq": seq,
            "name": node.get("name"),
            # pasta aberta ou fechada e do estado local, ver ESTADO_LOCAL
            "variables": variaveis,
            "auth": node.get("auth") or None,
            "origin": node.get("origin"),
        },
        ORDEM_GRUPO,
    )
    # com o cofre recusando, o arquivo que ainda tem o segredo em claro fica como esta,
    # igual ao ambiente: ele e o unico lugar onde o valor existe fora da memoria
    if cofre_ok or not descartados or not arquivo.exists():
        if _escrever(arquivo, dados, raiz, resumo):
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
            if _escrever(caminho, corpo, raiz, resumo):
                resumo["escritos"] += 1
            vivos.add(caminho)
        else:
            _gravar_grupo(
                destino / nome, filho, indice, "folder", vivos, diretorios, resumo, raiz, cofre_ok
            )
