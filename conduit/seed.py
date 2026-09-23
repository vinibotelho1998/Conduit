"""Collections de exemplo, com APIs publicas que respondem de verdade.

Nenhum endpoint aqui e interno nem precisa de credencial. Servem pra tela nao abrir
vazia, pra voce ter o que apertar Send no primeiro minuto e pra exercitar cada recurso
do programa: variavel, query param, body json, form, header, status de erro e timeout.
"""

from __future__ import annotations

from .core import workspaces as ws

EXAMPLES_ID = "exemplos"


def kv(key: str, value: str, enabled: bool = True) -> dict:
    return {"key": key, "value": value, "enabled": enabled}


def secret(key: str, value: str = "") -> dict:
    return {"key": key, "value": value, "enabled": True, "secret": True}


def req(
    name: str,
    method: str,
    url: str,
    *,
    params=None,
    headers=None,
    body=None,
    docs: str = "",
    timeout: int = 30,
) -> dict:
    return {
        "id": ws.new_id("req"),
        "type": "request",
        "name": name,
        "method": method,
        "url": url,
        "params": params or [],
        "headers": headers or [],
        "body": body or {"mode": "none", "raw": ""},
        "docs": docs,
        "settings": {"timeout": timeout, "followRedirects": True, "verifyTls": True},
    }


def folder(name: str, items: list, expanded: bool = False, variables=None) -> dict:
    return {
        "id": ws.new_id("fld"),
        "type": "folder",
        "name": name,
        "expanded": expanded,
        "variables": variables or [],
        "items": items,
    }


def collection(name: str, items: list, expanded: bool = False, variables=None) -> dict:
    return {
        "id": ws.new_id("col"),
        "type": "collection",
        "name": name,
        "expanded": expanded,
        "variables": variables or [],
        "items": items,
    }


def json_body(raw: str) -> dict:
    return {"mode": "json", "raw": raw}


def _brasilapi() -> dict:
    base = "{{brasilApi}}"
    return collection(
        "BrasilAPI",
        expanded=True,
        variables=[
            kv("tipoVeiculo", "carros"),
            kv("codigoBanco", "341"),
            kv("moeda", "USD"),
            kv("ano", "2026"),
        ],
        items=[
            folder(
                "localidade",
                expanded=True,
                variables=[kv("cep", "01310930"), kv("ddd", "65")],
                items=[
                    req(
                        "CEP v2",
                        "GET",
                        f"{base}/cep/v2/{{{{cep}}}}",
                        docs="Consulta de CEP com varios provedores em cascata. Devolve tambem latitude e longitude.",
                    ),
                    req(
                        "DDD",
                        "GET",
                        f"{base}/ddd/v1/{{{{ddd}}}}",
                        docs="Estado e lista de cidades atendidas pelo DDD.",
                    ),
                    req(
                        "Municipios por UF",
                        "GET",
                        f"{base}/ibge/municipios/v1/{{{{uf}}}}",
                        docs="uf existe em dois escopos de proposito: SP nas globais e MT no "
                        "ambiente. O ambiente ganha, entao vem MT. Passe o mouse na variavel "
                        "realcada na url pra ver de onde ela veio e quem perdeu a disputa.",
                    ),
                    req("Estados do IBGE", "GET", f"{base}/ibge/uf/v1"),
                ],
            ),
            folder(
                "veiculos FIPE",
                items=[
                    req(
                        "Marcas por tipo",
                        "GET",
                        f"{base}/fipe/marcas/v1/{{{{tipoVeiculo}}}}",
                        docs="tipoVeiculo aceita carros, motos e caminhoes.",
                    ),
                    req(
                        "Tabelas de referencia",
                        "GET",
                        f"{base}/fipe/tabelas/v1",
                        docs="Codigo da tabela de referencia usado nas consultas de preco.\n"
                        "A origem da FIPE cai de vez em quando e devolve 500. Quando isso "
                        "acontecer, o erro e de la, nao daqui: a aba Enviado mostra que a "
                        "chamada saiu certa.",
                    ),
                    req(
                        "Preco por codigo FIPE",
                        "GET",
                        f"{base}/fipe/preco/v1/{{{{codigoFipe}}}}",
                        docs="Preco medio do veiculo. Aceita o parametro tabela_referencia.\n"
                        "Depende da mesma origem da consulta de tabelas.",
                    ),
                ],
            ),
            folder(
                "financeiro",
                items=[
                    req("Bancos, lista completa", "GET", f"{base}/banks/v1"),
                    req("Banco por codigo", "GET", f"{base}/banks/v1/{{{{codigoBanco}}}}"),
                    req(
                        "Participantes do PIX",
                        "GET",
                        f"{base}/pix/v1/participants",
                        docs="Lista grande. Bom pra testar o viewer com resposta pesada.",
                    ),
                    req("Taxas SELIC, CDI e IPCA", "GET", f"{base}/taxas/v1"),
                    req(
                        "Cambio por moeda e data",
                        "GET",
                        f"{base}/cambio/v1/cotacao/{{{{moeda}}}}/{{{{dataCambio}}}}",
                    ),
                ],
            ),
            folder(
                "empresa e calendario",
                items=[
                    req(
                        "CNPJ",
                        "GET",
                        f"{base}/cnpj/v1/{{{{cnpj}}}}",
                        docs="Dados cadastrais da Receita. Sem token.\n"
                        "A BrasilAPI limita por IP, entao 429 aqui e normal. Espere um pouco e repita.",
                    ),
                    req(
                        "Feriados nacionais",
                        "GET",
                        f"{base}/feriados/v1/{{{{ano}}}}",
                        docs="Util pra decidir se uma data e dia util antes de agendar "
                        "processamento.",
                    ),
                ],
            ),
        ],
    )


def _viacep() -> dict:
    return collection(
        "ViaCEP",
        items=[
            req(
                "CEP em JSON",
                "GET",
                "{{viaCep}}/ws/{{cep}}/json/",
                docs="O classico. Responde 200 com erro no corpo quando o CEP nao existe.",
            ),
            req(
                "Busca por logradouro",
                "GET",
                "{{viaCep}}/ws/{{uf}}/{{cidade}}/{{logradouro}}/json/",
                docs="Busca reversa. Minimo de tres caracteres em cidade e logradouro.",
            ),
        ],
    )


def _jsonplaceholder() -> dict:
    base = "{{jsonPlaceholder}}"
    return collection(
        "JSONPlaceholder, CRUD",
        items=[
            req("Listar posts", "GET", f"{base}/posts", params=[kv("_limit", "5")]),
            req("Post por id", "GET", f"{base}/posts/{{{{postId}}}}"),
            req(
                "Criar post",
                "POST",
                f"{base}/posts",
                headers=[kv("Content-Type", "application/json")],
                body=json_body('{\n  "title": "Conduit",\n  "body": "criado pelo cliente local",\n  "userId": 1\n}'),
            ),
            req(
                "Atualizar post inteiro",
                "PUT",
                f"{base}/posts/{{{{postId}}}}",
                headers=[kv("Content-Type", "application/json")],
                body=json_body('{\n  "id": 1,\n  "title": "titulo novo",\n  "body": "corpo novo",\n  "userId": 1\n}'),
            ),
            req(
                "Atualizar campo",
                "PATCH",
                f"{base}/posts/{{{{postId}}}}",
                headers=[kv("Content-Type", "application/json")],
                body=json_body('{\n  "title": "so o titulo"\n}'),
            ),
            req("Excluir post", "DELETE", f"{base}/posts/{{{{postId}}}}"),
            req("Comentarios do post", "GET", f"{base}/posts/{{{{postId}}}}/comments"),
        ],
    )


def _github() -> dict:
    base = "{{githubApi}}"
    headers = [kv("Accept", "application/vnd.github+json")]
    return collection(
        "GitHub API",
        items=[
            req("Usuario", "GET", f"{base}/users/{{{{githubUser}}}}", headers=headers),
            req("Repositorio", "GET", f"{base}/repos/{{{{owner}}}}/{{{{repo}}}}", headers=headers),
            req(
                "Issues abertas",
                "GET",
                f"{base}/repos/{{{{owner}}}}/{{{{repo}}}}/issues",
                headers=headers,
                params=[kv("state", "open"), kv("per_page", "10")],
            ),
            req(
                "Busca de repositorios",
                "GET",
                f"{base}/search/repositories",
                headers=headers,
                params=[kv("q", "http client language:python"), kv("sort", "stars"), kv("per_page", "5")],
            ),
            req(
                "Limite de uso",
                "GET",
                f"{base}/rate_limit",
                headers=headers,
                docs="Sem token sao 60 chamadas por hora por IP. Ver o header x-ratelimit-remaining.",
            ),
        ],
    )


def _clima() -> dict:
    return collection(
        "Open-Meteo, clima",
        items=[
            req(
                "Previsao por coordenada",
                "GET",
                "{{openMeteo}}/v1/forecast",
                params=[
                    kv("latitude", "{{lat}}"),
                    kv("longitude", "{{lon}}"),
                    kv("current", "temperature_2m,relative_humidity_2m"),
                    kv("timezone", "America/Sao_Paulo"),
                ],
                docs="Sem chave. Bom exemplo de request que vive de query param.",
            ),
            req(
                "Busca de cidade",
                "GET",
                "{{geoMeteo}}/v1/search",
                params=[kv("name", "{{cidade}}"), kv("count", "5"), kv("language", "pt")],
            ),
        ],
    )


def _laboratorio() -> dict:
    base = "{{httpbin}}"
    return collection(
        "Laboratorio httpbin",
        items=[
            folder(
                "basico",
                items=[
                    req(
                        "GET com query",
                        "GET",
                        f"{base}/get",
                        params=[kv("uf", "MT"), kv("origem", "conduit")],
                        docs="O httpbin devolve de volta o que recebeu. Serve pra conferir se "
                        "a variavel foi resolvida antes de sair.",
                    ),
                    req(
                        "POST JSON",
                        "POST",
                        f"{base}/post",
                        headers=[kv("Content-Type", "application/json")],
                        body=json_body('{\n  "id": 1042,\n  "nome": "pedido de teste",\n  "valor": 199.9\n}'),
                    ),
                    req(
                        "POST form urlencoded",
                        "POST",
                        f"{base}/post",
                        body={"mode": "form", "raw": "campo=valor&outro=teste"},
                    ),
                    req("PUT", "PUT", f"{base}/put"),
                    req("DELETE", "DELETE", f"{base}/delete"),
                    req("Eco dos headers", "GET", f"{base}/headers", headers=[kv("X-Rastreio", "{{$guid}}")]),
                ],
            ),
            folder(
                "erro e lentidao",
                items=[
                    req("Status 200", "GET", f"{base}/status/200"),
                    req("Status 404", "GET", f"{base}/status/404"),
                    req("Status 500", "GET", f"{base}/status/500"),
                    req(
                        "Resposta em 3 segundos",
                        "GET",
                        f"{base}/delay/3",
                        docs="Serve pra ver que a janela nao congela durante o envio.",
                    ),
                    req(
                        "Timeout proposital",
                        "GET",
                        f"{base}/delay/10",
                        timeout=3,
                        docs="Timeout de 3 segundos contra resposta de 10. Deve falhar por tempo.",
                    ),
                ],
            ),
            folder(
                "formato e auth",
                items=[
                    req("XML", "GET", f"{base}/xml"),
                    req(
                        "Imagem PNG",
                        "GET",
                        f"{base}/image/png",
                        docs="A aba Preview vira Imagem e mostra a figura, com o tamanho em pixels na dica.",
                    ),
                    req("HTML", "GET", f"{base}/html"),
                    req("Resposta gzip", "GET", f"{base}/gzip"),
                    req("Redirect em cadeia", "GET", f"{base}/redirect/3"),
                    req(
                        "Basic auth",
                        "GET",
                        f"{base}/basic-auth/conduit/segredo",
                        docs="A aba Auth resolve isso: escolha Basic e preencha usuario e "
                        "senha, em vez de montar o header na mao. O usuario e conduit e a senha "
                        "e segredo.",
                    ),
                    req(
                        "Bearer",
                        "GET",
                        f"{base}/bearer",
                        headers=[kv("Authorization", "Bearer {{tokenExemplo}}")],
                        docs="tokenExemplo esta marcado como secreto no ambiente, entao nao vai pro historico em claro.",
                    ),
                ],
            ),
        ],
    )


def examples_tree() -> dict:
    globais = [
        kv("operador", "time-de-integracao"),
        kv("uf", "SP"),
        kv("cidade", "Sao Paulo"),
        kv("timeoutPadrao", "30"),
    ]

    valores_comuns = [
        kv("brasilApi", "https://brasilapi.com.br/api"),
        kv("viaCep", "https://viacep.com.br"),
        kv("jsonPlaceholder", "https://jsonplaceholder.typicode.com"),
        kv("githubApi", "https://api.github.com"),
        kv("openMeteo", "https://api.open-meteo.com"),
        kv("geoMeteo", "https://geocoding-api.open-meteo.com"),
        kv("httpbin", "https://httpbin.org"),
        kv("uf", "MT"),
        kv("cidade", "Cuiaba"),
        kv("logradouro", "Historiador"),
        kv("cnpj", "19131243000197"),
        kv("codigoFipe", "001004-9"),
        # data fixa de proposito: a cotacao de um dia que ja fechou nao muda, entao o
        # exemplo devolve o mesmo resultado hoje e daqui a um ano
        kv("dataCambio", "2026-08-21"),
        kv("postId", "1"),
        kv("githubUser", "vinibotelho1998"),
        kv("owner", "vinibotelho1998"),
        kv("repo", "conduit"),
        kv("lat", "-15.6014"),
        kv("lon", "-56.0979"),
        secret("tokenExemplo", "token-de-mentira-so-pra-demonstrar"),
    ]

    return {
        "schemaVersion": 1,
        "globals": globais,
        "environments": [
            {"id": "env-publico", "name": "publico", "values": valores_comuns},
            {
                "id": "env-local",
                "name": "local",
                "values": [
                    kv("brasilApi", "http://localhost:8081/api"),
                    kv("httpbin", "http://localhost:8080"),
                    kv("viaCep", "http://localhost:8080"),
                    kv("jsonPlaceholder", "http://localhost:8080"),
                    kv("githubApi", "http://localhost:8080"),
                    kv("openMeteo", "http://localhost:8080"),
                    kv("geoMeteo", "http://localhost:8080"),
                    kv("uf", "MT"),
                    secret("tokenExemplo", ""),
                ],
            },
        ],
        "activeEnv": "env-publico",
        "collections": [
            _brasilapi(),
            _viacep(),
            _jsonplaceholder(),
            _github(),
            _clima(),
            _laboratorio(),
        ],
    }


def ensure_examples(force: bool = False) -> str:
    """Cria o workspace de exemplos. Sem force, nao mexe se ele ja existir."""
    registry = ws.list_workspaces()
    existe = any(entry["id"] == EXAMPLES_ID for entry in registry["workspaces"])

    if not existe:
        # tirado da lista, o de exemplos volta na abertura seguinte. Volta com o que a
        # pessoa ja tinha posto nele: regravar os exemplos por cima apagava o resto
        adotado = ws.ja_existe_no_disco(EXAMPLES_ID)
        ws.create_workspace("Exemplos", ws.COLORS[0])
        if adotado and not force:
            return EXAMPLES_ID
    elif not force:
        return EXAMPLES_ID

    ws.write_tree(EXAMPLES_ID, examples_tree())
    return EXAMPLES_ID


def seed() -> None:
    registry = ws.list_workspaces()
    ensure_examples()
    if not registry["workspaces"]:
        ws.set_active(EXAMPLES_ID)
