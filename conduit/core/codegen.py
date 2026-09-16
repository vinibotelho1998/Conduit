"""Geracao de codigo equivalente ao request, em varias linguagens.

Regra de seguranca: por padrao o valor de variavel secreta NAO e resolvido, ele fica
como {{nome}} no codigo gerado. Quem quiser o valor real precisa pedir de forma
explicita, porque codigo gerado costuma acabar colado em chat e em ticket.
"""

from __future__ import annotations

import json
import shlex

LANGUAGES = [
    ("curl", "curl"),
    ("powershell", "PowerShell"),
    ("python-httpx", "Python, httpx"),
    ("python-requests", "Python, requests"),
    ("javascript-fetch", "JavaScript, fetch"),
    ("node-axios", "Node, axios"),
    ("java", "Java, HttpClient"),
    ("csharp", "C#, HttpClient"),
    ("go", "Go, net/http"),
]


def _pretty_body(body: str | None) -> str:
    if not body:
        return ""
    try:
        return json.dumps(json.loads(body), indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, ValueError):
        return body


def generate(language: str, method: str, url: str, headers: dict, body: str | None) -> str:
    method = (method or "GET").upper()
    headers = headers or {}
    fn = {
        "curl": _curl,
        "powershell": _powershell,
        "python-httpx": _python_httpx,
        "python-requests": _python_requests,
        "javascript-fetch": _fetch,
        "node-axios": _axios,
        "java": _java,
        "csharp": _csharp,
        "go": _go,
    }.get(language)
    if fn is None:
        return f"linguagem {language} nao suportada"
    return fn(method, url, headers, body)


def _curl(method, url, headers, body) -> str:
    linhas = [f"curl -X {method} {shlex.quote(url)}"]
    for chave, valor in headers.items():
        linhas.append(f"  -H {shlex.quote(f'{chave}: {valor}')}")
    if body:
        linhas.append(f"  -d {shlex.quote(body)}")
    linhas.append("  -i")
    return " \\\n".join(linhas)


def _ps_literal(valor: str) -> str:
    """Literal do PowerShell. Aspa simples se escapa dobrando ela mesma."""
    return "'" + str(valor).replace("'", "''") + "'"


def _powershell(method, url, headers, body) -> str:
    partes = []
    if headers:
        # Sem escapar, um header ou uma url com aspa dentro fechava a string antes da
        # hora e o comando colado no terminal nem rodava.
        itens = "; ".join(
            f"{_ps_literal(k)} = {_ps_literal(v)}" for k, v in headers.items()
        )
        partes.append(f"$headers = @{{ {itens} }}")
    if body:
        partes.append("$body = @'\n" + body + "\n'@")
    chamada = [f"Invoke-RestMethod -Method {method} -Uri {_ps_literal(url)}"]
    if headers:
        chamada.append("-Headers $headers")
    if body:
        chamada.append("-Body $body")
    chamada.append("-SkipHttpErrorCheck")
    partes.append(" ".join(chamada))
    return "\n".join(partes)


def _python_httpx(method, url, headers, body) -> str:
    linhas = ["import httpx", ""]
    if headers:
        linhas.append("headers = " + json.dumps(headers, indent=4, ensure_ascii=False))
    if body:
        linhas.append("body = " + _py_literal(body))
    linhas.append("")
    args = [f'"{method}"', f'"{url}"']
    if headers:
        args.append("headers=headers")
    if body:
        args.append("content=body.encode()")
    linhas.append("with httpx.Client(timeout=60, follow_redirects=True) as client:")
    linhas.append(f"    resposta = client.request({', '.join(args)})")
    linhas.append("")
    linhas.append("print(resposta.status_code, resposta.elapsed.total_seconds())")
    linhas.append("print(resposta.text)")
    return "\n".join(linhas)


def _python_requests(method, url, headers, body) -> str:
    linhas = ["import requests", ""]
    if headers:
        linhas.append("headers = " + json.dumps(headers, indent=4, ensure_ascii=False))
    if body:
        linhas.append("body = " + _py_literal(body))
    linhas.append("")
    args = [f'"{method}"', f'"{url}"']
    if headers:
        args.append("headers=headers")
    if body:
        args.append("data=body.encode()")
    args.append("timeout=60")
    linhas.append(f"resposta = requests.request({', '.join(args)})")
    linhas.append("print(resposta.status_code)")
    linhas.append("print(resposta.text)")
    return "\n".join(linhas)


def _py_literal(body: str) -> str:
    if "\n" in body:
        return '"""' + body.replace('"""', '\\"\\"\\"') + '"""'
    return json.dumps(body, ensure_ascii=False)


def _fetch(method, url, headers, body) -> str:
    corpo = ""
    if body:
        corpo = "  body: " + _js_literal(body) + ",\n"

    linhas = [f'const resposta = await fetch("{url}", {{']
    linhas.append(f'  method: "{method}",')
    if headers:
        linhas.append("  headers: " + json.dumps(headers, indent=2, ensure_ascii=False).replace("\n", "\n  ") + ",")
    if corpo:
        linhas.append(corpo.rstrip("\n"))
    linhas.append("});")
    linhas.append("")
    linhas.append("console.log(resposta.status);")
    linhas.append("console.log(await resposta.text());")
    return "\n".join(linhas)


def _axios(method, url, headers, body) -> str:
    linhas = ['const axios = require("axios");', "", "const resposta = await axios({"]
    linhas.append(f'  method: "{method.lower()}",')
    linhas.append(f'  url: "{url}",')
    if headers:
        linhas.append("  headers: " + json.dumps(headers, indent=2, ensure_ascii=False).replace("\n", "\n  ") + ",")
    if body:
        linhas.append("  data: " + _js_literal(body) + ",")
    linhas.append("  validateStatus: () => true,")
    linhas.append("});")
    linhas.append("")
    linhas.append("console.log(resposta.status, resposta.data);")
    return "\n".join(linhas)


def _js_literal(body: str) -> str:
    try:
        return json.dumps(json.loads(body), indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, ValueError):
        return "`" + body.replace("`", "\\`") + "`"


def _java(method, url, headers, body) -> str:
    linhas = [
        "import java.net.URI;",
        "import java.net.http.HttpClient;",
        "import java.net.http.HttpRequest;",
        "import java.net.http.HttpResponse;",
        "import java.time.Duration;",
        "",
        "HttpClient cliente = HttpClient.newBuilder()",
        "        .connectTimeout(Duration.ofSeconds(60))",
        "        .followRedirects(HttpClient.Redirect.NORMAL)",
        "        .build();",
        "",
        "HttpRequest requisicao = HttpRequest.newBuilder()",
        f'        .uri(URI.create("{url}"))',
    ]
    for chave, valor in headers.items():
        linhas.append(f'        .header("{chave}", "{_java_escape(valor)}")')
    if body:
        linhas.append(f'        .method("{method}", HttpRequest.BodyPublishers.ofString("""')
        linhas.append(body)
        linhas.append('"""))')
    else:
        linhas.append(f'        .method("{method}", HttpRequest.BodyPublishers.noBody())')
    linhas.append("        .build();")
    linhas.append("")
    linhas.append("HttpResponse<String> resposta = cliente.send(requisicao, HttpResponse.BodyHandlers.ofString());")
    linhas.append("System.out.println(resposta.statusCode());")
    linhas.append("System.out.println(resposta.body());")
    return "\n".join(linhas)


def _java_escape(valor: str) -> str:
    return str(valor).replace("\\", "\\\\").replace('"', '\\"')


def _csharp(method, url, headers, body) -> str:
    linhas = [
        "using System;",
        "using System.Net.Http;",
        "using System.Text;",
        "",
        "using var cliente = new HttpClient();",
        f'var requisicao = new HttpRequestMessage(new HttpMethod("{method}"), "{url}");',
    ]
    for chave, valor in headers.items():
        if chave.lower() == "content-type":
            continue
        linhas.append(f'requisicao.Headers.TryAddWithoutValidation("{chave}", "{_java_escape(valor)}");')
    if body:
        tipo = headers.get("Content-Type") or headers.get("content-type") or "application/json"
        literal = body.replace('"', '""')
        linhas.append(f'requisicao.Content = new StringContent(@"{literal}", Encoding.UTF8, "{tipo.split(";")[0]}");')
    linhas.append("")
    linhas.append("var resposta = await cliente.SendAsync(requisicao);")
    linhas.append("Console.WriteLine((int)resposta.StatusCode);")
    linhas.append("Console.WriteLine(await resposta.Content.ReadAsStringAsync());")
    return "\n".join(linhas)


def _go(method, url, headers, body) -> str:
    # Go recusa compilar com import que ninguem usa, e "strings" so entra em cena quando
    # existe corpo. Sem separar, todo GET gerado aqui nascia sem compilar.
    pacotes = ['    "fmt"', '    "io"', '    "net/http"']
    if body:
        pacotes.append('    "strings"')
    pacotes.append('    "time"')
    linhas = ["package main", "", "import (", *pacotes, ")", "", "func main() {"]
    if body:
        literal = body.replace("`", "` + \"`\" + `")
        linhas.append(f"    corpo := strings.NewReader(`{literal}`)")
        linhas.append(f'    requisicao, _ := http.NewRequest("{method}", "{url}", corpo)')
    else:
        linhas.append(f'    requisicao, _ := http.NewRequest("{method}", "{url}", nil)')
    for chave, valor in headers.items():
        linhas.append(f'    requisicao.Header.Set("{chave}", "{_java_escape(valor)}")')
    linhas.append("")
    linhas.append("    cliente := &http.Client{Timeout: 60 * time.Second}")
    linhas.append("    resposta, erro := cliente.Do(requisicao)")
    linhas.append("    if erro != nil {")
    linhas.append("        panic(erro)")
    linhas.append("    }")
    linhas.append("    defer resposta.Body.Close()")
    linhas.append("")
    linhas.append("    dados, _ := io.ReadAll(resposta.Body)")
    linhas.append("    fmt.Println(resposta.StatusCode)")
    linhas.append("    fmt.Println(string(dados))")
    linhas.append("}")
    return "\n".join(linhas)
