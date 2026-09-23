"""Montagem e envio do request. Unico ponto do sistema que usa o valor real do segredo."""

from __future__ import annotations

import http.cookiejar
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

import httpx

from . import auth as authmod, certs
from .vars import Resolved, resolve


# Segundos pra abrir a conexao. So isso tem teto: depois de conectado o app
# espera a resposta o tempo que ela levar.
CONEXAO = 30.0

# esquema no comeco da url, do jeito que a RFC escreve: letra, depois letra, digito, + . -
_ESQUEMA = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")


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
    # token do OAuth2 que ficou pra ser pedido no envio, ver completar_auth
    oauth2_pendente: dict | None = None
    # a url veio sem http e o envio supos http://, pra tela poder avisar
    esquema_suposto: bool = False


def prepare(
    request: dict,
    variables: dict[str, dict],
    ancestry: list | None = None,
    tree: dict | None = None,
    cofre=None,
    rede: bool = True,
) -> Prepared:
    """Resolve o request inteiro. Com `rede` desligada, nada aqui vai a rede.

    A interface sempre prepara com a rede desligada: o token do OAuth2 que nao esta no
    cofre fica pendente e e pedido por `send`, que ja roda fora da thread da janela.
    """
    out = Prepared()
    missing: list[str] = []
    secrets: list[tuple[str, str]] = []

    def take(text: str) -> str:
        res: Resolved = resolve(text or "", variables)
        missing.extend(res.missing)
        secrets.extend(res.secrets)
        return res.text

    out.method = (request.get("method") or "GET").upper()
    # Endereco copiado de documento chega com fim de linha ou espaco nas pontas, e o
    # envio falhava com caractere nao imprimivel numa posicao que a tela nao mostrava.
    url = re.sub(r"[\r\n\t]", "", take(request.get("url") or "")).strip()
    # localhost:8080/api, que navegador e Postman aceitam, era recusado por nao comecar
    # com http. Com variavel ainda sem valor fica como esta: nao da pra saber o esquema.
    if url and "{{" not in url and not _ESQUEMA.match(url):
        url = "http://" + url
        out.esquema_suposto = True

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
    try:
        out.timeout = float(settings.get("timeout") or 0)
    except (TypeError, ValueError):
        # "30s" escrito na mao no YAML estourava ValueError no clique de Enviar
        out.timeout = 0.0
    out.verify_tls = settings.get("verifyTls", True)
    out.ca_arquivo = ""
    out.follow_redirects = settings.get("followRedirects", True)

    config, origem = authmod.efetiva(request, ancestry)
    aplicada = authmod.aplicar(config, variables, cofre, rede=rede)
    out.auth_tipo = aplicada.tipo
    out.auth_origem = origem
    out.auth_detalhe = aplicada.detalhe
    out.auth_erro = aplicada.erro
    out.oauth2_pendente = aplicada.pendente

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


def completar_auth(prepared: Prepared) -> None:
    """Pede o token do OAuth2 que o prepare deixou pendente. Vai a rede.

    Troca so o header que ainda carrega a marca de pendente: header de Authorization
    escrito no proprio request continua ganhando da auth, como no prepare.
    """
    pendente = prepared.oauth2_pendente
    if not pendente:
        return
    prepared.oauth2_pendente = None
    if pendente["marca"] not in prepared.headers.values():
        # o Authorization escrito no request ganhou da auth: o token nao vai em lugar
        # nenhum, e pedir ele assim mesmo so servia pra falha do provedor barrar o envio
        return
    aplicada = authmod.aplicar(pendente["config"], pendente["variaveis"], pendente["cofre"])
    if aplicada.erro:
        prepared.auth_erro = aplicada.erro
        return
    prepared.auth_detalhe = aplicada.detalhe
    novo = aplicada.headers.get("Authorization", "")
    for chave, valor in list(prepared.headers.items()):
        if valor == pendente["marca"]:
            prepared.headers[chave] = novo
    prepared.secrets.extend(aplicada.secrets)


def _dominio(url: str) -> str:
    """O host do jeito que o cookiejar compara, com o .local que ele poe em host sem ponto."""
    return http.cookiejar.eff_request_host(urllib.request.Request(url))[1]


def _jarra(url: str, cookies: dict) -> httpx.Cookies | None:
    """Os cookies guardados, presos ao host de onde vieram.

    Passados como dicionario solto, o httpx grava cada um sem dominio, e cookie sem
    dominio vai pra qualquer host: num redirect pra outro endereco, a sessao do primeiro
    servidor seguia junto pro segundo.
    """
    if not cookies:
        return None
    dominio = _dominio(url)
    jarra = httpx.Cookies()
    for nome, valor in cookies.items():
        jarra.set(str(nome), str(valor), domain=dominio)
    return jarra


def _cookies_do_host(jar, url: str) -> dict:
    """So o que vale pro host do request. O jar do workspace guarda por host dele, e o
    cookie que um redirect pegou de outro servidor iria parar no primeiro."""
    dominio = _dominio(url)
    saida = {}
    for cookie in jar:
        alvo = (cookie.domain or "").lstrip(".")
        if not alvo or dominio == alvo or dominio.endswith("." + alvo):
            saida[cookie.name] = cookie.value
    return saida


def explicar_erro(erro: str, url: str = "") -> str:
    """Frase curta com o que fazer, pros erros de rede que mais aparecem.

    O texto do httpx e do sistema, em ingles e com numero de erro do Windows, fica na
    segunda linha da tela e no historico como veio. Esta frase so vai na frente dele.
    Devolve vazio quando o erro nao e um dos conhecidos.
    """
    texto = erro or ""
    baixo = texto.lower()
    partes = urllib.parse.urlsplit(url or "")
    host = partes.hostname or "o servidor"
    try:
        porta = partes.port or (443 if partes.scheme == "https" else 80)
    except ValueError:
        porta = ""
    alvo = f"{host}:{porta}" if porta else host

    if "certificate_verify_failed" in baixo or "certificate verify failed" in baixo:
        return (
            "o certificado do servidor nao e reconhecido. Se ele e de uma CA interna, "
            "cadastre a CA em Executar, Certificados e CA; so pra este request, da pra "
            "desligar a verificacao na aba Ajustes"
        )
    if "connecttimeout" in baixo:
        return f"{alvo} nao atendeu a conexao a tempo. Confira o endereco, a porta e a VPN"
    if "readtimeout" in baixo or "writetimeout" in baixo:
        return (
            "o servidor aceitou a conexao mas nao respondeu dentro do tempo limite, que "
            "fica na aba Ajustes do request"
        )
    if any(sinal in baixo for sinal in (
        "getaddrinfo", "11001", "name or service not known", "nodename nor servname",
        "name resolution", "no address associated",
    )):
        return f"nao achei o endereco {host}. Confira a url, a variavel dela ou a VPN"
    if any(sinal in baixo for sinal in ("10061", "connection refused", "refused")):
        return f"nada respondendo em {alvo}. O servico esta de pe nessa porta?"
    return ""


def send(prepared: Prepared) -> dict:
    if not prepared.url.lower().startswith(("http://", "https://")):
        return {"ok": False, "error": "a url precisa comecar com http ou https", "elapsedMs": 0}

    try:
        completar_auth(prepared)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"auth: {type(exc).__name__}: {exc}", "elapsedMs": 0}

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
            cookies=_jarra(prepared.url, prepared.cookies),
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
            cookies_finais = _cookies_do_host(client.cookies.jar, prepared.url)
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
