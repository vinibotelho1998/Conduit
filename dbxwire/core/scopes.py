"""Escopos de variavel e a resolucao efetiva de cada nome.

Cinco escopos, do mais geral pro mais especifico:

    globais  <  collection  <  pasta  <  ambiente  <  execucao

Por que ambiente ganha de pasta, diferente do rascunho original do plano: ambiente e o
botao que voce usa pra trocar entre dev, hml e prd. Se uma pasta pudesse sobrepor o
ambiente, trocar pra prd nao trocaria tudo, e essa e exatamente a classe de erro que faz
alguem bater em producao achando que esta em homologacao. Pasta serve pra valor comum de
um grupo de requests, nao pra mandar no ambiente.

Execucao e o escopo volatil, do reenvio e do que a IA setar mais pra frente. Nao vai
pro disco.
"""

from __future__ import annotations

from dataclasses import dataclass

SCOPES = ("globais", "collection", "pasta", "ambiente", "execucao")

SCOPE_LABEL = {
    "globais": "global",
    "collection": "collection",
    "pasta": "pasta",
    "ambiente": "ambiente",
    "execucao": "execucao",
}


@dataclass
class VarInfo:
    name: str
    value: str
    secret: bool = False
    scope: str = "ambiente"
    origin: str = ""          # nome da collection, da pasta ou do ambiente
    shadowed: list = None     # onde mais o nome existe e perdeu a disputa

    def masked(self) -> str:
        if not self.secret:
            return self.value
        if not self.value:
            return ""
        if len(self.value) <= 8:
            return "***"
        return f"{self.value[:3]}***{self.value[-2:]}"


def _collect(pairs, scope: str, origin: str, into: dict, order: list) -> None:
    for item in pairs or []:
        key = (item.get("key") or "").strip()
        if not key or item.get("enabled") is False:
            continue
        info = VarInfo(
            name=key,
            value=item.get("value") or "",
            secret=bool(item.get("secret")),
            scope=scope,
            origin=origin,
        )
        anterior = into.get(key)
        if anterior is not None:
            order.append((key, anterior))
        into[key] = info


def active_env(tree: dict) -> dict | None:
    for env in tree.get("environments") or []:
        if env.get("id") == tree.get("activeEnv"):
            return env
    return None


def build(tree: dict, ancestry: list[dict] | None = None, runtime: dict | None = None) -> dict[str, VarInfo]:
    """Mapa efetivo de variaveis para um request.

    ancestry e a linhagem do request, da collection ate a pasta mais proxima. Sem ela
    o mapa sai so com globais, ambiente e execucao, que e o suficiente pra tela de
    variaveis e pra qualquer request sem contexto.
    """
    resultado: dict[str, VarInfo] = {}
    sombras: list = []

    _collect(tree.get("globals"), "globais", "workspace", resultado, sombras)

    for node in ancestry or []:
        tipo = node.get("type")
        if tipo == "collection":
            _collect(node.get("variables"), "collection", node.get("name") or "", resultado, sombras)
        elif tipo == "folder":
            _collect(node.get("variables"), "pasta", node.get("name") or "", resultado, sombras)

    env = active_env(tree)
    if env:
        _collect(env.get("values"), "ambiente", env.get("name") or "", resultado, sombras)

    if runtime:
        pares = [{"key": k, "value": v} for k, v in runtime.items()]
        _collect(pares, "execucao", "execucao atual", resultado, sombras)

    for nome, perdedor in sombras:
        vencedor = resultado.get(nome)
        if vencedor is None:
            continue
        if vencedor.shadowed is None:
            vencedor.shadowed = []
        vencedor.shadowed.append(perdedor)

    return resultado


def as_plain(mapa: dict[str, VarInfo]) -> dict[str, dict]:
    """Formato que o resolvedor e o motor consomem."""
    return {nome: {"value": info.value, "secret": info.secret} for nome, info in mapa.items()}
