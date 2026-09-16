"""Montagem e envio do request. Unico ponto do sistema que usa o valor real do segredo."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

from . import auth as authmod, certs
from .vars import Resolved, resolve


# Segundos pra abrir a conexao. So isso tem teto: depois de conectado o app
# espera a resposta o tempo que ela levar.
CONEXAO = 30.0


@dataclass
class Prepared:
    method: str = "GET"
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    body: str | None = None
    missing: list[str] = field(default_factory=list)
    secrets: list[tuple[str, str]] = field(default_factory=list)
    # Zero quer dizer sem limite de leitura. Um minuto derrubava chamada legitima:
    # api de orgao publico costuma passar disso e a resposta vinha depois.
    timeout: float = 0.0
    verify_tls: bool = True
    ca_arquivo: str = ""
    follow_redirects: bool = True
    auth_tipo: str = "none"
    auth_origem: str = ""
    auth_detalhe: str = ""
    auth_erro: str | None = None
    certificado: object = None
    cert_senha: str = ""
    cookies: dict = field(default_factory=dict)


def prepare(
    request: dict,
    variables: dict[str, dict],
    ancestry: list | None = None,
    tree: dict | None = None,
    cofre=None,
) -> Prepared:
    out = Prepared()
    missing: list[str] = []
    secrets: list[tuple[str, str]] = []

    def take(text: str) -> str:
        res: Resolved = resolve(text or "", variables)
        missing.extend(res.missing)
        secrets.extend(res.secrets)
        return res.text

    out.method = (request.get("method") or "GET").upper()
    url = take(request.get("url") or "")

    params = []
    for item in request.get("params") or []:
        if item.get("enabled") is False or not item.get("key"):
            continue
        params.append((item["key"], take(item.get("value") or "")))

    # A lista de params e a fonte da query. A url e so a outra vista do mesmo dado,
    # entao o que estiver depois do ? na url e descartado quando ha params. Sem isso
    # a query sairia duplicada assim que a interface sincroniza os dois lados.
    if params:
        base, _, _ = url.partition("?")
        out.url = f"{base}?{httpx.QueryParams(params)}"
    else:
        out.url = url

    for item in request.get("headers") or []:
        if item.get("enabled") is False or not item.get("key"):
            continue
        out.headers[item["key"]] = take(item.get("value") or "")

    body = request.get("body") or {}
    mode = body.get("mode") or "none"
    if mode != "none" and body.get("raw"):
        out.body = take(body["raw"])
        lowered = {k.lower() for k in out.headers}
        if mode == "json" and "content-type" not in lowered:
            out.headers["Content-Type"] = "application/json"
        if mode == "form" and "content-type" not in lowered:
            out.headers["Content-Type"] = "application/x-www-form-urlencoded"

    settings = request.get("settings") or {}
    out.timeout = float(settings.get("timeout") or 0)
    out.verify_tls = settings.get("verifyTls", True)
    out.ca_arquivo = ""
    out.follow_redirects = settings.get("followRedirects", True)

    config, origem = authmod.efetiva(request, ancestry)
    aplicada = authmod.aplicar(config, variables, cofre)
    out.auth_tipo = aplicada.tipo
    out.auth_origem = origem
    out.auth_detalhe = aplicada.detalhe
    out.auth_erro = aplicada.erro

    # header do request ganha do header da auth, senao nao daria pra sobrepor num caso
    for chave, valor in aplicada.headers.items():
        if chave.lower() not in {k.lower() for k in out.headers}:
            out.headers[chave] = valor
    if aplicada.params:
        base, _, existente = out.url.partition("?")
        query = httpx.QueryParams(existente).merge(httpx.QueryParams(aplicada.params))
        out.url = f"{base}?{query}"
    secrets.extend(aplicada.secrets)

    if tree is not None:
        cert = certs.para_url(tree, out.url)
        if cert is not None:
            out.certificado = cert
            if cofre is not None:
                out.cert_senha = cofre.get(certs.CHAVE_SENHA.format(host=cert.host))

    out.missing = list(dict.fromkeys(missing))
    out.secrets = secrets
    return out


def send(prepared: Prepared) -> dict:
    if not prepared.url.lower().startswith(("http://", "https://")):
        return {"ok": False, "error": "a url precisa comecar com http ou https", "elapsedMs": 0}

    if prepared.auth_erro:
        return {"ok": False, "error": f"auth: {prepared.auth_erro}", "elapsedMs": 0}

    verificacao = prepared.verify_tls
    temporario = None
    if prepared.certificado is None and prepared.ca_arquivo and prepared.verify_tls:
        try:
            verificacao = certs.contexto_verificacao(prepared.ca_arquivo)
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "error": f"certificado de CA: {type(exc).__name__}: {exc}",
                "elapsedMs": 0,
            }
    if prepared.certificado is not None:
        try:
            verificacao, temporario = certs.contexto_ssl(
                prepared.certificado, prepared.cert_senha, prepared.verify_tls,
                prepared.ca_arquivo,
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "error": f"certificado cliente: {type(exc).__name__}: {exc}",
                "elapsedMs": 0,
            }

    started = time.perf_counter()
    try:
        # Sem teto de leitura, mas com teto pra conectar: host morto tem que falhar
        # rapido, resposta demorada tem que ser esperada ate o fim.
        limite = (
            httpx.Timeout(prepared.timeout, connect=CONEXAO)
            if prepared.timeout
            else httpx.Timeout(None, connect=CONEXAO)
        )
        with httpx.Client(
            timeout=limite,
            verify=verificacao,
            follow_redirects=prepared.follow_redirects,
            cookies=prepared.cookies or None,
        ) as client:
            resp = client.request(
                prepared.method,
                prepared.url,
                headers=prepared.headers or None,
                content=prepared.body.encode("utf-8") if prepared.body else None,
            )
            # O cookie tem que sair do cliente, e nao da resposta. Num redirect o
            # Set-Cookie vem na resposta intermediaria, e a final nao carrega nada.
            # O cliente acumula a cadeia toda.
            # Pelo jar, e nao por dict(client.cookies): o mapping do httpx indexa
            # por nome e levanta CookieConflict quando o mesmo nome existe em dois
            # domain/path. Aqui o ultimo gravado vence.
            cookies_finais = {c.name: c.value for c in client.cookies.jar}
        elapsed = round((time.perf_counter() - started) * 1000)
        return {
            "ok": True,
            "cookies": cookies_finais,
            "status": resp.status_code,
            "reason": resp.reason_phrase,
            "headers": [[k, v] for k, v in resp.headers.items()],
            "body": resp.text,
            "content": resp.content,
            "sizeBytes": len(resp.content),
            "elapsedMs": elapsed,
            "url": str(resp.url),
        }
    except httpx.HTTPError as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "elapsedMs": round((time.perf_counter() - started) * 1000),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "elapsedMs": round((time.perf_counter() - started) * 1000),
        }
    finally:
        certs.descartar(temporario)
