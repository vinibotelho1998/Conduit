"""Autenticacao: heranca, os tipos e o cache de token do OAuth2.

Heranca. O request nasce com `inherit`, entao ele usa o que a pasta mais proxima
define, e se a pasta tambem herda, sobe pra collection. E o desenho do Postman e do
Insomnia, e existe porque credencial quase sempre e da API inteira, nao de um endpoint.

Token do OAuth2 vive no cofre, nunca em arquivo versionado, e e reaproveitado ate perto
de expirar. Sem cache, cada envio faria duas chamadas de rede e queimaria o rate limit
do provedor de identidade.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import dataclass, field

import httpx

from .vars import Resolved, resolve

TIPOS = {
    "inherit": "Herdar",
    "none": "Sem auth",
    "bearer": "Bearer token",
    "basic": "Basic",
    "apikey": "API key",
    "oauth2": "OAuth2 client credentials",
}

# margem antes de expirar, pra nao mandar request com token vencendo no caminho
FOLGA_SEGUNDOS = 30


@dataclass
class AuthAplicada:
    tipo: str = "none"
    origem: str = ""                       # de quem herdou, pra mostrar na tela
    headers: dict[str, str] = field(default_factory=dict)
    params: list[tuple[str, str]] = field(default_factory=list)
    secrets: list[tuple[str, str]] = field(default_factory=list)
    erro: str | None = None
    detalhe: str = ""


def efetiva(node: dict, ancestry: list[dict] | None) -> tuple[dict, str]:
    """Devolve a config de auth que vale pro request e de onde ela veio."""
    propria = node.get("auth") or {}
    if propria.get("type") and propria["type"] != "inherit":
        return propria, "deste request"

    for ancestral in reversed(ancestry or []):
        config = ancestral.get("auth") or {}
        if config.get("type") and config["type"] != "inherit":
            rotulo = "pasta" if ancestral.get("type") == "folder" else "collection"
            return config, f"{rotulo} {ancestral.get('name')}"

    return {"type": "none"}, "nenhum"


def _tomar(texto: str, variaveis: dict, ledger: list) -> str:
    resultado: Resolved = resolve(texto or "", variaveis)
    ledger.extend(resultado.secrets)
    return resultado.text


def aplicar(config: dict, variaveis: dict, cofre=None) -> AuthAplicada:
    """Monta header e query da auth escolhida. Nao toca no request, so devolve o que sai."""
    tipo = (config or {}).get("type") or "none"
    saida = AuthAplicada(tipo=tipo)
    ledger: list = []

    if tipo in ("none", "inherit"):
        return saida

    # O valor final da credencial sempre entra no ledger, e nao so a variavel que a
    # originou. Sem isso o Basic vazava: base64 de usuario e senha nao contem o texto
    # do segredo, entao o redator do historico nao tinha o que trocar.
    if tipo == "bearer":
        token = _tomar(config.get("token"), variaveis, ledger)
        if token:
            saida.headers["Authorization"] = f"Bearer {token}"
            saida.detalhe = "Authorization: Bearer"
            ledger.append(("auth.bearer", token))
        else:
            saida.erro = "bearer sem token"

    elif tipo == "basic":
        usuario = _tomar(config.get("username"), variaveis, ledger)
        senha = _tomar(config.get("password"), variaveis, ledger)
        par = f"{usuario}:{senha}".encode("utf-8")
        cifrado = base64.b64encode(par).decode("ascii")
        saida.headers["Authorization"] = "Basic " + cifrado
        saida.detalhe = f"Authorization: Basic, usuario {usuario or 'vazio'}"
        ledger.append(("auth.basic", cifrado))

    elif tipo == "apikey":
        chave = _tomar(config.get("key"), variaveis, ledger)
        valor = _tomar(config.get("value"), variaveis, ledger)
        if not chave:
            saida.erro = "api key sem nome"
        elif (config.get("in") or "header") == "query":
            saida.params.append((chave, valor))
            saida.detalhe = f"query {chave}"
            ledger.append(("auth.apikey", valor))
        else:
            saida.headers[chave] = valor
            saida.detalhe = f"header {chave}"
            ledger.append(("auth.apikey", valor))

    elif tipo == "oauth2":
        token, erro, detalhe = token_oauth2(config, variaveis, ledger, cofre)
        if erro:
            saida.erro = erro
        else:
            prefixo = config.get("prefix") or "Bearer"
            saida.headers["Authorization"] = f"{prefixo} {token}"
            saida.detalhe = detalhe
            ledger.append(("auth.oauth2", token))

    saida.secrets.extend(ledger)
    return saida


def _assinatura(config: dict, url: str, client_id: str, escopo: str) -> str:
    bruto = json.dumps([url, client_id, escopo], sort_keys=True)
    return "oauth:" + hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:24]


def token_oauth2(config: dict, variaveis: dict, ledger: list, cofre=None) -> tuple[str, str | None, str]:
    url = _tomar(config.get("tokenUrl"), variaveis, ledger)
    client_id = _tomar(config.get("clientId"), variaveis, ledger)
    client_secret = _tomar(config.get("clientSecret"), variaveis, ledger)
    escopo = _tomar(config.get("scope"), variaveis, ledger)

    if not url or not client_id:
        return "", "OAuth2 precisa de tokenUrl e clientId", ""

    chave = _assinatura(config, url, client_id, escopo)

    if cofre is not None:
        guardado = cofre.get(chave)
        if guardado:
            try:
                dados = json.loads(guardado)
                if dados.get("expira", 0) > time.time() + FOLGA_SEGUNDOS:
                    faltam = int(dados["expira"] - time.time())
                    return dados["token"], None, f"OAuth2 do cache, expira em {faltam}s"
            except (json.JSONDecodeError, KeyError):
                pass

    corpo = {"grant_type": "client_credentials", "client_id": client_id}
    if client_secret:
        corpo["client_secret"] = client_secret
    if escopo:
        corpo["scope"] = escopo
    if config.get("audience"):
        corpo["audience"] = _tomar(config.get("audience"), variaveis, ledger)

    try:
        with httpx.Client(timeout=30, follow_redirects=True) as cliente:
            resposta = cliente.post(url, data=corpo)
    except httpx.HTTPError as exc:
        return "", f"falha ao pegar o token: {exc}", ""

    if resposta.status_code >= 400:
        return "", f"provedor devolveu {resposta.status_code}: {resposta.text[:200]}", ""

    try:
        dados = resposta.json()
    except ValueError:
        return "", "resposta do token nao e JSON", ""

    token = dados.get("access_token")
    if not token:
        return "", "resposta do token nao trouxe access_token", ""

    vida = int(dados.get("expires_in") or 3600)
    if cofre is not None:
        try:
            cofre.set(chave, json.dumps({"token": token, "expira": time.time() + vida}))
        except Exception:  # noqa: BLE001
            pass

    return token, None, f"OAuth2 novo, vale {vida}s"


def limpar_cache(cofre) -> int:
    """Joga fora todo token guardado. Util quando a credencial muda."""
    return cofre.remover_prefixo("oauth:") if cofre is not None else 0
