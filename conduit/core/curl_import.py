"""Le um comando curl e monta o request.

Aceita as tres formas que aparecem no dia a dia: a do bash com barra invertida no fim
da linha, a do PowerShell com crase, e a do cmd com acento circunflexo. Tambem aceita o
"Copy as cURL" do Chrome e do Firefox, que e de onde a maioria dos comandos sai.

Nao tenta ser um curl completo. Cobre o que muda um request: metodo, url, header, corpo,
usuario e senha, cookie, timeout, redirect e verificacao de TLS. O que nao entende volta
na lista de ignorados, em vez de sumir calado.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# opcoes que nao mudam nada do que a gente monta, entao somem sem aviso
RUIDO = {
    "--compressed", "-s", "--silent", "-S", "--show-error", "-v", "--verbose",
    "-i", "--include", "--no-buffer", "-#", "--progress-bar", "-f", "--fail",
    "-4", "--ipv4", "-6", "--ipv6", "--http1.1", "--http2", "-N",
}


@dataclass
class Importado:
    method: str = "GET"
    url: str = ""
    params: list = field(default_factory=list)
    headers: list = field(default_factory=list)
    body: dict = field(default_factory=lambda: {"mode": "none", "raw": ""})
    auth: dict | None = None
    settings: dict = field(default_factory=dict)
    ignorados: list = field(default_factory=list)
    erro: str | None = None

    def resumo(self) -> str:
        partes = [f"{self.method} {self.url}"]
        if self.headers:
            partes.append(f"{len(self.headers)} headers")
        if self.params:
            partes.append(f"{len(self.params)} params")
        if self.body.get("mode") != "none":
            partes.append(f"corpo {self.body['mode']}")
        if self.auth:
            partes.append(f"auth {self.auth.get('type')}")
        return "   ·   ".join(partes)


def parece_curl(texto: str) -> bool:
    return bool(re.match(r"^\s*curl[\s\n]", (texto or "") + " "))


def _limpar(texto: str) -> str:
    """Tira as continuacoes de linha das tres conchas e junta tudo numa linha so."""
    limpo = texto.strip()
    if limpo.startswith("`") or limpo.startswith("'"):
        limpo = limpo.strip("`'")
    limpo = re.sub(r"\\\s*\r?\n", " ", limpo)      # bash
    limpo = re.sub(r"`\s*\r?\n", " ", limpo)       # powershell
    limpo = re.sub(r"\^\s*\r?\n", " ", limpo)      # cmd
    limpo = re.sub(r"\s*\r?\n\s*", " ", limpo)
    return limpo.strip()


def _dividir(texto: str) -> list[str]:
    try:
        return shlex.split(texto, posix=True)
    except ValueError:
        pass
    # aspas desbalanceadas, comum quando o comando vem cortado de um chat. O modo nao
    # posix recusa aspa aberta do mesmo jeito, entao fecha a que ficou aberta e tenta de novo
    for fecho in ("'", '"'):
        try:
            return shlex.split(texto + fecho, posix=True)
        except ValueError:
            continue
    return shlex.split(texto, posix=False)


def importar(comando: str) -> Importado:
    saida = Importado()
    texto = _limpar(comando)
    if not parece_curl(texto):
        saida.erro = "o texto nao comeca com curl"
        return saida

    try:
        pedacos = _dividir(texto)[1:]
    except ValueError as exc:
        saida.erro = f"nao consegui separar os argumentos: {exc}"
        return saida

    corpos: list[str] = []
    metodo_explicito = None
    virar_query = False
    # teve -d ou -F, mesmo que o conteudo nao tenha vindo: pro curl isso ja e POST
    pediu_corpo = False
    forms: list[tuple[str, str]] = []
    urls: list[str] = []

    indice = 0
    while indice < len(pedacos):
        atual = pedacos[indice]
        proximo = pedacos[indice + 1] if indice + 1 < len(pedacos) else None

        def consome() -> str:
            nonlocal indice
            indice += 1
            return pedacos[indice] if indice < len(pedacos) else ""

        if atual in RUIDO:
            pass
        elif atual in ("-X", "--request"):
            metodo_explicito = (consome() or "GET").upper()
        elif atual in ("-H", "--header"):
            bruto = consome()
            chave, _, valor = bruto.partition(":")
            if chave.strip():
                saida.headers.append(
                    {"key": chave.strip(), "value": valor.strip(), "enabled": True}
                )
        elif atual in ("-d", "--data", "--data-raw", "--data-binary", "--data-ascii"):
            dado = consome()
            pediu_corpo = True
            if atual != "--data-raw" and dado.startswith("@"):
                # o curl le o corpo desse arquivo, que nao veio junto. Mandado como texto,
                # o servidor recebia @corpo.json no lugar do conteudo, igual ao -F
                saida.ignorados.append(f"{atual} {dado}, envio de arquivo")
            else:
                corpos.append(dado)
        elif atual == "--data-urlencode":
            corpos.append(consome())
            pediu_corpo = True
        elif atual == "--json":
            corpos.append(consome())
            pediu_corpo = True
            if not any(h["key"].lower() == "content-type" for h in saida.headers):
                saida.headers.append(
                    {"key": "Content-Type", "value": "application/json", "enabled": True}
                )
        elif atual in ("-F", "--form"):
            bruto = consome()
            pediu_corpo = True
            chave, _, valor = bruto.partition("=")
            if valor.startswith(("@", "<")):
                # envio de arquivo e multipart, que o app ainda nao manda. Convertido
                # calado, o servidor recebia o texto %40nota.pdf no lugar do arquivo
                saida.ignorados.append(f"{atual} {chave}={valor}, envio de arquivo")
            else:
                forms.append((chave, valor))
                if "multipart" not in " ".join(saida.ignorados):
                    saida.ignorados.append(
                        f"{atual} sai como form urlencoded, e nao multipart"
                    )
        elif atual in ("-u", "--user"):
            usuario, _, senha = consome().partition(":")
            saida.auth = {"type": "basic", "username": usuario, "password": senha}
        elif atual in ("-b", "--cookie"):
            saida.headers.append({"key": "Cookie", "value": consome(), "enabled": True})
        elif atual in ("-A", "--user-agent"):
            saida.headers.append({"key": "User-Agent", "value": consome(), "enabled": True})
        elif atual in ("-e", "--referer"):
            saida.headers.append({"key": "Referer", "value": consome(), "enabled": True})
        elif atual in ("-k", "--insecure"):
            saida.settings["verifyTls"] = False
        elif atual in ("-L", "--location"):
            saida.settings["followRedirects"] = True
        elif atual in ("-m", "--max-time", "--connect-timeout"):
            try:
                saida.settings["timeout"] = int(float(consome()))
            except ValueError:
                pass
        elif atual == "-G" or atual == "--get":
            virar_query = True
        elif atual == "--url":
            urls.append(consome())
        elif atual.startswith("-"):
            saida.ignorados.append(atual)
            # opcao desconhecida que parece pedir valor engole o proximo pedaco
            if proximo and not proximo.startswith("-") and "://" not in proximo:
                consome()
        else:
            urls.append(atual)

        indice += 1

    if not urls:
        saida.erro = "nao achei a url no comando"
        return saida

    url = urls[0]
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url

    partes = urlsplit(url)
    if partes.query:
        saida.params = [
            {"key": chave, "value": valor, "enabled": True}
            for chave, valor in parse_qsl(partes.query, keep_blank_values=True)
        ]
        url = urlunsplit((partes.scheme, partes.netloc, partes.path, "", partes.fragment))

    corpo_junto = "&".join(c for c in corpos if c)

    if virar_query and corpo_junto:
        for chave, valor in parse_qsl(corpo_junto, keep_blank_values=True):
            saida.params.append({"key": chave, "value": valor, "enabled": True})
        corpo_junto = ""

    if forms:
        saida.body = {
            "mode": "form",
            "raw": urlencode([(c, v) for c, v in forms]),
        }
    elif corpo_junto:
        tipo = next(
            (h["value"] for h in saida.headers if h["key"].lower() == "content-type"), ""
        ).lower()
        eh_json = "json" in tipo or corpo_junto.lstrip().startswith(("{", "["))
        # sem Content-Type o curl manda o -d como form urlencoded. Como raw ele saia sem
        # Content-Type nenhum, e o servidor nao lia os campos
        modo = "json" if eh_json else "raw" if tipo else "form"
        saida.body = {"mode": modo, "raw": corpo_junto}

    # metodo: o -X manda, senao corpo implica POST, mesmo o de arquivo que ficou de fora
    if metodo_explicito:
        saida.method = metodo_explicito
    elif saida.body.get("mode") != "none" or (pediu_corpo and not virar_query):
        saida.method = "POST"
    else:
        saida.method = "GET"

    # a query montada nos params nao fica duplicada na url, ver engine.prepare
    saida.url = url
    return saida


def aplicar(request: dict, dados: Importado) -> None:
    """Joga o resultado dentro do request aberto, no lugar do que estava."""
    request["method"] = dados.method
    request["url"] = dados.url
    request["params"] = list(dados.params)
    request["headers"] = list(dados.headers)
    request["body"] = dict(dados.body)
    if dados.auth:
        request["auth"] = dict(dados.auth)
    if dados.settings:
        request.setdefault("settings", {}).update(dados.settings)
