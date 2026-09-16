"""Variaveis geradas na hora do envio, no padrao do Postman.

Sao as que comecam com cifrao: `{{$guid}}`, `{{$timestamp}}` e companhia. Elas nao moram
em ambiente nenhum, nao tem valor guardado e nao se preenchem. O valor nasce no momento
em que o request sai, e nasce diferente a cada envio, que e justamente o motivo de
existirem: um id de correlacao que se repete nao serve pra correlacionar nada.

Por que isto virou codigo. O app tratava `$guid` como nome comum de variavel: ele nao
existia em escopo nenhum, entao a criacao automatica gravava um `$guid` vazio no
ambiente ativo, o aviso amarelo dizia "definida mas sem valor" pra sempre, e na hora do
envio o header saia em branco. Um dos requests de exemplo que vem com o app usa
`{{$guid}}`, entao bastava abrir ele pra sujar o ambiente.

O cifrao e namespace reservado: nome com cifrao sempre resolve aqui, mesmo que exista
uma variavel gravada com o mesmo nome. Isso conserta sozinho quem ja tem um `$guid`
vazio salvo de antes.
"""

from __future__ import annotations

import random
import string
import uuid
from datetime import datetime, timezone

ALFANUMERICO = string.ascii_letters + string.digits


def _guid() -> str:
    return str(uuid.uuid4())


def _timestamp() -> str:
    return str(int(datetime.now(timezone.utc).timestamp()))


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _random_int() -> str:
    return str(random.randint(0, 1000))


def _alfanumerico() -> str:
    return "".join(random.choice(ALFANUMERICO) for _ in range(16))


def _hex() -> str:
    return uuid.uuid4().hex


# Os nomes seguem o Postman de proposito: request importado de la funciona sem edicao,
# e curl ou collection que sai daqui volta pra la do mesmo jeito.
GERADORES = {
    "$guid": _guid,
    "$randomUUID": _guid,
    "$timestamp": _timestamp,
    "$isoTimestamp": _iso,
    "$randomInt": _random_int,
    "$randomAlphaNumeric": _alfanumerico,
    "$randomHex": _hex,
}

# O que aparece na ajuda e no tooltip, na ordem em que faz sentido ler.
DESCRICAO = {
    "$guid": "uuid v4 novo a cada envio",
    "$randomUUID": "o mesmo que $guid",
    "$timestamp": "epoch em segundos, UTC",
    "$isoTimestamp": "data e hora ISO 8601 em UTC",
    "$randomInt": "inteiro de 0 a 1000",
    "$randomAlphaNumeric": "16 caracteres de letra e numero",
    "$randomHex": "32 caracteres hexadecimais",
}


def eh_dinamica(nome: str) -> bool:
    """Nome reservado, gerado na hora. Nao vira variavel de ambiente nem pede valor."""
    return (nome or "").startswith("$")


def conhecida(nome: str) -> bool:
    return nome in GERADORES


def gerar(nome: str) -> str | None:
    """Devolve um valor novo, ou None quando o nome comeca com cifrao mas nao existe.

    Nome desconhecido volta None de proposito, pra quem chamou poder avisar que o nome
    esta errado em vez de mandar texto vazio no lugar de um id.
    """
    gerador = GERADORES.get(nome)
    return gerador() if gerador else None
