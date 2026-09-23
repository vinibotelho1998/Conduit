"""Confere o nucleo peca por peca, sem janela: cada funcao com o caso comum, a borda e o
erro que ela promete tratar.

As outras suites sobem o app inteiro e pegam o defeito que so aparece com tudo montado.
Esta olha o que fica atras da tela: parametro que some no import, segredo que escapa do
redator, data que cai no dia errado, arquivo de outra ferramenta lido pela metade. Roda
em poucos segundos e aponta a funcao, e nao a janela.

Rede, so a da propria maquina: um servidor HTTP falso numa porta livre faz o papel do
provedor de token e da api. Nada aqui sai pra internet.
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import re
import shutil
import sys
import tempfile
import threading
import time
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs

from comum import Placar, casa_limpa, sem_tela  # noqa: E402

sem_tela()
casa_limpa("nucleo")

from conduit.core import (  # noqa: E402
    auth,
    certs,
    codegen,
    cookies,
    curl_import,
    dinamicas,
    engine,
    examples,
    history,
    importer,
    scopes,
    sftp,
    storage,
    vars as resolvedor,
    vault,
    workspaces as ws,
)
from conduit.core.formats import Resultado, bruno, insomnia, openapi, postman  # noqa: E402

PASTAS: list[Path] = []


def pasta_nova(nome: str) -> Path:
    destino = Path(tempfile.mkdtemp(prefix=f"conduit-nucleo-{nome}-"))
    PASTAS.append(destino)
    return destino


def var(valor: str, secreta: bool = False) -> dict:
    return {"value": valor, "secret": secreta}


class CofreDeMentira:
    """Cofre em memoria, pro que so precisa de get e set. O de verdade tem secao propria."""

    def __init__(self):
        self.dados: dict[str, str] = {}

    def get(self, chave, padrao=""):
        return self.dados.get(chave, padrao)

    def set(self, chave, valor):
        self.dados[chave] = valor

    def remover_prefixo(self, prefixo):
        alvos = [c for c in self.dados if c.startswith(prefixo)]
        for chave in alvos:
            self.dados.pop(chave)
        return len(alvos)


def subir_http():
    """Servidor falso: provedor de token, eco do que chegou e uma resposta que demora."""
    pedidos: list[tuple[str, dict]] = []

    class Local(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def _responder(self, codigo, corpo=b"", extras=()):
            self.send_response(codigo)
            for chave, valor in extras:
                self.send_header(chave, valor)
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            try:
                self.wfile.write(corpo)
            except ConnectionError:
                # o teste de tempo limite desiste antes da resposta; e o esperado
                pass

        def do_GET(self):  # noqa: N802
            if self.path.startswith("/eco"):
                corpo = json.dumps({
                    "caminho": self.path,
                    "authorization": self.headers.get("Authorization") or "",
                    "cookie": self.headers.get("Cookie") or "",
                }).encode()
                self._responder(200, corpo, [("Content-Type", "application/json"),
                                             ("X-Request-Id", "req-do-servidor"),
                                             ("Set-Cookie", "sessao=nova; Path=/")])
            elif self.path == "/demora":
                time.sleep(1.5)
                self._responder(200, b"tarde")
            else:
                self._responder(404, b"nada aqui")

        def do_POST(self):  # noqa: N802
            tamanho = int(self.headers.get("Content-Length") or 0)
            campos = {k: v[0] for k, v in parse_qs(self.rfile.read(tamanho).decode()).items()}
            pedidos.append((self.path, campos))
            if self.path == "/token":
                corpo = json.dumps({"access_token": f"tok-{len(pedidos)}", "expires_in": 3600}).encode()
                self._responder(200, corpo, [("Content-Type", "application/json")])
            elif self.path == "/token-recusado":
                self._responder(401, b'{"error": "invalid_client"}')
            elif self.path == "/token-html":
                self._responder(200, b"<html>login</html>", [("Content-Type", "text/html")])
            elif self.path == "/token-sem-access":
                self._responder(200, b'{"token_type": "bearer"}', [("Content-Type", "application/json")])
            else:
                self._responder(404)

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), Local)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return servidor, f"http://127.0.0.1:{servidor.server_address[1]}", pedidos


def porta_fechada() -> int:
    import socket

    tomada = socket.socket()
    tomada.bind(("127.0.0.1", 0))
    porta = tomada.getsockname()[1]
    tomada.close()
    return porta


def main() -> int:
    p = Placar("Nucleo, funcao por funcao")

    def caso(rotulo: str, resultado, detalhe="") -> None:
        """Confere um valor pronto, ou chama a funcao e confere o que ela devolver.

        Com funcao, o erro dela vira uma linha de falha em vez de derrubar a suite.
        """
        if callable(resultado):
            try:
                resultado = resultado()
            except Exception as erro:  # noqa: BLE001
                p.confere(rotulo, False, f"{type(erro).__name__}: {erro}")
                return
        if isinstance(resultado, tuple):
            resultado, detalhe = resultado
        p.confere(rotulo, resultado, str(detalhe) if detalhe != "" else "")

    servidor, base_http, pedidos = subir_http()
    secoes = [
        (_variaveis, ()), (_escopos, ()), (_auth, (base_http, pedidos)), (_montagem, (base_http,)),
        (_curl, ()), (_codigo, ()), (_historico, ()), (_exemplos_e_cookies, ()), (_cofre, ()),
        (_gravacao, ()), (_registro, ()), (_certificados, ()), (_postman, ()), (_insomnia, ()),
        (_bruno, ()), (_openapi, ()), (_importador, ()), (_sftp_sem_servidor, ()),
        (_funcoes_da_tela, ()), (_linha_de_comando, ()),
    ]
    try:
        for secao, extras in secoes:
            # uma secao que estoura no meio vira falha dela, e as outras seguem rodando
            try:
                secao(p, caso, *extras)
            except Exception as erro:  # noqa: BLE001
                p.confere(f"{secao.__name__[1:]} rodou ate o fim", False, f"{type(erro).__name__}: {erro}")
    finally:
        servidor.shutdown()
        for pasta in PASTAS:
            shutil.rmtree(pasta, ignore_errors=True)
    return p.fechar()


# ---------------------------------------------------------------------------- variaveis


def _variaveis(p, caso) -> None:
    p.secao("resolver {{variavel}}")
    mapa = {"base": var("https://api"), "id": var("42"), "token": var("SEGREDO-1", True),
            "vazio": var("", True)}

    feito = resolvedor.resolve("{{base}}/itens/{{ id }}", mapa)
    caso("troca o nome pelo valor, com ou sem espaco dentro das chaves",
         (feito.text == "https://api/itens/42" and not feito.missing, feito.text))
    faltou = resolvedor.resolve("{{base}}/{{sumida}}/{{sumida}}", mapa)
    caso("nome sem dono fica como esta e vai pra lista de faltantes",
         (faltou.text == "https://api/{{sumida}}/{{sumida}}" and faltou.missing == ["sumida", "sumida"],
          (faltou.text, faltou.missing)))
    secreto = resolvedor.resolve("Bearer {{token}} {{vazio}}", mapa)
    caso("segredo com valor entra no ledger, e o vazio nao",
         (secreto.secrets == [("token", "SEGREDO-1")], secreto.secrets))
    caso("texto nulo ou vazio volta vazio, sem estourar",
         resolvedor.resolve(None, mapa).text == "" and resolvedor.resolve("", mapa).text == "")

    arvore = {"activeEnv": "e2", "environments": [
        {"id": "e1", "values": [{"key": "so_no_outro", "value": "x"}]},
        {"id": "e2", "values": [
            {"key": "host", "value": "h2"},
            {"key": "desligada", "value": "x", "enabled": False},
            {"key": "", "value": "sem nome"},
            {"key": "chave", "value": "k", "secret": True},
        ]},
    ]}
    ativo = resolvedor.env_map(arvore)
    caso("env_map le so o ambiente ativo, sem desligada nem linha sem nome",
         (ativo == {"host": var("h2"), "chave": var("k", True)}, ativo))
    caso("sem ambiente ativo o mapa sai vazio", resolvedor.env_map({"environments": arvore["environments"]}) == {})

    caso("redact devolve {{nome}} no lugar do valor",
         resolvedor.redact("x=SEGREDO-1&y=SEGREDO-1", [("token", "SEGREDO-1")]) == "x={{token}}&y={{token}}")
    caso("redact ignora valor vazio e ledger nulo",
         resolvedor.redact("abc", [("vazia", "")]) == "abc" and resolvedor.redact("abc", None) == "abc")

    p.secao("variaveis geradas na hora")
    uuid_re = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
    um = resolvedor.resolve("{{$guid}}", {}).text
    outro = resolvedor.resolve("{{$guid}}", {}).text
    caso("$guid e um uuid v4 novo a cada envio", (bool(uuid_re.match(um)) and um != outro, (um, outro)))
    caso("$guid gravado vazio no ambiente nao prende o valor",
         bool(uuid_re.match(resolvedor.resolve("{{$guid}}", {"$guid": var("")}).text)))
    agora = time.time()
    marca = int(dinamicas.gerar("$timestamp"))
    caso("$timestamp e o epoch em segundos de agora", (abs(marca - agora) < 5, marca))
    iso = dinamicas.gerar("$isoTimestamp")
    caso("$isoTimestamp e ISO em UTC terminado em Z",
         (iso.endswith("Z") and abs(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() - agora) < 5, iso))
    inteiros = [int(dinamicas.gerar("$randomInt")) for _ in range(200)]
    caso("$randomInt fica entre 0 e 1000", (min(inteiros) >= 0 and max(inteiros) <= 1000, (min(inteiros), max(inteiros))))
    alfa = dinamicas.gerar("$randomAlphaNumeric")
    caso("$randomAlphaNumeric tem 16 letras e numeros", (len(alfa) == 16 and alfa.isalnum(), alfa))
    hexa = dinamicas.gerar("$randomHex")
    caso("$randomHex tem 32 hexadecimais", (bool(re.fullmatch(r"[0-9a-f]{32}", hexa)), hexa))
    caso("$randomUUID e o mesmo formato do $guid", bool(uuid_re.match(dinamicas.gerar("$randomUUID"))))
    desconhecida = resolvedor.resolve("{{$guidd}}", {})
    caso("cifrao com nome errado nao vira vazio, e avisa",
         (desconhecida.text == "{{$guidd}}" and desconhecida.missing == ["$guidd"], desconhecida))
    caso("so nome com cifrao e reservado",
         dinamicas.eh_dinamica("$x") and not dinamicas.eh_dinamica("x") and not dinamicas.eh_dinamica(None))
    caso("toda gerada tem descricao pra ajuda", (set(dinamicas.GERADORES) == set(dinamicas.DESCRICAO),
                                                  set(dinamicas.GERADORES) ^ set(dinamicas.DESCRICAO)))
    caso("conhecida separa o nome certo do errado",
         dinamicas.conhecida("$guid") and not dinamicas.conhecida("$guidd"))


def _escopos(p, caso) -> None:
    p.secao("escopos")
    colecao = {"type": "collection", "name": "Api", "variables": [
        {"key": "base", "value": "da-collection"}, {"key": "so_col", "value": "c"}]}
    pasta = {"type": "folder", "name": "Pedidos", "variables": [
        {"key": "base", "value": "da-pasta"}, {"key": "so_pasta", "value": "f"}]}
    arvore = {
        "activeEnv": "hml",
        "globals": [{"key": "base", "value": "global"}, {"key": "so_global", "value": "g"}],
        "environments": [{"id": "hml", "name": "hml", "values": [
            {"key": "base", "value": "do-ambiente"},
            {"key": "desligada", "value": "x", "enabled": False},
            {"key": "  com_espaco  ", "value": "limpo"},
            {"key": "porta", "value": 8080},
            {"key": "ligado", "value": True},
            {"key": "nulo", "value": None},
        ]}],
    }
    mapa = scopes.build(arvore, [colecao, pasta])
    caso("ambiente ganha de pasta, collection e global",
         (mapa["base"].value == "do-ambiente" and mapa["base"].scope == "ambiente", mapa["base"]))
    caso("quem perdeu fica anotado, do mais geral pro mais proximo",
         ([s.scope for s in mapa["base"].shadowed] == ["globais", "collection", "pasta"],
          [s.scope for s in mapa["base"].shadowed or []]))
    caso("cada escopo contribui com o que so ele tem",
         (mapa["so_global"].value, mapa["so_col"].value, mapa["so_pasta"].value) == ("g", "c", "f"))
    caso("origem diz de onde veio", (mapa["so_pasta"].origin == "Pedidos" and mapa["so_global"].origin == "workspace",
                                     mapa["so_pasta"].origin))
    caso("linha desligada nao entra", "desligada" not in mapa)
    caso("espaco em volta do nome sai", "com_espaco" in mapa and "  com_espaco  " not in mapa)
    caso("numero, booleano e nulo viram texto",
         ((mapa["porta"].value, mapa["ligado"].value, mapa["nulo"].value) == ("8080", "true", ""),
          (mapa["porta"].value, mapa["ligado"].value, mapa["nulo"].value)))
    com_execucao = scopes.build(arvore, [colecao, pasta], runtime={"base": "da-execucao"})
    caso("execucao ganha de tudo", (com_execucao["base"].scope == "execucao", com_execucao["base"].scope))
    sem_linhagem = scopes.build(arvore)
    caso("sem linhagem ficam global, ambiente e execucao",
         "so_col" not in sem_linhagem and "so_pasta" not in sem_linhagem and "so_global" in sem_linhagem)
    caso("sem ambiente ativo nao ha ambiente", scopes.active_env({"environments": arvore["environments"]}) is None)
    plano = scopes.as_plain(mapa)
    caso("as_plain entrega valor e marca de secreta", plano["base"] == var("do-ambiente"))

    info = scopes.VarInfo
    caso("mascara: publico aparece inteiro", info("a", "valor-aberto").masked() == "valor-aberto")
    caso("mascara: secreto curto vira tres asteriscos", info("a", "abc", secret=True).masked() == "***")
    caso("mascara: secreto longo mostra so as pontas",
         info("a", "abcdefghijk", secret=True).masked() == "abc***jk")
    caso("mascara: secreto vazio fica vazio", info("a", "", secret=True).masked() == "")


# ---------------------------------------------------------------------------- auth


def _auth(p, caso, base_http, pedidos) -> None:
    p.secao("auth: heranca")
    bearer = {"type": "bearer", "token": "t"}
    basic = {"type": "basic", "username": "u"}
    colecao = {"type": "collection", "name": "Api", "auth": bearer}
    pasta_herda = {"type": "folder", "name": "Herda", "auth": {"type": "inherit"}}
    pasta_basic = {"type": "folder", "name": "Interna", "auth": basic}

    caso("auth propria vale e diz que e deste request",
         auth.efetiva({"auth": basic}, [colecao]) == (basic, "deste request"))
    caso("herda da pasta mais proxima que define",
         auth.efetiva({"auth": {"type": "inherit"}}, [colecao, pasta_basic, pasta_herda]) == (basic, "pasta Interna"))
    caso("pasta que herda sobe pra collection",
         auth.efetiva({}, [colecao, pasta_herda]) == (bearer, "collection Api"))
    caso("ninguem define, sai sem auth", auth.efetiva({}, []) == ({"type": "none"}, "nenhum"))

    p.secao("auth: tipos")
    mapa = {"tok": var("TOKEN-SECRETO", True), "usuario": var("ana"), "senha": var("s3nh4", True)}
    aplicada = auth.aplicar({"type": "bearer", "token": "{{tok}}"}, mapa)
    caso("bearer monta o header com o valor resolvido",
         aplicada.headers == {"Authorization": "Bearer TOKEN-SECRETO"})
    caso("e o token entra no ledger inteiro", ("auth.bearer", "TOKEN-SECRETO") in aplicada.secrets
         and ("tok", "TOKEN-SECRETO") in aplicada.secrets)
    vazio = auth.aplicar({"type": "bearer", "token": ""}, {})
    caso("bearer sem token e erro, sem header", vazio.erro == "bearer sem token" and not vazio.headers)

    basica = auth.aplicar({"type": "basic", "username": "{{usuario}}", "password": "{{senha}}"}, mapa)
    esperado = base64.b64encode(b"ana:s3nh4").decode()
    caso("basic codifica usuario e senha", basica.headers.get("Authorization") == f"Basic {esperado}")
    caso("o base64 vai pro ledger, senao o historico nao tem o que trocar",
         ("auth.basic", esperado) in basica.secrets)
    caso("basic sem usuario diz vazio", "usuario vazio" in auth.aplicar({"type": "basic"}, {}).detalhe)

    no_header = auth.aplicar({"type": "apikey", "key": "X-Api-Key", "value": "{{tok}}"}, mapa)
    caso("api key vai no header por padrao", no_header.headers == {"X-Api-Key": "TOKEN-SECRETO"} and not no_header.params)
    na_query = auth.aplicar({"type": "apikey", "key": "chave", "value": "v", "in": "query"}, {})
    caso("api key com in query vai pra query", na_query.params == [("chave", "v")] and not na_query.headers)
    caso("api key sem nome e erro", auth.aplicar({"type": "apikey", "value": "v"}, {}).erro == "api key sem nome")
    for tipo in ("none", "inherit", None):
        caso(f"tipo {tipo} nao poe nada", not auth.aplicar({"type": tipo}, {}).headers)

    p.secao("auth: OAuth2")
    caso("OAuth2 sem tokenUrl e erro legivel",
         "tokenUrl" in (auth.aplicar({"type": "oauth2", "clientId": "c"}, {}).erro or ""))
    pendente = auth.aplicar({"type": "oauth2", "tokenUrl": f"{base_http}/token", "clientId": "c",
                             "prefix": "Token"}, {}, None, rede=False)
    caso("sem rede e sem cache o token fica pendente, com o prefixo escolhido",
         (pendente.headers.get("Authorization") == "Token {{oauth2_token}}" and pendente.pendente is not None
          and not pedidos, (pendente.headers, len(pedidos))))

    cofre = CofreDeMentira()
    config = {"type": "oauth2", "tokenUrl": f"{base_http}/token", "clientId": "cliente",
              "clientSecret": "{{senha}}", "scope": "ler escrever", "audience": "api-a"}
    pedidos.clear()
    primeiro = auth.aplicar(config, mapa, cofre)
    campos = pedidos[0][1] if pedidos else {}
    caso("o pedido do token leva grant, cliente, segredo, escopo e audience",
         (campos == {"grant_type": "client_credentials", "client_id": "cliente", "client_secret": "s3nh4",
                     "scope": "ler escrever", "audience": "api-a"}, campos))
    caso("e o token volta no header", primeiro.headers.get("Authorization") == "Bearer tok-1", primeiro.headers)
    caso("o token novo entra no ledger", ("auth.oauth2", "tok-1") in primeiro.secrets)
    segundo = auth.aplicar(config, mapa, cofre)
    caso("segundo envio usa o cache, sem ir ao provedor",
         (len(pedidos) == 1 and segundo.headers.get("Authorization") == "Bearer tok-1" and "cache" in segundo.detalhe,
          (len(pedidos), segundo.detalhe)))
    chave = next(iter(cofre.dados))
    cofre.dados[chave] = json.dumps({"token": "quase-vencido", "expira": time.time() + auth.FOLGA_SEGUNDOS - 1})
    renovado = auth.aplicar(config, mapa, cofre)
    caso("token a menos da folga de vencer e pedido de novo",
         (len(pedidos) == 2 and "quase-vencido" not in renovado.headers.get("Authorization", ""), renovado.headers))
    cofre.dados[chave] = "{isto nao e json"
    caso("cache estragado nao derruba, pede outro", auth.aplicar(config, mapa, cofre).erro is None and len(pedidos) == 3)
    caso("limpar o cache tira so os tokens",
         (auth.limpar_cache(cofre) == 1 and not cofre.dados and auth.limpar_cache(None) == 0, cofre.dados))

    base = {"tokenUrl": f"{base_http}/token", "clientId": "c"}
    caso("assinatura muda com o grant e com a audience",
         len({auth._assinatura(base, "u", "c", "s", ""),
              auth._assinatura(dict(base, grant="password"), "u", "c", "s", ""),
              auth._assinatura(base, "u", "c", "s", "outra")}) == 3)
    for caminho, pedaco in (("/token-recusado", "401"), ("/token-html", "nao e JSON"),
                            ("/token-sem-access", "access_token")):
        _, erro, _ = auth.token_oauth2(dict(base, tokenUrl=f"{base_http}{caminho}"), {}, [], None)
        caso(f"provedor com {caminho[1:]} vira erro que diz o que houve", (pedaco in (erro or ""), erro))
    _, erro, _ = auth.token_oauth2(dict(base, tokenUrl=f"http://127.0.0.1:{porta_fechada()}/t"), {}, [], None)
    caso("provedor fora do ar vira erro, e nao excecao", ("falha ao pegar o token" in (erro or ""), erro))


# ---------------------------------------------------------------------------- engine


def _montagem(p, caso, base_http) -> None:
    p.secao("montagem do envio")
    mapa = {"base": var("https://api.exemplo"), "tok": var("SEG-99", True), "q": var("a b")}

    def preparar(request, variaveis=None, **extra):
        return engine.prepare(request, mapa if variaveis is None else variaveis, **extra)

    pronto = preparar({"method": "post", "url": "  {{base}}/itens\r\n"})
    caso("metodo sai em maiusculo e a url sem quebra nem espaco",
         (pronto.method == "POST" and pronto.url == "https://api.exemplo/itens", (pronto.method, pronto.url)))
    suposto = preparar({"url": "localhost:8080/api"})
    caso("url sem esquema ganha http:// e fica marcada",
         suposto.url == "http://localhost:8080/api" and suposto.esquema_suposto)
    caso("url com esquema nao e marcada", not preparar({"url": "https://x"}).esquema_suposto)
    sem_valor = preparar({"url": "{{sumida}}/x"}, {})
    caso("url com variavel sem valor nao ganha esquema",
         (sem_valor.url == "{{sumida}}/x" and sem_valor.missing == ["sumida"], (sem_valor.url, sem_valor.missing)))
    caso("faltante repetida aparece uma vez so", preparar({"url": "{{x}}/{{x}}"}, {}).missing == ["x"])

    com_params = preparar({"url": "https://x/a?velha=1", "params": [
        {"key": "q", "value": "{{q}}"}, {"key": "off", "value": "1", "enabled": False}, {"key": "", "value": "z"}]})
    caso("params mandam na query e a da url sai", (com_params.url == "https://x/a?q=a+b", com_params.url))
    caso("sem params a query da url fica", preparar({"url": "https://x/a?fica=1"}).url == "https://x/a?fica=1")

    cabecalhos = preparar({"url": "https://x", "headers": [
        {"key": "X-Tok", "value": "{{tok}}"}, {"key": "Off", "value": "1", "enabled": False}, {"key": "", "value": "v"}]})
    caso("header desligado ou sem nome nao vai", (cabecalhos.headers == {"X-Tok": "SEG-99"}, cabecalhos.headers))
    caso("segredo de header entra no ledger", ("tok", "SEG-99") in cabecalhos.secrets)

    json_corpo = preparar({"url": "https://x", "body": {"mode": "json", "raw": '{"t": "{{tok}}"}'}})
    caso("corpo json ganha Content-Type e resolve variavel",
         json_corpo.headers.get("Content-Type") == "application/json" and json_corpo.body == '{"t": "SEG-99"}')
    proprio = preparar({"url": "https://x", "headers": [{"key": "content-type", "value": "application/vnd+json"}],
                        "body": {"mode": "json", "raw": "{}"}})
    caso("Content-Type escrito a mao, em qualquer caixa, nao e trocado",
         (proprio.headers == {"content-type": "application/vnd+json"}, proprio.headers))
    formulario = preparar({"url": "https://x", "body": {"mode": "form", "raw": "a=1"}})
    caso("corpo form ganha urlencoded", formulario.headers.get("Content-Type") == "application/x-www-form-urlencoded")
    caso("corpo raw nao inventa Content-Type", not preparar({"url": "https://x", "body": {"mode": "raw", "raw": "oi"}}).headers)
    caso("modo none nao manda corpo mesmo com texto guardado",
         preparar({"url": "https://x", "body": {"mode": "none", "raw": "sobrou"}}).body is None)

    caso("tempo limite escrito como texto torto vira sem limite",
         preparar({"url": "https://x", "settings": {"timeout": "30s"}}).timeout == 0.0)
    ajustado = preparar({"url": "https://x", "settings": {"timeout": "12.5", "verifyTls": False,
                                                          "followRedirects": False}})
    caso("tempo limite, TLS e redirect do request valem",
         (ajustado.timeout, ajustado.verify_tls, ajustado.follow_redirects) == (12.5, False, False))

    escrito = preparar({"url": "https://x", "headers": [{"key": "authorization", "value": "Manual"}],
                        "auth": {"type": "bearer", "token": "{{tok}}"}})
    caso("Authorization escrito no request ganha da auth",
         (escrito.headers == {"authorization": "Manual"}, escrito.headers))
    caso("e a origem da auth fica registrada", escrito.auth_origem == "deste request" and escrito.auth_tipo == "bearer")
    chave_query = preparar({"url": "https://x/a", "params": [{"key": "p", "value": "1"}],
                            "auth": {"type": "apikey", "key": "k", "value": "{{tok}}", "in": "query"}})
    caso("api key na query junta com os params", (chave_query.url == "https://x/a?p=1&k=SEG-99", chave_query.url))
    caso("erro da auth chega no preparado", preparar({"url": "https://x", "auth": {"type": "bearer"}}).auth_erro)

    cofre = CofreDeMentira()
    cofre.set(certs.CHAVE_SENHA.format(host="*.exemplo"), "senha-do-pfx")
    arvore = {"certificates": [{"host": "*.exemplo", "file": "c:/x.pfx"}]}
    com_cert = preparar({"url": "{{base}}/x"}, tree=arvore, cofre=cofre)
    caso("certificado do host entra no preparado, com a senha do cofre",
         (com_cert.certificado is not None and com_cert.cert_senha == "senha-do-pfx", com_cert.cert_senha))
    caso("host de fora nao leva certificado", preparar({"url": "https://outro"}, tree=arvore).certificado is None)

    p.secao("envio")
    caso("url sem http nao sai", "http ou https" in engine.send(engine.Prepared(url="ftp://x")).get("error", ""))
    barrado = engine.send(engine.Prepared(url=f"{base_http}/eco", auth_erro="bearer sem token"))
    caso("erro de auth barra antes da rede", barrado == {"ok": False, "error": "auth: bearer sem token", "elapsedMs": 0})
    caso("CA que nao existe vira erro de certificado",
         "certificado de CA" in engine.send(engine.Prepared(url="https://x", ca_arquivo="c:/nao/existe.pem"))["error"])
    sem_arquivo = engine.send(engine.Prepared(url="https://x", certificado=certs.Certificado("x", "c:/nao/existe.pfx")))
    caso("pfx que nao existe vira erro de certificado cliente", "certificado cliente" in sem_arquivo["error"])

    volta = engine.send(engine.Prepared(method="GET", url=f"{base_http}/eco?a=1",
                                        headers={"Authorization": "Bearer x"}, cookies={"antigo": "1"}))
    corpo = json.loads(volta.get("body") or "{}")
    caso("resposta traz status, corpo, tamanho e url final",
         (volta["ok"] and volta["status"] == 200 and volta["sizeBytes"] == len(volta["content"])
          and volta["url"] == f"{base_http}/eco?a=1", {k: volta.get(k) for k in ("status", "url", "error")}))
    caso("header e cookie guardado chegam no servidor",
         (corpo.get("authorization") == "Bearer x" and corpo.get("cookie") == "antigo=1", corpo))
    caso("cookie que o servidor mandou volta pro jar", (volta.get("cookies", {}).get("sessao") == "nova", volta.get("cookies")))
    caso("headers da resposta vem em pares", ["x-request-id", "req-do-servidor"] in [
        [k.lower(), v] for k, v in volta["headers"]])
    lento = engine.send(engine.Prepared(url=f"{base_http}/demora", timeout=0.3))
    caso("tempo limite estourado vira falha com o nome do erro",
         (not lento["ok"] and "ReadTimeout" in lento["error"], lento.get("error")))

    marca = f"Bearer {auth.TOKEN_PENDENTE}"
    ganhou = engine.Prepared(url="https://x", headers={"Authorization": "Manual"},
                             oauth2_pendente={"config": {"tokenUrl": f"http://127.0.0.1:{porta_fechada()}/t",
                                                         "clientId": "c", "type": "oauth2"},
                                              "variaveis": {}, "cofre": None, "marca": marca})
    engine.completar_auth(ganhou)
    caso("token pendente que perdeu pro header manual nao e pedido",
         ganhou.oauth2_pendente is None and ganhou.auth_erro is None and ganhou.headers == {"Authorization": "Manual"})
    fora = engine.Prepared(url="https://x", headers={"Authorization": marca},
                           oauth2_pendente={"config": {"type": "oauth2", "clientId": "c",
                                                       "tokenUrl": f"http://127.0.0.1:{porta_fechada()}/t"},
                                            "variaveis": {}, "cofre": None, "marca": marca})
    engine.completar_auth(fora)
    caso("provedor fora do ar no envio vira erro de auth", "falha ao pegar o token" in (fora.auth_erro or ""))

    p.secao("frase do erro de rede")
    caso("certificado desconhecido fala da CA",
         "CA" in engine.explicar_erro("ConnectError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"))
    caso("conexao que nao atende diz host e porta padrao do https",
         "api.exemplo:443" in engine.explicar_erro("ConnectTimeout: timed out", "https://api.exemplo/x"))
    caso("porta invalida na url nao estoura",
         engine.explicar_erro("ConnectTimeout", "http://h:abc/").startswith("h nao atendeu"))
    caso("leitura que estoura fala do tempo limite", "tempo limite" in engine.explicar_erro("ReadTimeout: x"))
    caso("nome que nao resolve cita o host",
         "nao.existe" in engine.explicar_erro("ConnectError: [Errno 11001] getaddrinfo failed", "http://nao.existe:81/x"))
    caso("porta fechada cita host e porta",
         "127.0.0.1:9" in engine.explicar_erro("ConnectError: [WinError 10061] recusou", "http://127.0.0.1:9/"))
    caso("erro desconhecido nao ganha frase", engine.explicar_erro("ValueError: outro") == "")

    p.secao("cookie por host")
    caso("host sem ponto ganha o .local do cookiejar", engine._dominio("http://localhost:8080/x") == "localhost.local")
    jarra = [SimpleNamespace(domain=".exemplo.com", name="pai", value="1"),
             SimpleNamespace(domain="outro.com", name="alheio", value="2"),
             SimpleNamespace(domain="", name="solto", value="3"),
             SimpleNamespace(domain="api.exemplo.com", name="proprio", value="4")]
    caso("so o cookie do host e dos pais dele fica",
         engine._cookies_do_host(jarra, "https://api.exemplo.com/x") == {"pai": "1", "solto": "3", "proprio": "4"})
    caso("sem cookie nao monta jarra", engine._jarra("https://x", {}) is None)


# ---------------------------------------------------------------------------- curl


def _curl(p, caso) -> None:
    p.secao("importar curl")
    imp = curl_import.importar
    bash = imp("curl -X put \\\n  'https://x/a?b=1&c=' \\\n  -H 'Accept: application/json' \\\n  --compressed")
    caso("barra invertida do bash junta as linhas, metodo sai em maiusculo",
         (bash.erro is None and bash.method == "PUT" and bash.url == "https://x/a", (bash.erro, bash.method, bash.url)))
    caso("query da url vira params, inclusive o vazio",
         [(q["key"], q["value"]) for q in bash.params] == [("b", "1"), ("c", "")])
    caso("opcao de ruido some sem aviso", not bash.ignorados)
    ps = imp("curl https://x `\n  -H 'A: 1'")
    caso("crase do PowerShell junta as linhas", ps.erro is None and ps.headers[0]["key"] == "A")
    cmd = imp('curl https://x ^\n  -H "A: 1"')
    caso("circunflexo do cmd junta as linhas", cmd.erro is None and cmd.headers[0]["value"] == "1")
    caso("texto que nao e curl recusa", imp("wget https://x").erro == "o texto nao comeca com curl")
    caso("curl sem url recusa", imp("curl -H 'A: 1'").erro == "nao achei a url no comando")
    caso("url sem esquema ganha https", imp("curl api.exemplo/x").url == "https://api.exemplo/x")
    caso("--url tambem e url", imp("curl --url https://x/y").url == "https://x/y")

    corpo_json = imp("curl https://x -d '{\"a\": 1}'")
    caso("-d com JSON vira POST com corpo json", corpo_json.method == "POST" and corpo_json.body["mode"] == "json")
    caso("-d repetido junta com &", imp("curl https://x -H 'Content-Type: text/plain' -d a -d b").body["raw"] == "a&b")
    texto = imp("curl https://x -H 'Content-Type: text/plain' -d 'oi'")
    caso("-d com Content-Type de texto fica raw", texto.body == {"mode": "raw", "raw": "oi"})
    get = imp("curl -G https://x -d 'a=1' --data-urlencode 'b=dois tres'")
    caso("-G leva o corpo pra query e fica GET",
         (get.method == "GET" and get.body["mode"] == "none"
          and [(q["key"], q["value"]) for q in get.params] == [("a", "1"), ("b", "dois tres")], (get.method, get.params)))
    explicito = imp("curl -X DELETE https://x -d 'a=1'")
    caso("-X manda mesmo com corpo", explicito.method == "DELETE")
    com_json = imp("curl https://x --json '{\"a\":1}' --json '{}'")
    caso("--json poe o Content-Type uma vez so",
         [h["key"] for h in com_json.headers].count("Content-Type") == 1 and com_json.body["mode"] == "json")
    usuario = imp("curl -u ana:s3:nh4 https://x")
    caso("-u vira auth basic, senha com dois pontos inteira",
         usuario.auth == {"type": "basic", "username": "ana", "password": "s3:nh4"})
    extras = imp("curl https://x -b 'a=1' -A 'Agente/1' -e https://antes")
    caso("-b, -A e -e viram header",
         [(h["key"], h["value"]) for h in extras.headers] == [("Cookie", "a=1"), ("User-Agent", "Agente/1"),
                                                             ("Referer", "https://antes")])
    ajustes = imp("curl -k -L -m 12.7 https://x")
    caso("-k, -L e -m viram ajustes do request",
         (ajustes.settings == {"verifyTls": False, "followRedirects": True, "timeout": 12}, ajustes.settings))
    caso("-m com lixo e ignorado", "timeout" not in imp("curl -m abc https://x").settings)
    desconhecida = imp("curl --opcao-nova valor https://x")
    caso("opcao desconhecida vai pros ignorados e engole o valor dela",
         (desconhecida.ignorados == ["--opcao-nova"] and desconhecida.url == "https://x", desconhecida.ignorados))
    caso("mas nao engole uma url", imp("curl --opcao-nova https://x").url == "https://x")
    form = imp("curl https://x -F a=1 -F b=2")
    caso("-F de texto vira form urlencoded, com um aviso so",
         (form.body == {"mode": "form", "raw": "a=1&b=2"} and len(form.ignorados) == 1, (form.body, form.ignorados)))
    arquivo = imp("curl https://x -F nota=@nota.pdf")
    caso("-F com arquivo continua POST, como no curl", (arquivo.method == "POST", arquivo.method))
    de_arquivo = imp("curl https://x -d @corpo.json")
    caso("-d @arquivo nao manda o nome do arquivo como corpo, e avisa",
         (de_arquivo.body.get("raw") != "@corpo.json" and any("arquivo" in i for i in de_arquivo.ignorados)
          and de_arquivo.method == "POST", (de_arquivo.method, de_arquivo.body, de_arquivo.ignorados)))
    caso("--data-raw @ e texto de verdade, e vai como esta",
         imp("curl https://x -H 'Content-Type: text/plain' --data-raw @oi").body["raw"] == "@oi")
    sem_tipo = imp("curl https://x -d 'a=1&b=2'")
    caso("-d sem Content-Type sai como form, que e o que o curl manda",
         (sem_tipo.body == {"mode": "form", "raw": "a=1&b=2"}, sem_tipo.body))
    cortado = imp("curl 'https://x/a?b=1")
    caso("comando cortado com aspa aberta ainda importa",
         (cortado.erro is None and cortado.url == "https://x/a", (cortado.erro, cortado.url)))
    caso("parece_curl aceita espaco antes e recusa palavra parecida",
         curl_import.parece_curl("  curl https://x") and not curl_import.parece_curl("curly https://x"))
    resumo = imp("curl -u a:b https://x/y?z=1 -H 'A: 1' -d '{}'").resumo()
    caso("resumo conta header, param, corpo e auth",
         all(t in resumo for t in ("POST https://x/y", "1 headers", "1 params", "corpo json", "auth basic")), resumo)

    request = {"method": "GET", "url": "velha", "settings": {"timeout": 5, "verifyTls": True}}
    curl_import.aplicar(request, imp("curl -k -X PATCH https://x -u a:b"))
    caso("aplicar troca o request e junta os ajustes",
         (request["method"] == "PATCH" and request["url"] == "https://x" and request["auth"]["type"] == "basic"
          and request["settings"] == {"timeout": 5, "verifyTls": False}, request))


# ---------------------------------------------------------------------------- codigo


def _codigo(p, caso) -> None:
    p.secao("codigo gerado")
    gerar = codegen.generate
    headers = {"Accept": "application/json", "Content-Type": "application/json; charset=utf-8"}
    caso("linguagem desconhecida diz que nao suporta", "nao suportada" in gerar("cobol", "GET", "https://x", {}, None))
    curl = gerar("curl", "post", "https://x/a b", headers, "it's")
    caso("curl com aspa simples e o metodo em maiusculo",
         curl.startswith("curl -X POST 'https://x/a b'") and "-d 'it'\"'\"'s'" in curl, curl)
    caso("curl sem corpo nao tem -d", "-d" not in gerar("curl", "GET", "https://x", {}, None))
    ps = gerar("powershell", "POST", "https://x", {"A": "b'c"}, "linha1\nlinha2")
    caso("PowerShell poe o corpo num here-string e dobra a aspa",
         "$body = @'\nlinha1\nlinha2\n'@" in ps and "'b''c'" in ps and "-Body $body" in ps, ps)
    caso("PowerShell sem header nao cita $headers", "$headers" not in gerar("powershell", "GET", "https://x", {}, None))
    for linguagem in ("python-httpx", "python-requests"):
        codigo = gerar(linguagem, "PUT", "https://x", headers, '{"a": "b\\"c"}')
        try:
            compile(codigo, linguagem, "exec")
            valido = True
        except SyntaxError as erro:
            valido = f"SyntaxError: {erro}"
        caso(f"{linguagem} compila e leva o metodo", (valido is True and '"PUT"' in codigo, valido))
    fetch = gerar("javascript-fetch", "POST", "https://x", {}, "texto com ${x} e `crase`")
    caso("fetch com texto escapa interpolacao e crase", "\\${x}" in fetch and "\\`crase\\`" in fetch, fetch)
    axios = gerar("node-axios", "DELETE", "https://x", {}, '{"a":1}')
    caso("axios manda o metodo em minusculo e o JSON como objeto", 'method: "delete"' in axios and '"a": 1' in axios)
    java = gerar("java", "POST", 'https://x/"q"', {"A": 'v"'}, "a\\b")
    caso("Java escapa aspa e barra", 'https://x/\\"q\\"' in java and 'v\\"' in java and "a\\\\b" in java, java)
    caso("Java sem corpo usa noBody", "noBody()" in gerar("java", "GET", "https://x", {}, None))
    csharp = gerar("csharp", "POST", "https://x", headers, 'diz "oi"')
    caso("C# tira o Content-Type dos headers e usa no conteudo",
         'TryAddWithoutValidation("Content-Type"' not in csharp and '"application/json")' in csharp
         and 'diz ""oi""' in csharp, csharp)
    go = gerar("go", "POST", "https://x", {}, "com `crase`")
    caso("Go quebra a crase do corpo", "` + \"`\" + `" in go)


# ---------------------------------------------------------------------------- historico


def _historico(p, caso) -> None:
    p.secao("historico")
    raiz = pasta_nova("historico")
    hist = history.History(raiz)
    ledger = [("token", "SEGREDO-LONGO-123")]
    enviado = engine.Prepared(
        method="POST", url="https://api/x?k=SEGREDO-LONGO-123",
        headers={"Authorization": "Bearer SEGREDO-LONGO-123", "X-Api-Key": "chave-que-nao-e-variavel",
                 "Cookie": "a=1", "X-Request-Id": "rid-1"},
        body="x" * (history.MAX_REQ_BODY + 10), secrets=ledger, missing=["faltou"],
    )
    resultado = {"ok": True, "status": 201, "reason": "Created", "elapsedMs": 12, "sizeBytes": 3,
                 "headers": [["Set-Cookie", "s=abcdefghijkl"], ["traceparent", "00-abc"]],
                 "body": "SEGREDO-LONGO-123", "url": "https://api/x?k=SEGREDO-LONGO-123"}
    ident = hist.record(request={"id": "r1", "name": "Criar", "url": "{{base}}/x"}, prepared=enviado,
                        result=resultado, request_path="Api/Criar", env_name="hml")
    lido = hist.get(ident)
    pedido, resposta = lido["request"], lido["response"]
    cabecalhos = dict(map(tuple, pedido["headers"]))
    caso("url, header e corpo da resposta gravados sem o segredo",
         ("SEGREDO" not in json.dumps(lido), [t for t in ("url", "headers", "body") if "SEGREDO" in json.dumps(pedido.get(t))]))
    caso("header de credencial que veio de variavel fica como {{nome}}",
         cabecalhos["Authorization"] == "Bearer {{token}}", cabecalhos["Authorization"])
    caso("header de credencial solto sai mascarado pelas pontas",
         (cabecalhos["X-Api-Key"] == "chav***el" and cabecalhos["Cookie"] == "***", cabecalhos))
    caso("corpo grande e cortado e marcado",
         len(pedido["body"]) == history.MAX_REQ_BODY and pedido["bodyTruncated"])
    caso("id de correlacao do pedido e da resposta vao pro trace",
         (lido["trace"] == {"x-request-id": "rid-1", "traceparent": "00-abc"}, lido["trace"]))
    caso("o molde da url e as faltantes ficam juntos",
         pedido["urlTemplate"] == "{{base}}/x" and pedido["missingVars"] == ["faltou"])
    caso("Set-Cookie da resposta sai mascarado", resposta["headers"][0][1] == "s=ab***kl", resposta["headers"])

    def gravar(status, ok=True, metodo="GET", url="https://api/lista", rid="r2", caminho="Api/Listar", erro=None):
        return hist.record(request={"id": rid, "name": caminho.split("/")[-1], "url": url},
                           prepared=engine.Prepared(method=metodo, url=url),
                           result={"ok": ok, "status": status, "error": erro, "headers": [], "body": ""},
                           request_path=caminho)

    ids = [gravar(200), gravar(404), gravar(None, ok=False, erro="ConnectError"), gravar(500, metodo="DELETE")]
    Q = history.Query
    caso("filtro por familia de status", {r["id"] for r in hist.query(Q(status_class="4"))} == {ids[1]})
    caso("filtro de falha de rede pega o ok zero", {r["id"] for r in hist.query(Q(status_class="erro"))} == {ids[2]})
    caso("filtro por metodo", [r["id"] for r in hist.query(Q(method="DELETE"))] == [ids[3]])
    caso("busca por texto olha a url", len(hist.query(Q(text="lista"))) == 4)
    caso("busca pelo pedaco do id acha a execucao", [r["id"] for r in hist.query(Q(text=history.short_id(ids[0])))] == [ids[0]])
    caso("por request casa pelo id ou pelo caminho",
         len(hist.query(Q(request_id="r-que-mudou", request_path="Api/Listar"))) == 4
         and len(hist.query(Q(request_id="r1"))) == 1)
    caso("mais recente primeiro e com limite", [r["id"] for r in hist.query(Q(limit=2))] == [ids[3], ids[2]])
    agora = time.time()
    caso("ids novos ordenam depois dos velhos",
         history.new_entry_id(agora) < history.new_entry_id(agora + 0.002) < history.new_entry_id(agora + 60)
         and len(history.short_id(ids[0])) == 6)
    estat = hist.stats()
    caso("stats conta total e falhas", (estat["total"] == 5 and estat["falhas"] == 1, estat))
    uso = hist.uso_por_request()
    caso("uso por request conta pelo id e pelo caminho", (uso["r2"][0] == 4 and uso["Api/Listar"][0] == 4, uso.get("r2")))

    hist.delete(ids[1])
    caso("excluir tira do indice e deixa as outras abrindo",
         hist.get(ids[1]) is None and all(hist.get(i) for i in (ids[0], ids[2], ids[3])))
    hist.close()
    (raiz / "history" / "index.db").unlink()
    de_novo = history.History(raiz)
    caso("indice apagado nasce de novo do log, sem a excluida",
         (len(de_novo.query(Q())) == 4 and de_novo.get(ids[1]) is None, len(de_novo.query(Q()))))

    velho = datetime.now() - timedelta(days=100)
    dia_velho = velho.strftime("%Y-%m-%d")
    (raiz / "history" / f"{dia_velho}.jsonl").write_text(json.dumps({
        "id": "antiga", "ts": velho.isoformat(timespec="seconds"), "request": {"method": "GET", "url": "u"},
        "response": {"ok": True, "status": 200}}) + "\n", encoding="utf-8")
    medio = datetime.now() - timedelta(days=10)
    (raiz / "history" / f"{medio:%Y-%m-%d}.jsonl").write_text(json.dumps({
        "id": "de-dez-dias", "ts": medio.isoformat(timespec="seconds"), "request": {}, "response": {}}) + "\n",
        encoding="utf-8")
    caso("reconstruir le todo dia do log", de_novo.rebuild_index() == 6)
    caso("dias com corpo lista os logs do disco", dia_velho in de_novo.dias_com_corpo())
    expurgo = de_novo.purge()
    caso("expurgo apaga o log velho e o resumo mais velho que o limite",
         (expurgo == {"arquivos": 2, "registros": 1}, expurgo))
    caso("execucao de dez dias perde o corpo e mantem o resumo",
         de_novo.get("de-dez-dias") is None and (de_novo.resumo("de-dez-dias") or {}).get("id") == "de-dez-dias")
    caso("resumo de id que nao existe e None", de_novo.resumo("nao-existe") is None)
    de_novo.clear()
    caso("limpar zera o indice e o log", not de_novo.query(Q()) and not de_novo.dias_com_corpo())
    de_novo.close()
    caso("clip de nulo volta vazio", history._clip(None, 10) == ("", False))


def _exemplos_e_cookies(p, caso) -> None:
    p.secao("exemplo de resposta")
    ledger = [("token", "SEG-EX")]
    exemplo = examples.montar(
        "Criado", {"ok": True, "status": 201, "reason": "Created", "headers": [["Set-Cookie", "x=abcdefghij"]],
                   "body": "token SEG-EX", "sizeBytes": 12, "elapsedMs": 5},
        {"method": "POST", "url": "https://x?k=SEG-EX", "headers": {"Authorization": "Basic YWJjOmRlZmdoaQ=="},
         "body": "b" * (examples.LIMITE_CORPO + 5)}, ledger)
    caso("exemplo troca o segredo por {{nome}} na url e no corpo",
         exemplo["request"]["url"] == "https://x?k={{token}}" and exemplo["response"]["body"] == "token {{token}}")
    caso("credencial solta no header sai mascarada",
         exemplo["request"]["headers"] == [["Authorization", "Basi***=="]], exemplo["request"]["headers"])
    caso("corpo gigante e cortado com aviso", exemplo["request"]["body"].endswith("cortado ao salvar o exemplo"))
    caso("id de exemplo tem prefixo", exemplo["id"].startswith("ex-") and exemplo["id"] != examples.novo_id())
    dados, enviado = examples.para_resposta({"status": 200, "response": {"body": "ok", "headers": [["A", "1"]]},
                                             "request": {"headers": [["B", "2"]], "url": "u"}})
    caso("exemplo sem ok conta como sucesso e mede o corpo",
         dados["ok"] and dados["sizeBytes"] == 2 and dados["headers"] == [("A", "1")] and enviado["headers"] == {"B": "2"})
    caso("resumo do exemplo tem status, quando e tamanho",
         examples.resumo({"status": 200, "savedAt": "2026-01-02T10:11:12", "sizeBytes": 20})
         == "200   ·   2026-01-02 10:11   ·   20 B")
    caso("exemplo sem status mostra interrogacao", examples.resumo({}) == "?")

    p.secao("cookies do workspace")
    raiz = pasta_nova("cookies")
    jar = cookies.CookieJar(raiz)
    caso("guardar conta quantos entraram", jar.guardar("https://API.exemplo/x", {"a": 1, "b": "2"}) == 2)
    caso("host em qualquer caixa acha o cookie", jar.para_url("https://api.exemplo/outra") == {"a": "1", "b": "2"})
    caso("outro host nao ve o cookie", jar.para_url("https://outro/") == {})
    caso("url sem host ou cookie vazio nao grava", jar.guardar("sem-host", {"a": 1}) == 0 and jar.guardar("https://x", {}) == 0)
    jar.guardar("https://outro/", {"c": "3"})
    relido = cookies.CookieJar(raiz)
    caso("o jar sobrevive a outra instancia", relido.resumo()["cookies"] == 3 and relido.resumo()["dominios"] == 2)
    copia = relido.tudo()
    copia["intruso"] = {}
    caso("tudo devolve copia", "intruso" not in relido.tudo())
    caso("limpar um host conta o que saiu", relido.limpar("outro") == 1 and relido.resumo()["dominios"] == 1)
    caso("limpar tudo conta o resto", relido.limpar() == 2 and relido.resumo()["cookies"] == 0)


def _cofre(p, caso) -> None:
    p.secao("cofre")
    raiz = pasta_nova("cofre")
    cofre = vault.Vault(raiz)
    caso("chave do segredo separa por dono", vault.chave_de("hml", "token") == "env:hml:token")
    caso("cofre que nao existe abre vazio e sem erro", cofre.chaves() == [] and cofre.erro is None)
    cofre.set("env:hml:token", "VALOR-CIFRADO-1")
    caso("o arquivo nao guarda o valor em claro",
         "VALOR-CIFRADO-1" not in (raiz / ".secrets" / vault.ARQUIVO).read_text(encoding="utf-8"))
    caso("outra instancia le o que foi gravado", vault.Vault(raiz).get("env:hml:token") == "VALOR-CIFRADO-1")
    caso("chave ausente devolve o padrao", cofre.get("nao", "padrao") == "padrao")
    caso("gravar varios conta o total", cofre.set_muitos({"env:prd:a": "1", "oauth:x": "2"}) == 3)
    caso("gravar o mesmo de novo nao reescreve", cofre.set_muitos({"env:prd:a": "1"}) == 0)
    caso("valor vazio apaga a chave", cofre.set_muitos({"env:prd:a": ""}) == 2 and "env:prd:a" not in cofre.chaves())
    cofre.set("oauth:x", "")
    caso("set vazio tambem apaga", cofre.chaves() == ["env:hml:token"])
    cofre.set("oauth:y", "t")
    caso("remover por prefixo conta e poupa o resto",
         cofre.remover_prefixo("oauth:") == 1 and cofre.chaves() == ["env:hml:token"])
    caso("remover prefixo sem alvo nao grava", cofre.remover_prefixo("nada:") == 0)
    resumo = cofre.resumo()
    caso("resumo diz total e que o arquivo existe", resumo["total"] == 1 and resumo["existe"] and not resumo["erro"])


# ---------------------------------------------------------------------------- disco


def _gravacao(p, caso) -> None:
    p.secao("slug e ordem de chave")
    caso("slug tira acento e simbolo", storage.slug("Ação Rápida! (v2)") == "acao-rapida-v2")
    caso("slug vazio vira item", storage.slug("") == "item" and storage.slug("!!!") == "item")
    caso("slug corta em 60", len(storage.slug("a" * 100)) == 60)
    usados: set = set()
    caso("slug repetido ganha numero",
         [storage.slug("Api", usados) for _ in range(3)] == ["api", "api-2", "api-3"])
    ordenado = storage._ordenar({"b": 1, "items": [1], "type": "x", "a": None, "z": [], "id": "i", "extra": "e"},
                                ["id", "a", "b"])
    caso("ordenar segue a ordem, tira vazio e o que nao e do arquivo",
         (list(ordenado.items()) == [("id", "i"), ("b", 1), ("extra", "e")], ordenado))
    caso("seq torto vira 999", storage._ordem("abc") == 999 and storage._ordem(None) == 999 and storage._ordem("3") == 3)
    caso("lista de mapas descarta o que nao e mapa", storage._mapas([{"a": 1}, "x", 2]) == [{"a": 1}]
         and storage._mapas("texto") == [])
    caso("pares tipados viram texto e nulo fica nulo",
         storage._pares([{"key": 1, "value": True}, "lixo", {"key": "k", "value": None}])
         == [{"key": "1", "value": "true"}, {"key": "k", "value": None}])

    p.secao("gravar e ler o workspace")
    raiz = pasta_nova("storage")
    request_cheio = {
        "id": "r-cheio", "type": "request", "name": "Zeta cheio", "method": "POST", "url": "{{base}}/z",
        "favorite": True, "params": [{"key": "p", "value": "1", "enabled": False}],
        "headers": [{"key": "H", "value": "v"}], "body": {"mode": "json", "raw": '{\n  "a": 1\n}'},
        "auth": {"type": "bearer", "token": "{{tok}}"}, "settings": {"timeout": 9},
        "docs": "linha 1\nlinha 2", "examples": [{"id": "ex-1", "name": "ok", "status": 200}],
        "origin": {"postman": "abc"},
    }
    arvore = {
        "activeEnv": "e-prd", "sortMode": "nome",
        "certificates": [{"host": "x", "file": "c.pfx"}], "caFile": "ca.pem",
        "sftp": [{"id": "s1", "host": "h"}],
        "globals": [{"key": "g", "value": "1"}],
        "environments": [
            {"id": "e-hml", "name": "Homologação", "values": [{"key": "base", "value": "https://hml"}]},
            {"id": "e-prd", "name": "Produção", "values": [{"key": "tok", "value": "SEG-PRD", "secret": True}]},
        ],
        "collections": [{
            "id": "c1", "type": "collection", "name": "Api", "expanded": True,
            "auth": {"type": "basic", "username": "u"}, "variables": [{"key": "v", "value": "1"}],
            "items": [
                request_cheio,
                {"id": "f1", "type": "folder", "name": "Alfa pasta", "expanded": False, "items": [
                    {"id": "r-dentro", "type": "request", "name": "Dentro", "method": "GET", "url": "u",
                     "body": {"mode": "none", "raw": ""}}]},
                {"id": "r-simples", "type": "request", "name": "Alfa simples", "method": "GET", "url": "u2",
                 "body": {"mode": "none", "raw": ""}},
            ],
        }],
    }
    resumo = storage.gravar_workspace(raiz, arvore)
    caso("primeira gravacao escreve e manda o segredo pro cofre", (resumo["escritos"] >= 6 and resumo["segredos"] >= 1, resumo))
    caso("segredo do ambiente nao vai pro yaml",
         "SEG-PRD" not in " ".join(a.read_text(encoding="utf-8") for a in raiz.rglob("*.yaml")))
    lida = storage.ler_workspace(raiz)
    colecao = lida["collections"][0]
    caso("ordem dos itens vem do seq, e nao do nome do arquivo",
         ([n["name"] for n in colecao["items"]] == ["Zeta cheio", "Alfa pasta", "Alfa simples"],
          [n["name"] for n in colecao["items"]]))
    volta = colecao["items"][0]
    campos = ("method", "url", "favorite", "params", "headers", "body", "auth", "settings", "docs", "examples", "origin")
    diferentes = [c for c in campos if volta.get(c) != request_cheio[c]]
    caso("request volta com todos os campos", (not diferentes, diferentes))
    caso("ambientes voltam na ordem, com o segredo do cofre",
         [e["name"] for e in lida["environments"]] == ["Homologação", "Produção"]
         and lida["environments"][1]["values"][0]["value"] == "SEG-PRD")
    caso("settings, globais e estado local voltam",
         (lida["activeEnv"], lida["sortMode"], lida["caFile"], lida["certificates"][0]["host"], lida["sftp"][0]["host"],
          lida["globals"][0]["value"]) == ("e-prd", "nome", "ca.pem", "x", "h", "1"))
    caso("auth e variavel da collection voltam", colecao.get("auth") == {"type": "basic", "username": "u"}
         and colecao["variables"] == [{"key": "v", "value": "1"}])
    caso("pasta aberta e fechada vem do estado local",
         colecao["expanded"] is True and colecao["items"][1]["expanded"] is False)
    caso("nome do arquivo e o slug do nome",
         (raiz / "environments" / "homologacao.yaml").exists() and (raiz / "collections" / "api" / "alfa-pasta" / "_folder.yaml").exists())

    de_novo = storage.gravar_workspace(raiz, storage.ler_workspace(raiz))
    caso("gravar o que acabou de ler nao reescreve nada", (de_novo["escritos"] == 0 and de_novo["apagados"] == 0, de_novo))

    arvore["collections"][0]["items"].pop()
    arvore["collections"][0]["items"][1]["items"] = []
    enxuto = storage.gravar_workspace(raiz, arvore)
    caso("request tirado da arvore sai do disco",
         (not (raiz / "collections" / "api" / "alfa-simples.yaml").exists()
          and not (raiz / "collections" / "api" / "alfa-pasta" / "dentro.yaml").exists() and enxuto["apagados"] >= 2,
          enxuto))
    arvore["collections"][0]["name"] = "Api Nova"
    storage.gravar_workspace(raiz, arvore)
    caso("collection renomeada muda de pasta e a velha some",
         (raiz / "collections" / "api-nova").is_dir() and not (raiz / "collections" / "api").exists())
    avulso = raiz / "notas.yaml"
    avulso.write_text("minha: nota\n", encoding="utf-8")
    storage.gravar_workspace(raiz, arvore)
    caso("arquivo na raiz que nao e do app fica", avulso.exists())

    foto = storage.assinatura(raiz)
    alvo = raiz / "collections" / "api-nova" / "zeta-cheio.yaml"
    caso("assinatura usa caminho relativo com barra", "collections/api-nova/zeta-cheio.yaml" in foto)
    time.sleep(0.02)
    alvo.write_text(alvo.read_text(encoding="utf-8") + "# mexido por fora\n", encoding="utf-8")
    conflito = storage.gravar_workspace(raiz, arvore, foto)
    copias = list((raiz / ".conduit" / "conflitos").rglob("zeta-cheio.yaml"))
    caso("arquivo mexido por fora ganha copia antes de ser regravado",
         ("collections/api-nova/zeta-cheio.yaml" in conflito["conflitos"] and copias
          and "mexido por fora" in copias[0].read_text(encoding="utf-8"), conflito["conflitos"]))

    p.secao("request escrito na mao")
    solto = pasta_nova("request-mao")
    arquivo = solto / "sem-nome.yaml"
    arquivo.write_text("url: https://x\nbody: texto solto\nauth: bearer\nexamples: [1, {name: e}]\n", encoding="utf-8")
    lido = storage._ler_request(arquivo)
    caso("sem nome nem metodo usa o arquivo e GET", lido["name"] == "sem-nome" and lido["method"] == "GET")
    caso("corpo em texto vira raw", lido["body"] == {"mode": "raw", "raw": "texto solto"})
    caso("auth que nao e mapa fica de fora", "auth" not in lido)
    caso("exemplo que nao e mapa sai da lista", lido["examples"] == [{"name": "e"}])
    arquivo.write_text("- lista\n- no lugar do mapa\n", encoding="utf-8")
    caso("arquivo que nao e mapa nao vira request", storage._ler_request(arquivo) is None)
    arquivo.write_bytes("name: Relatório\n".encode("latin-1"))
    caso("arquivo em ANSI nao derruba a leitura", storage._ler_request(arquivo) is None)

    estado = raiz / storage.ESTADO_LOCAL
    estado.write_text("[1, 2]", encoding="utf-8")
    caso("estado local que nao e mapa e ignorado", storage.ler_workspace(raiz)["sortMode"] in ("manual", "nome"))


def _registro(p, caso) -> None:
    p.secao("registro de workspaces")
    ws.ensure_root()
    primeiro = ws.create_workspace("Projeto Um")
    caso("criar da id pelo slug e cria as pastas",
         primeiro["id"] == "projeto-um" and (Path(primeiro["path"]) / ".secrets").is_dir()
         and (Path(primeiro["path"]) / ".gitignore").exists())
    caso("o primeiro vira o ativo", ws.list_workspaces()["active"] == "projeto-um")
    try:
        ws.create_workspace("projeto um")
        caso("mesmo nome e recusado", False)
    except ValueError as erro:
        caso("mesmo nome e recusado, sem falar de id", ("esse nome" in str(erro) and "id" not in str(erro), str(erro)))
    try:
        ws.create_workspace("Projeto-Um!")
        caso("nome que da o mesmo slug cita o outro workspace", False)
    except ValueError as erro:
        caso("nome que da o mesmo slug cita o outro workspace", ("Projeto Um" in str(erro), str(erro)))
    caso("id livre pula o que ja existe", ws.id_livre("Projeto Um") == "projeto-um-2")
    (ws.WORKSPACES_DIR / "projeto-um-2").mkdir()
    (ws.WORKSPACES_DIR / "projeto-um-2" / "settings.yaml").write_text("schemaVersion: 1\n", encoding="utf-8")
    caso("id livre pula pasta que saiu da lista", ws.id_livre("Projeto Um") == "projeto-um-3")
    caso("escrever o gitignore nao sobrescreve", ws.escrever_gitignore(Path(primeiro["path"])) is False)

    segundo = ws.create_workspace("Segundo", color="#123456")
    caso("cor escolhida vale", segundo["color"] == "#123456")
    caso("renomear troca so o nome", ws.rename_workspace("segundo", "Outro Nome")["id"] == "segundo"
         and ws.get_workspace("segundo")["name"] == "Outro Nome")
    caso("trocar a cor grava", ws.set_color("segundo", "#3ecf8e")["color"] == "#3ecf8e")
    for funcao, args in ((ws.rename_workspace, ("nao-existe", "x")), (ws.set_color, ("nao-existe", "#fff")),
                         (ws.get_workspace, ("nao-existe",)), (ws.delete_workspace, ("nao-existe",))):
        try:
            funcao(*args)
            caso(f"{funcao.__name__} de workspace que nao existe avisa", False)
        except KeyError:
            caso(f"{funcao.__name__} de workspace que nao existe avisa", True)

    registro = json.loads(ws.REGISTRY.read_text(encoding="utf-8"))
    registro["workspaces"][1]["color"] = "#A78BFA"
    registro["workspaces"][1]["path"] = str(ws.ROOT / "lugar-antigo" / "segundo")
    ws.REGISTRY.write_text(json.dumps(registro), encoding="utf-8")
    caso("cor aposentada troca pela substituta e grava",
         ws.list_workspaces()["workspaces"][1]["color"] == "#8e8e95"
         and "#A78BFA" not in ws.REGISTRY.read_text(encoding="utf-8"))
    caso("caminho que sumiu e consertado pro lugar certo",
         Path(ws.get_workspace("segundo")["path"]) == ws.WORKSPACES_DIR / "segundo"
         and "lugar-antigo" not in ws.REGISTRY.read_text(encoding="utf-8"))

    antes = ws.get_workspace("segundo")["lastOpenedAt"]
    ws.set_active("segundo")
    caso("abrir marca o ativo e a hora", ws.list_workspaces()["active"] == "segundo"
         and ws.get_workspace("segundo")["lastOpenedAt"] and antes is None)

    raiz = Path(primeiro["path"])
    storage.gravar_workspace(raiz, {"activeEnv": "e1", "environments": [{"id": "e1", "name": "hml", "values": [
        {"key": "tok", "value": "SEG-DUP", "secret": True}]}], "collections": [
        {"id": "c", "type": "collection", "name": "Api", "items": []}]})
    (raiz / "history" / "2026-01-01.jsonl").write_text("{}\n", encoding="utf-8")
    copia = ws.duplicate_workspace("projeto-um", "Copia")
    destino = Path(copia["path"])
    caso("duplicar leva collection, ambiente e o estado local",
         (destino / "collections" / "api").is_dir() and (destino / "environments" / "hml.yaml").exists()
         and (destino / storage.ESTADO_LOCAL).exists())
    caso("duplicar nao leva cofre nem historico",
         not list((destino / "history").glob("*.jsonl")) and vault.Vault(destino).get("env:e1:tok") == "")
    caso("e a copia abre com o ambiente de antes", ws.read_tree(copia["id"])["activeEnv"] == "e1")

    fora = ws.create_workspace("Fora da lista")
    ws.delete_workspace(fora["id"])
    try:
        ws.duplicate_workspace("projeto-um", "Fora da lista")
        caso("duplicar em cima de pasta de workspace fora da lista recusa", False)
    except ValueError as erro:
        caso("duplicar em cima de pasta de workspace fora da lista recusa", "saiu da" in str(erro))

    ws.set_active("segundo")
    saida = ws.delete_workspace("segundo", apagar_arquivos=True)
    caso("excluir com arquivos move pra lixeira do app",
         (saida["lixeira"] and Path(saida["lixeira"]).is_dir() and not (ws.WORKSPACES_DIR / "segundo").exists(),
          saida["lixeira"]))
    caso("excluir o ativo passa o ativo pro primeiro da lista", ws.list_workspaces()["active"] == "projeto-um")

    antigo = ws.create_workspace("Migrado")
    pasta = Path(antigo["path"])
    (pasta / "settings.yaml").unlink()
    (pasta / "tree.json").write_text(json.dumps({"activeEnv": None, "environments": [], "collections": [
        {"id": "c-velha", "type": "collection", "name": "Da versao velha", "items": []}]}), encoding="utf-8")
    migrada = ws.read_tree("migrado")
    caso("tree.json antigo vira YAML e fica de backup",
         [c["name"] for c in migrada["collections"]] == ["Da versao velha"]
         and (pasta / "tree.json.migrado").exists() and not (pasta / "tree.json").exists())

    p.secao("preferencias")
    caso("sem arquivo volta o padrao sem criar nada",
         ws.read_preferences() == ws.PREFERENCES_PADRAO and not ws.PREFERENCES.exists())
    gravadas = ws.write_preferences(tema="claro", invasora="x")
    caso("gravar ignora chave desconhecida", gravadas["tema"] == "claro" and "invasora" not in gravadas)
    caso("e le de volta", ws.read_preferences()["tema"] == "claro")
    ws.PREFERENCES.write_text("[1, 2]", encoding="utf-8")
    caso("arquivo que nao e mapa volta o padrao, sem derrubar a abertura",
         lambda: (ws.read_preferences() == ws.PREFERENCES_PADRAO, ws.read_preferences()))
    ws.PREFERENCES.write_bytes('{"tema": "claro, versão"}'.encode("latin-1"))
    caso("arquivo fora de UTF-8 volta o padrao, sem derrubar a abertura",
         lambda: (ws.read_preferences() == ws.PREFERENCES_PADRAO, ws.read_preferences()))
    ws.PREFERENCES.unlink()


def _certificados(p, caso) -> None:
    p.secao("certificado cliente")
    Cert = certs.Certificado
    caso("host exato casa sem ligar pra caixa", Cert("API.exemplo", "").combina("https://api.EXEMPLO/x"))
    caso("curinga casa o dominio e os filhos",
         Cert("*.exemplo.com", "").combina("https://exemplo.com") and Cert("*.exemplo.com", "").combina("https://a.b.exemplo.com"))
    caso("curinga nao casa dominio que so termina igual", not Cert("*.exemplo.com", "").combina("https://malexemplo.com"))
    caso("host vazio nao casa nada", not Cert("", "").combina("https://x") and not Cert("x", "").combina("sem-host"))
    arvore = {"certificates": [{"host": "api", "file": "a.pfx", "enabled": False},
                               {"host": "api", "file": "b.pfx"}, {"host": "api", "file": "c.pfx"}]}
    caso("o primeiro ativo que casa e o escolhido", certs.para_url(arvore, "https://api/x").arquivo == "b.pfx")
    caso("listar entende enabled", [c.ativo for c in certs.listar(arvore)] == [False, True, True])

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID

    chave = ec.generate_private_key(ec.SECP256R1())
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "cliente-do-teste")])
    agora = datetime.now(timezone.utc)
    certificado = (x509.CertificateBuilder().subject_name(nome).issuer_name(nome).public_key(chave.public_key())
                   .serial_number(x509.random_serial_number()).not_valid_before(agora - timedelta(days=1))
                   .not_valid_after(agora + timedelta(days=30)).sign(chave, hashes.SHA256()))
    pasta = pasta_nova("certs")
    pfx = pasta / "cliente.pfx"
    pfx.write_bytes(pkcs12.serialize_key_and_certificates(
        b"c", chave, certificado, None, serialization.BestAvailableEncryption(b"senha-pfx")))
    pem = pasta / "cliente.pem"
    pem.write_bytes(certificado.public_bytes(serialization.Encoding.PEM))

    visto = certs.inspecionar(str(pfx), "senha-pfx")
    caso("inspecionar le dono, validade e dias que faltam",
         (visto["erro"] == "" and "cliente-do-teste" in visto["dono"] and visto["dias"] in (29, 30), visto))
    caso("inspecionar um PEM tambem funciona", "cliente-do-teste" in certs.inspecionar(str(pem), "").get("dono", ""))
    caso("senha errada vira erro legivel", certs.inspecionar(str(pfx), "errada")["erro"].startswith("nao consegui ler"))
    caso("arquivo que nao existe avisa", certs.inspecionar(str(pasta / "x.pfx"), "")["erro"] == "arquivo nao encontrado")
    caso("descrever mostra dono e validade", "vale ate" in certs.descrever(str(pfx), "senha-pfx")
         and certs.descrever(str(pasta / "x.pfx"), "") == "arquivo nao encontrado")
    contexto, temporario = certs.contexto_ssl(Cert("x", str(pfx)), "senha-pfx", verificar=False)
    caso("contexto do pfx sobe sem verificar e sem deixar o PEM",
         contexto.verify_mode == 0 and not contexto.check_hostname and not Path(temporario).exists())
    try:
        certs.contexto_ssl(Cert("x", str(pasta / "nao.pfx")), "")
        caso("pfx sumido avisa", False)
    except FileNotFoundError:
        caso("pfx sumido avisa", True)
    caso("descartar aceita nulo e arquivo que nao existe",
         certs.descartar(None) is None and certs.descartar(str(pasta / "nao.pem")) is None)


# ---------------------------------------------------------------------------- formatos


def _postman(p, caso) -> None:
    p.secao("Postman")
    pasta = pasta_nova("postman")
    colecao = {
        "info": {"name": "Loja", "schema": postman.SCHEMA, "_postman_id": "pm-1"},
        "auth": {"type": "bearer", "bearer": [{"key": "token", "value": "{{tok}}"}]},
        "variable": [{"key": "zero", "value": 0}, {"key": "ligado", "value": True},
                     {"key": "off", "value": "x", "disabled": True}, {"value": "sem chave"}],
        "item": [
            {"name": "Pedidos", "auth": {"type": "basic", "basic": [{"key": "username", "value": "u"}]}, "item": [
                {"name": "Listar", "event": [{"listen": "test"}], "request": {
                    "method": "get", "description": "lista tudo",
                    "url": {"raw": "{{base}}/pedidos?pagina=1&off=2", "query": [
                        {"key": "pagina", "value": "1"}, {"key": "off", "value": "2", "disabled": True}]},
                    "header": [{"key": "Accept", "value": "application/json"},
                               {"key": "X-Off", "value": "1", "disabled": True}]}},
                {"name": "Criar", "request": {"method": "POST", "url": "{{base}}/pedidos",
                                              "body": {"mode": "raw", "raw": "[1]"},
                                              "auth": {"type": "apikey", "apikey": [
                                                  {"key": "key", "value": "k"}, {"key": "in", "value": "query"}]}}},
            ]},
            {"name": "Form", "request": {"method": "POST", "url": {"protocol": "http", "host": ["api", "local"],
                                                                     "path": ["v1", "x"]},
                                         "body": {"mode": "urlencoded", "urlencoded": [
                                             {"key": "a", "value": "1"}, {"key": "b", "value": "2", "disabled": True}]},
                                         "auth": {"type": "noauth"}}},
            {"name": "Multipart", "request": {"method": "POST", "url": "https://x",
                                              "body": {"mode": "formdata", "formdata": [
                                                  {"key": "t", "value": "v"}, {"key": "f", "type": "file", "src": "a"}]}}},
            {"name": "Graph", "request": {"method": "POST", "url": "https://x", "body": {"mode": "graphql"}}},
            {"name": "Texto", "request": "https://so-texto"},
            {"name": "Oauth", "request": {"url": "https://x", "auth": {"type": "oauth2", "oauth2": [
                {"key": "accessTokenUrl", "value": "https://t"}, {"key": "clientId", "value": "c"}]}}},
            {"name": "Sem request"},
        ],
    }
    arquivo = pasta / "loja.postman_collection.json"
    arquivo.write_text(json.dumps(colecao), encoding="utf-8")
    resultado = postman.importar(arquivo)
    col = resultado.collections[0]
    itens = {n["name"]: n for n in col["items"]}
    listar, criar = col["items"][0]["items"]
    caso("collection traz nome, auth e origem",
         col["name"] == "Loja" and col["auth"] == {"type": "bearer", "token": "{{tok}}"} and col["origin"] == {"postman": "pm-1"})
    caso("variavel numerica e booleana vira texto, desligada fica desligada",
         ([(v["key"], v["value"], v["enabled"]) for v in col["variables"]]
          == [("zero", "0", True), ("ligado", "true", True), ("off", "x", False)], col["variables"]))
    caso("pasta vira folder com a auth dela", col["items"][0]["type"] == "folder"
         and col["items"][0]["auth"]["type"] == "basic")
    caso("url com raw sai sem a query, que vira params",
         (listar["url"] == "{{base}}/pedidos"
          and [(q["key"], q["enabled"]) for q in listar["params"]] == [("pagina", True), ("off", False)], listar["params"]))
    caso("header desligado continua, desligado", [h["enabled"] for h in listar["headers"]] == [True, False])
    caso("metodo em maiusculo e descricao vira docs", listar["method"] == "GET" and listar["docs"] == "lista tudo")
    caso("corpo que comeca com colchete e json", criar["body"] == {"mode": "json", "raw": "[1]"})
    caso("api key com in query", criar["auth"] == {"type": "apikey", "key": "k", "value": "", "in": "query"})
    caso("url em pedacos e remontada", itens["Form"]["url"] == "http://api.local/v1/x")
    caso("urlencoded vira form sem o desligado", itens["Form"]["body"] == {"mode": "form", "raw": "a=1"})
    caso("noauth vira sem auth", itens["Form"]["auth"] == {"type": "none"})
    caso("formdata sem o arquivo, e avisa", itens["Multipart"]["body"]["raw"] == "t=v"
         and any("multipart" in a for a in resultado.avisos))
    caso("graphql avisa e vem vazio", itens["Graph"]["body"]["mode"] == "none"
         and any("graphql" in a for a in resultado.avisos))
    caso("request em texto vira GET", itens["Texto"]["method"] == "GET" and itens["Texto"]["url"] == "https://so-texto")
    caso("oauth2 le url e cliente", itens["Oauth"]["auth"]["tokenUrl"] == "https://t" and itens["Oauth"]["auth"]["clientId"] == "c")
    caso("item sem request nem filhos fica de fora", "Sem request" not in itens)
    caso("script avisa que nao veio", any("scripts de Listar" in a for a in resultado.avisos))

    so_raw = pasta / "so-raw.json"
    so_raw.write_text(json.dumps({"info": {"name": "R", "schema": postman.SCHEMA}, "item": [
        {"name": "r", "request": {"url": {"raw": "https://x/a?b=1&c=2"}}}]}), encoding="utf-8")
    lido = postman.importar(so_raw).collections[0]["items"][0]
    caso("url com raw e sem a lista query nao perde a query",
         (("b=1" in lido["url"] or any(q["key"] == "b" for q in lido["params"]))
          and ("c=2" in lido["url"] or any(q["key"] == "c" for q in lido["params"])), (lido["url"], lido["params"])))

    ambiente = pasta / "hml.postman_environment.json"
    ambiente.write_text(json.dumps({"name": "hml", "_postman_variable_scope": "environment", "values": [
        {"key": "porta", "value": 8080}, {"key": "tok", "value": "x", "type": "secret"},
        {"key": "off", "value": "1", "enabled": False}]}), encoding="utf-8")
    env = postman.importar(ambiente).environments[0]
    caso("environment traz numero como texto, secreto e desligado",
         [(v["key"], v["value"], v["secret"], v["enabled"]) for v in env["values"]]
         == [("porta", "8080", False, True), ("tok", "x", True, True), ("off", "1", False, False)])

    caso("deteccao: schema v2 e certeza", postman.detectar(arquivo) == 1.0)
    caso("deteccao: environment", postman.detectar(ambiente) == 0.9)
    sem_schema = pasta / "sem.json"
    sem_schema.write_text('{"info": {}, "item": []}', encoding="utf-8")
    caso("deteccao: info e item sem schema", postman.detectar(sem_schema) == 0.8)
    torto = pasta / "torto.json"
    torto.write_text("{nao e json", encoding="utf-8")
    caso("deteccao: json torto, pasta e outra extensao dao zero",
         postman.detectar(torto) == 0 and postman.detectar(pasta) == 0 and postman.detectar(pasta / "x.txt") == 0)
    caso("arquivo torto vira erro legivel", postman.importar(torto).erro.startswith("nao consegui ler"))

    p.secao("Postman, exportar")
    nossa = {"name": "Nossa", "auth": {"type": "apikey", "key": "k", "value": "v", "in": "header"},
             "variables": [{"key": "pub", "value": "1"}, {"key": "seg", "value": "S", "secret": True}],
             "items": [
                 {"type": "folder", "name": "P", "auth": {"type": "basic", "username": "u", "password": "s"}, "items": [
                     {"type": "request", "name": "Form", "method": "POST", "url": "https://x/f",
                      "params": [{"key": "a", "value": "1"}, {"key": "b", "value": "2", "enabled": False}],
                      "headers": [{"key": "H", "value": "v", "enabled": False}],
                      "body": {"mode": "form", "raw": "campo=&outro=2"}, "docs": "doc",
                      "auth": {"type": "oauth2", "tokenUrl": "https://t", "clientId": "c"}},
                 ]},
                 {"type": "request", "name": "Json", "method": "PUT", "url": "https://x/j",
                  "body": {"mode": "json", "raw": '{"a":1}'}, "auth": {"type": "bearer", "token": "t"}},
             ]}
    destino = postman.exportar_collection(nossa, pasta / "saida" / "nossa.json")
    exportada = json.loads(destino.read_text(encoding="utf-8"))
    form = exportada["item"][0]["item"][0]["request"]
    caso("query ligada vai na url e a desligada so na lista",
         form["url"]["raw"] == "https://x/f?a=1" and form["url"]["query"][1]["disabled"] is True)
    caso("campo de form vazio nao some no export",
         ([c["key"] for c in form["body"]["urlencoded"]] == ["campo", "outro"], form["body"]["urlencoded"]))
    caso("docs vira description e header desligado vai marcado",
         form["description"] == "doc" and form["header"][0]["disabled"] is True)
    caso("auth vai no formato do Postman",
         exportada["auth"]["type"] == "apikey" and exportada["item"][0]["auth"]["type"] == "basic"
         and form["auth"]["oauth2"][0] == {"key": "accessTokenUrl", "value": "https://t"})
    caso("variavel secreta da collection sai sem valor",
         {v["key"]: v["value"] for v in exportada["variable"]} == {"pub": "1", "seg": ""})
    com_segredo = json.loads(postman.exportar_collection(nossa, pasta / "c.json", com_segredo=True).read_text(encoding="utf-8"))
    caso("com_segredo leva o valor", {v["key"]: v["value"] for v in com_segredo["variable"]}["seg"] == "S")
    de_volta = postman.importar(destino).collections[0]
    json_volta = de_volta["items"][1]
    caso("ida e volta mantem corpo json, auth e metodo",
         json_volta["body"] == {"mode": "json", "raw": '{"a":1}'} and json_volta["auth"] == {"type": "bearer", "token": "t"}
         and json_volta["method"] == "PUT")
    env_saida = postman.exportar_environment({"id": "e", "name": "hml", "values": [
        {"key": "a", "value": "1"}, {"key": "s", "value": "S", "secret": True}, {"key": "d", "value": "", "enabled": False}]},
        pasta / "env.json")
    valores = json.loads(env_saida.read_text(encoding="utf-8"))["values"]
    caso("environment exportado esconde o secreto e marca o tipo",
         [(v["key"], v["value"], v["type"], v["enabled"]) for v in valores]
         == [("a", "1", "default", True), ("s", "", "secret", True), ("d", "", "default", False)])


def _insomnia(p, caso) -> None:
    p.secao("Insomnia")
    pasta = pasta_nova("insomnia")
    recursos = [
        {"_id": "wrk_1", "_type": "workspace", "parentId": None, "name": "Loja"},
        {"_id": "fld_1", "_type": "request_group", "parentId": "wrk_1", "name": "Pedidos",
         "authentication": {"type": "bearer", "token": "{{ tok }}"}},
        {"_id": "req_1", "_type": "request", "parentId": "fld_1", "name": "Listar", "method": "get",
         "url": "https://x/pedidos?pagina=1", "parameters": [{"name": "ordem", "value": "desc"},
                                                              {"name": "off", "value": "1", "disabled": True}],
         "headers": [{"name": "Accept", "value": "json"}, {"name": "X", "value": "1", "disabled": True}],
         "body": {"mimeType": "application/json", "text": '{"a": 1}'},
         "authentication": {"type": "basic", "username": "u", "password": "s", "disabled": True}},
        {"_id": "req_2", "_type": "request", "parentId": "wrk_1", "name": "Form", "method": "POST", "url": "https://x/f",
         "body": {"mimeType": "application/x-www-form-urlencoded",
                  "params": [{"name": "a", "value": "1"}, {"name": "b", "value": "2", "disabled": True}]},
         "authentication": {"type": "apikey", "key": "k", "value": "v", "addTo": "header"}},
        {"_id": "req_3", "_type": "request", "parentId": "wrk_1", "name": "Graph", "url": "https://x/g",
         "body": {"mimeType": "application/graphql", "text": "{ a }"}},
        {"_id": "env_1", "_type": "environment", "parentId": "wrk_1", "name": "Base",
         "data": {"base": "https://x", "debug": True, "porta": 8080, "vazio": None}},
        {"_id": "env_2", "_type": "environment", "parentId": "env_1", "name": "Torto", "data": ["nao", "mapa"]},
    ]
    arquivo = pasta / "insomnia.json"
    arquivo.write_text(json.dumps({"_type": "export", "__export_format": 4, "resources": recursos}), encoding="utf-8")
    resultado = insomnia.importar(arquivo)
    col = resultado.collections[0]
    pedidos, form, graph = col["items"]
    listar = pedidos["items"][0]
    caso("workspace vira collection e request_group vira pasta com auth",
         col["type"] == "collection" and col["name"] == "Loja" and pedidos["type"] == "folder"
         and pedidos["auth"] == {"type": "bearer", "token": "{{ tok }}"})
    caso("query da url soma com os parameters",
         [(q["key"], q["enabled"]) for q in listar["params"]] == [("ordem", True), ("off", False), ("pagina", True)]
         and listar["url"] == "https://x/pedidos")
    caso("auth desligada vira sem auth", listar["auth"] == {"type": "none"})
    caso("corpo json pelo mimeType", listar["body"] == {"mode": "json", "raw": '{"a": 1}'})
    caso("form sem o desligado e api key com addTo", form["body"] == {"mode": "form", "raw": "a=1"}
         and form["auth"]["in"] == "header")
    caso("graphql vem como texto e avisa", graph["body"]["mode"] == "raw" and resultado.avisos)
    valores = {v["key"]: v["value"] for v in resultado.environments[0]["values"]}
    caso("ambiente com valor tipado vira texto do jeito que se escreve",
         (valores == {"base": "https://x", "debug": "true", "porta": "8080", "vazio": ""}, valores))
    caso("ambiente com data que nao e mapa fica de fora", len(resultado.environments) == 1)
    caso("deteccao: export e certeza", insomnia.detectar(arquivo) == 1.0)
    em_yaml = pasta / "insomnia.yaml"
    em_yaml.write_text("_type: export\n__export_format: 4\nresources: []\n", encoding="utf-8")
    caso("deteccao e import em YAML", insomnia.detectar(em_yaml) == 1.0 and insomnia.importar(em_yaml).erro is None)
    caso("sem a marca de export nao e Insomnia", insomnia.detectar(pasta_nova("x")) == 0.0)

    sem_raiz = pasta / "sem-workspace.json"
    sem_raiz.write_text(json.dumps({"__export_format": 4, "resources": [
        {"_id": "fld_a", "_type": "request_group", "parentId": None, "name": "Solta"},
        {"_id": "req_a", "_type": "request", "parentId": "fld_a", "name": "R", "url": "https://x"}]}), encoding="utf-8")
    caso("sem workspace a pasta raiz vira collection",
         [c["name"] for c in insomnia.importar(sem_raiz).collections] == ["Solta"] and insomnia.detectar(sem_raiz) == 0.6)

    p.secao("Insomnia, exportar e voltar")
    nossa = {"name": "Nossa", "items": [
        {"type": "folder", "name": "P", "auth": {"type": "basic", "username": "u", "password": "s"}, "items": [
            {"type": "request", "name": "Form", "method": "POST", "url": "https://x/f",
             "params": [{"key": "a", "value": "1", "enabled": False}], "body": {"mode": "form", "raw": "vazio=&b=2"}}]},
        {"type": "request", "name": "Json", "method": "PUT", "url": "https://x/j", "docs": "d",
         "headers": [{"key": "H", "value": "v"}], "body": {"mode": "json", "raw": "{}"},
         "auth": {"type": "oauth2", "tokenUrl": "https://t", "clientId": "c"}}]}
    arvore = {"environments": [{"name": "hml", "values": [{"key": "a", "value": "1"},
                                                          {"key": "s", "value": "S", "secret": True}]}]}
    saida = insomnia.exportar(arvore, [nossa], pasta / "saida.json")
    dados = json.loads(saida.read_text(encoding="utf-8"))
    por_nome = {r.get("name"): r for r in dados["resources"]}
    caso("export achata a arvore amarrando pelo parentId",
         por_nome["Form"]["parentId"] == por_nome["P"]["_id"] and por_nome["P"]["parentId"] == por_nome["Nossa"]["_id"])
    caso("campo de form vazio nao some no export",
         ([c["name"] for c in por_nome["Form"]["body"]["params"]] == ["vazio", "b"], por_nome["Form"]["body"]))
    caso("ambiente exportado esconde o secreto", por_nome["hml"]["data"] == {"a": "1", "s": ""})
    volta = insomnia.importar(saida)
    json_volta = volta.collections[0]["items"][1]
    caso("ida e volta mantem metodo, corpo, header, docs e auth",
         json_volta["method"] == "PUT" and json_volta["body"] == {"mode": "json", "raw": "{}"}
         and json_volta["headers"][0]["key"] == "H" and json_volta["docs"] == "d"
         and json_volta["auth"]["tokenUrl"] == "https://t")
    caso("e o param desligado continua desligado",
         volta.collections[0]["items"][0]["items"][0]["params"] == [{"key": "a", "value": "1", "enabled": False}])


def _bruno(p, caso) -> None:
    p.secao("Bruno")
    pasta = pasta_nova("bruno")
    colecao = pasta / "loja"
    (colecao / "pedidos").mkdir(parents=True)
    (colecao / "environments").mkdir()
    (colecao / "bruno.json").write_text('{"version": "1", "name": "Loja Bruno", "type": "collection"}', encoding="utf-8")
    (colecao / "pedidos" / "folder.bru").write_text("meta {\n  name: Pedidos da Loja\n}\n", encoding="utf-8")
    (colecao / "pedidos" / "b-listar.bru").write_text(
        "meta {\n  name: Listar\n  type: http\n  seq: 1\n}\n\n"
        "get {\n  url: {{base}}/pedidos?pagina=1&ordem=desc\n  body: none\n  auth: bearer\n}\n\n"
        "params:query {\n  pagina: 1\n  ordem: desc\n  ~limite: 10\n}\n\n"
        "headers {\n  Accept: application/json\n  ~X-Off: 1\n}\n\n"
        "auth:bearer {\n  token: {{tok}}\n}\n\n"
        "docs {\n  Lista os pedidos\n}\n\n"
        "script:pre-request {\n  bru.setVar('a', 1)\n}\n", encoding="utf-8")
    (colecao / "pedidos" / "a-criar.bru").write_text(
        "meta {\n  name: Criar\n  seq: 2\n}\n\npost {\n  url: {{base}}/pedidos\n}\n\n"
        'body:json {\n  {\n    "itens": [{"id": 1}]\n  }\n}\n\n'
        "auth:apikey {\n  key: X-Chave\n  value: {{chave}}\n  placement: header\n}\n", encoding="utf-8")
    (colecao / "form.bru").write_text(
        "meta {\n  name: Form\n  seq: x\n}\n\nput {\n  url: https://x/f\n}\n\n"
        "body:form-urlencoded {\n  a: 1\n  ~b: 2\n}\n\nauth:basic {\n  username: u\n  password: s\n}\n", encoding="utf-8")
    (colecao / "environments" / "hml.bru").write_text(
        "vars {\n  base: https://hml\n  ~off: 1\n}\nvars:secret [\n  tok,\n  chave\n]\n", encoding="utf-8")

    resultado = bruno.importar(colecao)
    col = resultado.collections[0]
    por_nome = {n["name"]: n for n in col["items"]}
    pedidos = por_nome["Pedidos da Loja"]
    listar, criar = pedidos["items"]
    caso("nome da collection vem do bruno.json e o da pasta do folder.bru",
         col["name"] == "Loja Bruno" and "Pedidos da Loja" in por_nome)
    caso("ordem vem do seq, e nao do nome do arquivo", [n["name"] for n in pedidos["items"]] == ["Listar", "Criar"])
    caso("query na url e no bloco params:query nao duplica",
         ([(q["key"], q["value"], q["enabled"]) for q in listar["params"]]
          == [("pagina", "1", True), ("ordem", "desc", True), ("limite", "10", False)], listar["params"]))
    caso("url sai sem a query", listar["url"] == "{{base}}/pedidos")
    caso("header com til fica desligado", [(h["key"], h["enabled"]) for h in listar["headers"]]
         == [("Accept", True), ("X-Off", False)])
    caso("auth bearer e docs", listar["auth"] == {"type": "bearer", "token": "{{tok}}"} and listar["docs"] == "Lista os pedidos")
    caso("corpo json com chave aninhada inteiro", json.loads(criar["body"]["raw"]) == {"itens": [{"id": 1}]}
         and criar["method"] == "POST")
    caso("api key com placement", criar["auth"] == {"type": "apikey", "key": "X-Chave", "value": "{{chave}}", "in": "header"})
    caso("form sem o desligado e auth basic",
         por_nome["Form"]["body"] == {"mode": "form", "raw": "a=1"} and por_nome["Form"]["auth"]["username"] == "u")
    caso("script avisa", any("scripts" in a for a in resultado.avisos))
    env = resultado.environments[0]
    caso("ambiente com var desligada e secretas so com o nome",
         [(v["key"], v["value"], v["enabled"], v.get("secret", False)) for v in env["values"]]
         == [("base", "https://hml", True, False), ("off", "1", False, False),
             ("tok", "", True, True), ("chave", "", True, True)])
    caso("deteccao: pasta com bruno.json, pasta com .bru e arquivo .bru",
         bruno.detectar(colecao) == 1.0 and bruno.detectar(colecao / "pedidos") == 0.8
         and bruno.detectar(colecao / "form.bru") == 0.9 and bruno.detectar(pasta_nova("vazia")) == 0.0)
    avulso = bruno.importar(colecao / "form.bru")
    caso("arquivo .bru sozinho vira collection de um request",
         avulso.collections[0]["name"] == "form" and avulso.collections[0]["items"][0]["name"] == "Form"
         and "_seq" not in avulso.collections[0]["items"][0])

    p.secao("Bruno, exportar e voltar")
    nossa = {"name": "Nossa", "items": [
        {"type": "folder", "name": "Pasta", "items": [
            {"type": "request", "name": "Um", "method": "PATCH", "url": "{{base}}/um",
             "params": [{"key": "a", "value": "1"}, {"key": "b", "value": "2", "enabled": False}],
             "headers": [{"key": "H", "value": "v", "enabled": False}], "body": {"mode": "form", "raw": "vazio=&c=3"},
             "auth": {"type": "basic", "username": "u", "password": "p"}, "docs": "doc do um"}]},
        {"type": "request", "name": "Dois", "method": "POST", "url": "https://x", "body": {"mode": "raw", "raw": "texto"},
         "auth": {"type": "apikey", "key": "k", "value": "v", "in": "query"}}]}
    arvore = {"environments": [{"name": "hml", "values": [{"key": "a", "value": "1"},
                                                          {"key": "s", "value": "S", "secret": True}]}]}
    destino = bruno.exportar(arvore, [nossa], pasta / "saida")
    volta = bruno.importar(destino)
    caso("pasta e request voltam na ordem do export",
         ([n["name"] for n in volta.collections[0]["items"]] == ["Pasta", "Dois"],
          [n["name"] for n in volta.collections[0]["items"]]))
    por_nome = {n["name"]: n for n in volta.collections[0]["items"]}
    um = por_nome["Pasta"]["items"][0]
    caso("ida e volta mantem metodo, params, header desligado e docs",
         um["method"] == "PATCH" and [(q["key"], q["enabled"]) for q in um["params"]] == [("a", True), ("b", False)]
         and um["headers"][0]["enabled"] is False and um["docs"] == "doc do um")
    caso("campo de form vazio nao some no export",
         (um["body"] == {"mode": "form", "raw": "vazio=&c=3"}, um["body"]))
    dois = por_nome["Dois"]
    caso("corpo de texto e api key voltam", dois["body"] == {"mode": "raw", "raw": "texto"} and dois["auth"]["in"] == "query")
    caso("segredo do ambiente volta so com o nome",
         [(v["key"], v["value"]) for v in volta.environments[0]["values"]] == [("a", "1"), ("s", "")])
    varias = bruno.exportar(arvore, [dict(nossa, name="Mesmo nome"), dict(nossa, name="Mesmo-Nome")], pasta / "varias")
    caso("duas collections de slug igual ficam em pastas separadas",
         (varias / "mesmo-nome").is_dir() and (varias / "mesmo-nome-2").is_dir())


def _openapi(p, caso) -> None:
    p.secao("OpenAPI")
    pasta = pasta_nova("openapi")
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "Pets"},
        "servers": [{"url": "https://pets.exemplo/v1"}],
        "components": {
            "parameters": {"Limite": {"name": "limite", "in": "query", "required": True, "schema": {"type": "integer"}}},
            "schemas": {"Pet": {"type": "object", "properties": {
                "nome": {"type": "string", "example": "Rex"}, "idade": {"type": "integer"},
                "vacinado": {"type": "boolean"}, "nascido": {"type": "string", "format": "date"},
                "tags": {"type": "array", "items": {"type": "string", "enum": ["a", "b"]}}}}},
            "securitySchemes": {"jwt": {"type": "http", "scheme": "bearer"}},
        },
        "paths": {
            "/pets/{petId}": {
                "parameters": [{"name": "X-Tenant", "in": "header", "schema": {"type": "string", "default": "t1"}}],
                "get": {"tags": ["pets"], "operationId": "lerPet", "summary": "Ler pet", "description": "um pet",
                        "parameters": [{"$ref": "#/components/parameters/Limite"},
                                       {"name": "ativo", "in": "query", "schema": {"type": "boolean"}}]},
                "put": {"tags": ["pets"], "requestBody": {"content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/Pet"}}}}},
            },
            "/lojas": {"post": {"tags": ["lojas"], "requestBody": {"content": {
                "application/x-www-form-urlencoded": {"example": {"nome": "Centro", "aberta": 1}}}}}},
            "/sem-metodo": {"summary": "so texto", "parameters": []},
        },
    }
    arquivo = pasta / "pets.json"
    arquivo.write_text(json.dumps(spec), encoding="utf-8")
    resultado = openapi.importar(arquivo)
    col = resultado.collections[0]
    pastas = {n["name"]: n for n in col["items"]}
    ler, trocar = pastas["pets"]["items"]
    caso("uma pasta por tag", set(pastas) == {"pets", "lojas"})
    caso("servidor vira baseUrl e parametro de caminho vira variavel",
         ler["url"] == "{{baseUrl}}/pets/{{petId}}"
         and {v["key"]: v["value"] for v in col["variables"]}.get("baseUrl") == "https://pets.exemplo/v1"
         and any(v["key"] == "petId" for v in col["variables"]))
    caso("summary vira nome e operationId vai pra docs", ler["name"] == "Ler pet"
         and ler["docs"].startswith("operationId: lerPet") and "um pet" in ler["docs"])
    caso("parametro por $ref e obrigatorio sai ligado, opcional desligado",
         [(q["key"], q["enabled"]) for q in ler["params"]] == [("limite", True), ("ativo", False)])
    caso("booleano de exemplo sai como se escreve na query",
         ([q["value"] for q in ler["params"]] == ["0", "false"], [q["value"] for q in ler["params"]]))
    caso("parametro comum do caminho vira header com o default", ler["headers"] == [
        {"key": "X-Tenant", "value": "t1", "enabled": True}])
    corpo = json.loads(trocar["body"]["raw"])
    caso("corpo inventado a partir do esquema",
         (corpo == {"nome": "Rex", "idade": 0, "vacinado": False, "nascido": "2026-01-01", "tags": ["a"]}, corpo))
    caso("e o Content-Type do corpo vira header",
         {"key": "Content-Type", "value": "application/json", "enabled": True} in trocar["headers"])
    loja = pastas["lojas"]["items"][0]
    caso("corpo urlencoded vira form", loja["body"] == {"mode": "form", "raw": "nome=Centro&aberta=1"}
         and loja["name"] == "POST /lojas")
    caso("seguranca bearer vira auth da collection com token secreto",
         col["auth"] == {"type": "bearer", "token": "{{token}}"}
         and any(v["key"] == "token" and v.get("secret") for v in col["variables"]))

    swagger = pasta / "swagger.yaml"
    swagger.write_text(
        "swagger: '2.0'\ninfo: {title: Velha}\nhost: api.velha\nbasePath: /v2\nschemes: [http]\n"
        "securityDefinitions:\n  chave: {type: apiKey, name: X-Key, in: header}\n"
        "paths:\n  /itens:\n    post:\n      parameters:\n        - in: body\n          name: corpo\n"
        "          schema: {type: object, properties: {qtd: {type: number}}}\n", encoding="utf-8")
    velha = openapi.importar(swagger).collections[0]
    item = velha["items"][0]
    caso("swagger 2 monta a base com esquema, host e basePath",
         {v["key"]: v["value"] for v in velha["variables"]}["baseUrl"] == "http://api.velha/v2")
    caso("sem tag os requests ficam direto na collection", item["type"] == "request")
    caso("corpo como parametro in body", json.loads(item["body"]["raw"]) == {"qtd": 0.0})
    caso("apiKey vira auth da collection", velha["auth"]["type"] == "apikey" and velha["auth"]["key"] == "X-Key")

    vazia = pasta / "vazia.json"
    vazia.write_text('{"openapi": "3.0.0", "info": {"title": "V"}}', encoding="utf-8")
    caso("spec sem operacao avisa", any("nenhuma operacao" in a for a in openapi.importar(vazia).avisos))
    caso("deteccao: openapi e swagger sim, json comum nao",
         openapi.detectar(arquivo) == 1.0 and openapi.detectar(swagger) == 1.0
         and openapi.detectar(pasta / "x.txt") == 0.0)
    comum = pasta / "comum.json"
    comum.write_text('{"nome": "nao e spec"}', encoding="utf-8")
    caso("json sem openapi nao e spec", openapi.detectar(comum) == 0.0)
    ciclo = {"a": {"$ref": "#/b"}, "b": {"$ref": "#/a"}}
    caso("$ref em ciclo nao trava", isinstance(openapi._resolver(ciclo, {"$ref": "#/a"}), dict))
    caso("$ref com barra escapada", openapi._resolver({"x": {"a/b": {"ok": 1}}}, {"$ref": "#/x/a~1b"}) == {"ok": 1})
    caso("esquema muito fundo para de descer", openapi._exemplo_de_esquema({"type": "string"}, 7) == {})
    caso("enum pega o primeiro e date-time tem formato", openapi._exemplo_de_esquema({"enum": ["x", "y"]}) == "x"
         and openapi._exemplo_de_esquema({"type": "string", "format": "date-time"}) == "2026-01-01T00:00:00Z")

    p.secao("OpenAPI, exportar")
    nossa = {"name": "Nossa", "items": [
        {"type": "folder", "name": "Pets", "items": [
            {"type": "request", "name": "Ler", "method": "GET", "url": "{{baseUrl}}/pets/{{id}}",
             "params": [{"key": "a", "value": "1"}, {"key": "b", "value": "", "enabled": False}], "docs": "d"},
            {"type": "request", "name": "Criar", "method": "POST", "url": "https://api.real/pets",
             "body": {"mode": "json", "raw": '{"nome": "x"}'}}]}]}
    saida = openapi.exportar({}, [nossa], pasta / "saida.yaml")
    import yaml

    gerada = yaml.safe_load(saida.read_text(encoding="utf-8"))
    ler = gerada["paths"]["/pets/{id}"]["get"]
    caso("variavel de caminho volta a ser {parametro}",
         [(q["name"], q["in"], q["required"]) for q in ler["parameters"]]
         == [("a", "query", True), ("b", "query", False), ("id", "path", True)])
    caso("pasta vira tag e docs vira description", ler["tags"] == ["Pets"] and ler["description"] == "d")
    caso("url com host vira servidor", gerada["servers"] == [{"url": "https://api.real"}])
    caso("corpo json vai de exemplo",
         gerada["paths"]["/pets"]["post"]["requestBody"]["content"]["application/json"]["example"] == {"nome": "x"})


def _importador(p, caso) -> None:
    p.secao("importador")
    pasta = pasta_nova("importador")
    caso("arquivo que nao existe avisa", "nao encontrei" in importer.importar(pasta / "nada.json").erro)
    texto = pasta / "texto.txt"
    texto.write_text("nada reconhecivel", encoding="utf-8")
    caso("formato desconhecido lista o que aceita", "Postman" in importer.importar(texto).erro)
    caso("formato pedido que nao existe avisa", "nao suportado" in importer.importar(texto, "Word").erro)
    ambiguo = pasta / "ambiguo.json"
    ambiguo.write_text(json.dumps({"info": {}, "item": [], "__export_format": 4, "resources": []}), encoding="utf-8")
    caso("deteccao ordena da mais provavel pra menos",
         [n for n, _ in importer.detectar(ambiguo)] == ["Postman", "Insomnia"])
    caso("quando parece dois, escolhe e avisa", any("tambem parecia Insomnia 60%" in a
                                                    for a in importer.importar(ambiguo).avisos))
    sem_id = pasta / "sem-id.json"
    sem_id.write_text(json.dumps({"_type": "export", "__export_format": 4, "resources": [
        {"_type": "request", "name": "sem id"}]}), encoding="utf-8")
    caso("recurso sem _id vira erro legivel, e nao tombo", "KeyError" in (importer.importar(sem_id).erro or ""))

    arvore = {"collections": [{"name": "Api"}], "environments": [{"name": "hml"}]}
    vindo = Resultado(collections=[{"name": "Api"}, {"name": "Api"}, {"name": "Outra"}],
                      environments=[{"name": "hml"}])
    contagem = importer.aplicar(arvore, vindo)
    caso("nome repetido ganha numero sem apagar o que existia",
         ([c["name"] for c in arvore["collections"]] == ["Api", "Api 2", "Api 3", "Outra"]
          and [e["name"] for e in arvore["environments"]] == ["hml", "hml 2"], [c["name"] for c in arvore["collections"]]))
    caso("contagem do que entrou", contagem == {"collections": 3, "ambientes": 1, "renomeados": 3})
    try:
        importer.exportar({}, [], "word", pasta / "x")
        caso("exportar em formato desconhecido recusa", False)
    except ValueError:
        caso("exportar em formato desconhecido recusa", True)
    duas = [{"name": "Pagamentos v1", "items": []}, {"name": "Pagamentos (v1)", "items": []}]
    destino = importer.exportar({"environments": [{"name": "hml", "values": []}]}, duas, "postman", pasta / "varias")
    caso("varias collections pro Postman viram arquivos separados, com o ambiente junto",
         sorted(a.name for a in destino.iterdir()) == ["hml.postman_environment.json",
                                                       "pagamentos-v1-2.postman_collection.json",
                                                       "pagamentos-v1.postman_collection.json"])
    for formato, nome in (("insomnia", "x.json"), ("openapi", "x.json"), ("bruno", "bru")):
        caso(f"exportar {formato} devolve o destino", importer.exportar({}, duas[:1], formato, pasta / nome).exists())
    contada = Resultado(collections=[{"items": [{"type": "folder", "items": [{"type": "request"}]},
                                                {"type": "request"}]}], environments=[{}])
    caso("resultado conta pasta, request e ambiente",
         (contada.contar() == {"collections": 1, "pastas": 1, "requests": 2, "ambientes": 1}
          and contada.resumo() == "1 collections, 1 pastas, 2 requests, 1 ambientes", contada.resumo()))
    caso("curl pelo importador", importer.importar_curl("curl https://x").url == "https://x")


# ---------------------------------------------------------------------------- sftp e tela


def _sftp_sem_servidor(p, caso) -> None:
    p.secao("SFTP sem servidor")
    Entrada = sftp.Entrada
    caso("tamanho em bytes, KB, GB e o teto em TB",
         [Entrada("a", "/a", tamanho=t).tamanho_legivel() for t in (0, 1023, 1536, 5 * 1024 ** 3, 2 * 1024 ** 5)]
         == ["0 B", "1023 B", "1.5 KB", "5.0 GB", "2048.0 TB"])
    caso("pasta nao mostra tamanho", Entrada("p", "/p", pasta=True, tamanho=10).tamanho_legivel() == "")
    caso("sem data e sem modo ficam vazios", Entrada("a", "/a").quando() == "" and Entrada("a", "/a").permissoes() == "")
    ano_passado = time.mktime((time.localtime().tm_year - 1, 6, 1, 12, 0, 0, 0, 0, -1))
    caso("data de outro ano mostra o ano", Entrada("a", "/a", modificado=ano_passado).quando().endswith(
        str(time.localtime().tm_year - 1)))
    caso("data deste ano mostra a hora", ":" in Entrada("a", "/a", modificado=time.time()).quando())
    ordem = sorted([Entrada("b", "/b"), Entrada("Z", "/Z", pasta=True), Entrada("A", "/A")], key=Entrada.ordenacao)
    caso("pasta primeiro e nome sem caixa", [e.nome for e in ordem] == ["Z", "A", "b"])
    torto = sftp.Perfil.de_dict({"host": "h", "user": "u", "port": "abc"})
    caso("porta que nao e numero vira problema, e nao tombo", torto.porta == 0 and "porta" in torto.problema())
    padrao = sftp.Perfil.de_dict({"host": "h"})
    caso("sem porta usa 22, nome cai no host e rotulo sem porta",
         padrao.porta == 22 and padrao.nome == "h" and padrao.rotulo() == "h" and padrao.id.startswith("sftp-"))
    arvore: dict = {}
    sftp.gravar_perfis(arvore, [sftp.Perfil(id="s1", host="h", usuario="u", porta=2222)])
    caso("gravar e listar perfis na arvore",
         [(x.id, x.porta) for x in sftp.listar_perfis(dict(arvore, sftp=arvore["sftp"] + ["lixo"]))] == [("s1", 2222)])
    caso("nome local tira o que o Windows recusa", sftp.nome_local('a<b>:c?.txt') == "a_b__c_.txt")
    caso("nome reservado ganha sublinhado", sftp.nome_local("CON.txt") == "_CON.txt" and sftp.nome_local("com1") == "_com1")
    caso("nome que so tem ponto vira arquivo", sftp.nome_local("..") == "arquivo" and sftp.nome_local("") == "arquivo")
    caso("destino local nao sai da pasta", sftp.destino_local("C:/x", "..\\..\\y.bat") == Path("C:/x") / ".._.._y.bat")
    caso("juntar com caminho absoluto troca a base", sftp.juntar("/a", "/b/c") == "/b/c" and sftp.juntar("", "x") == "/x")


def _funcoes_da_tela(p, caso) -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from conduit.gui import highlight, history_panel, main_window, palette, response_view, theme, tokens, widgets

    theme.aplicar(None, "escuro")
    p.secao("funcoes da tela: historico")
    hoje = date(2026, 9, 23)
    caso("hoje mostra so a hora", history_panel.quando("2026-09-23T14:32:10", hoje) == "14:32:10")
    caso("ontem diz ontem", history_panel.quando("2026-09-22T14:32:10", hoje) == "ontem 14:32")
    caso("outro dia mostra dia e mes", history_panel.quando("2026-01-02T08:05:00", hoje) == "02/01 08:05")
    caso("virada de mes conta como ontem", history_panel.quando("2026-08-31T23:59:00", date(2026, 9, 1)) == "ontem 23:59")
    caso("texto curto ou data torta nao estouram",
         history_panel.quando("", hoje) == "" and history_panel.quando("14:32", hoje) == "14:32"
         and history_panel.quando("xxxx-xx-xxT14:32:10", hoje) == "14:32:10")
    montada = history_panel.entrada_do_resumo({"id": "i", "method": "GET", "url": "u", "ok": 0, "status": None,
                                                "error": "ConnectError", "elapsed_ms": 5, "request_id": "r"})
    caso("execucao sem corpo e montada do indice",
         montada["semCorpo"] and montada["response"]["ok"] is False and montada["response"]["error"] == "ConnectError"
         and montada["requestId"] == "r" and montada["request"]["url"] == "u")
    caso("sem status: falha em vermelho, neutro em cinza",
         history_panel.status_color(None, False) == theme.ERR and history_panel.status_color(None, True) == theme.DIM)
    curl = history_panel.to_curl({"request": {"method": "POST", "url": "https://x", "headers": [["A", "$HOME"]],
                                              "body": '{"a": "`x`"}'}})
    caso("curl do historico em aspa simples", "-H 'A: $HOME'" in curl and "-d '{\"a\": \"`x`\"}'" in curl, curl)

    p.secao("funcoes da tela: resposta")
    caso("bytes legiveis", [response_view.human_bytes(n) for n in (None, 512, 2048, 3 * 1024 * 1024)]
         == ["", "512 B", "2.0 KB", "3.00 MB"])
    caso("tempo legivel", [response_view.human_ms(n) for n in (None, 999, 1500)] == ["", "999 ms", "1.50 s"])
    binarios = {t: response_view.eh_binario(t) for t in (
        "image/png", "image/svg+xml", "application/x-www-form-urlencoded", "application/x-amz-json-1.1",
        "application/pdf", "application/octet-stream", "text/plain", "", None)}
    caso("binario pelo tipo, com as excecoes de texto",
         (binarios == {"image/png": True, "image/svg+xml": False, "application/x-www-form-urlencoded": False,
                       "application/x-amz-json-1.1": False, "application/pdf": True, "application/octet-stream": True,
                       "text/plain": False, "": False, None: False}, binarios))
    caso("header sem ligar pra caixa", response_view.header_value([("Content-Type", "a")], "content-type") == "a"
         and response_view.header_value(None, "x") == "")
    caso("Set-Cookie quebrado em nome, valor e atributos",
         response_view.parse_cookies([("set-cookie", "sessao=abc=1; Path=/; HttpOnly"), ("X", "y")])
         == [["sessao", "abc=1", "Path=/  HttpOnly"]])
    nome = response_view.ResponseView._nome_sugerido
    caso("nome do Content-Disposition, simples e codificado",
         nome([("Content-Disposition", 'attachment; filename="nota.pdf"')]) == "nota.pdf"
         and nome([("Content-Disposition", "attachment; filename*=UTF-8''rela%C3%A7%C3%A3o.csv")]) == "relação.csv")
    caso("nome com caminho fica so com o nome",
         nome([("Content-Disposition", 'attachment; filename="..\\..\\x.bat"')]) == "x.bat"
         and nome([]) == "")
    caso("linguagem pelo tipo ou pelo comeco",
         [highlight.guess_language(t, c) for t, c in (("{}", ""), ("x", "application/json"), ("<a/>", ""),
                                                        ("oi", "text/html"), ("oi", ""), (None, None))]
         == ["json", "json", "xml", "xml", "none", "none"])

    p.secao("funcoes da tela: textos")
    caso("singular e plural", widgets.conta(1, "pasta", "pastas") == "1 pasta" and widgets.conta(0, "pasta", "pastas") == "0 pastas")
    caso("texto de fora com tag nao vira HTML", "<img" not in widgets.dica_de_fora("<img src='file://x/y'>")
         and widgets.dica_de_fora("texto comum") == "texto comum" and widgets.dica_de_fora(None) == "")
    info = scopes.VarInfo("tok", "segredo-muito-longo", secret=True, scope="ambiente", origin="prd")
    dica = highlight.tooltip_for("tok", info)
    caso("balao da variavel secreta nao mostra o valor inteiro", "segredo-muito-longo" not in dica and "seg***go" in dica)
    caso("balao de variavel sem dono diz que nao existe", "nao existe" in highlight.tooltip_for("x", None))
    caso("balao de variavel vazia diz sem valor", "sem valor" in highlight.tooltip_for("x", scopes.VarInfo("x", "")))
    caso("cor da variavel por tipo",
         len({highlight.cor_da_variavel(None), highlight.cor_da_variavel(info),
              highlight.cor_da_variavel(scopes.VarInfo("a", "b"))}) == 3)

    p.secao("funcoes da tela: busca da paleta")
    caso("busca vazia casa tudo e sem letra em ordem nao casa",
         palette.fuzzy("", "x") == 0 and palette.fuzzy("xyz", "abc") is None)
    caso("pedaco inteiro vale mais que letras espalhadas",
         palette.fuzzy("banco", "Banco por codigo") > palette.fuzzy("banco", "Basic auth na collection") > 0)
    caso("pedaco no meio da palavra ainda ganha de iniciais espalhadas",
         palette.fuzzy("rota", "Cenoura rotativa") > palette.fuzzy("rota", "Rede Objeto Tipo Arquivo") > 0)
    caso("comeco do texto vale mais que o meio",
         palette.fuzzy("cep", "Cep por rua") > palette.fuzzy("cep", "Consulta CEP"))

    p.secao("funcoes da tela: ponto de nao salvo")
    caso("ajustes com o padrao do envio no que falta",
         main_window._ajustes({}) == {"timeout": 0.0, "verifyTls": True, "followRedirects": True}
         and main_window._ajustes({"settings": "torto"})["timeout"] == 0.0
         and main_window._ajustes({"settings": {"timeout": "30s", "verifyTls": False}})
         == {"timeout": 0.0, "verifyTls": False, "followRedirects": True})
    foto = main_window._foto
    velho = {"method": "get", "url": "https://x/a?b=1", "auth": {"type": "inherit"}}
    aberto = {"method": "GET", "url": "https://x/a", "params": [{"key": "b", "value": "1"}], "auth": {},
              "body": {"mode": "none", "raw": ""}, "settings": {"timeout": 0, "verifyTls": True, "followRedirects": True}}
    caso("request antigo e o mesmo request aberto na aba tem a mesma foto", foto(velho) == foto(aberto))
    caso("mudar a url muda a foto", foto(velho) != foto(dict(velho, url="https://x/c?b=1")))
    caso("desligar um param muda a foto",
         foto(aberto) != foto(dict(aberto, params=[{"key": "b", "value": "1", "enabled": False}])))

    p.secao("funcoes da tela: cor")
    caso("alfa em rgba, com teto e piso", tokens.alfa("#ff6076", 0.27) == "rgba(255, 96, 118, 0.270)"
         and tokens.alfa("#fff", 2) == "rgba(255, 255, 255, 1.000)" and tokens.alfa("#000", -1).endswith("0.000)"))
    caso("mistura nas pontas e no meio", tokens.mistura("#ffffff", "#000000", 1) == "#ffffff"
         and tokens.mistura("#ffffff", "#000000", 0) == "#000000" and tokens.mistura("#ffffff", "#000000", 0.5) == "#808080")
    caso("contraste de preto e branco e 21", round(tokens.contraste("#000", "#fff"), 1) == 21.0
         and tokens.contraste("#777", "#777") == 1.0)
    caso("tinta escura no claro e branca no escuro",
         tokens.tinta_sobre("#ffffff") == "#0a1220" and tokens.tinta_sobre("#000000") == "#ffffff")
    P = theme.P
    tons = {s: theme.tom_do_status(s, True)[0] for s in (200, 302, 404, 500, 101)}
    caso("cor por familia de status",
         tons == {200: P["ok"], 302: P["info"], 404: P["aviso"], 500: P["erro"], 101: P["texto_medio"]}, tons)
    caso("falha ou status que nao e numero e erro",
         theme.tom_do_status(200, False)[0] == P["erro"] and theme.tom_do_status("200")[0] == P["erro"])
    app.processEvents()


def _linha_de_comando(p, caso) -> None:
    p.secao("linha de comando")
    from conduit import __main__ as principal

    saida = io.StringIO()
    with contextlib.redirect_stdout(saida):
        codigo = principal.main(["ws"])
    linhas = saida.getvalue().splitlines()
    ativo = ws.list_workspaces()["active"]
    caso("ws lista os workspaces e marca o ativo",
         (codigo == 0 and any(l.startswith("*") and ativo in l for l in linhas), linhas))
    saida = io.StringIO()
    try:
        with contextlib.redirect_stdout(saida):
            principal.main(["--version"])
        caso("--version diz a versao", False)
    except SystemExit as fim:
        from conduit import __version__

        caso("--version diz a versao", fim.code == 0 and __version__ in saida.getvalue())


if __name__ == "__main__":
    sys.exit(main())
