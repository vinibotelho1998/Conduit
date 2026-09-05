"""Exemplos de resposta salvos dentro do proprio request.

Servem pra tres coisas: mostrar como a API responde sem precisar chamar, virar a
documentacao da collection quando ela for compartilhada, e mais pra frente alimentar o
mock. Por isso moram no arquivo do request, e nao no historico: o historico e do que
voce executou e fica fora do git, o exemplo e do contrato e vai junto.

Como o arquivo do request e versionado, o exemplo passa pelo mesmo tratamento do
historico antes de ser gravado. O valor do segredo volta a ser {{nome}}, e header de
credencial sai mascarado. Sem isso, salvar um exemplo seria o jeito mais facil de
mandar um token pro git sem perceber.
"""

from __future__ import annotations

import secrets as _secrets
from datetime import datetime

from .history import MASK_KEYS, _mask
from .vars import redact

LIMITE_CORPO = 200_000


def novo_id() -> str:
    return f"ex-{_secrets.token_hex(3)}"


def _pares(headers, ledger) -> list[list[str]]:
    if isinstance(headers, dict):
        itens = list(headers.items())
    else:
        itens = [(p[0], p[1]) for p in headers or []]
    saida = []
    for chave, valor in itens:
        texto = redact(str(valor), ledger)
        if str(chave).lower() in MASK_KEYS and "{{" not in texto:
            texto = _mask(texto)
        saida.append([str(chave), texto])
    return saida


def _corpo(texto: str, ledger) -> str:
    limpo = redact(texto or "", ledger)
    if len(limpo) > LIMITE_CORPO:
        return limpo[:LIMITE_CORPO] + "\n\n... cortado ao salvar o exemplo"
    return limpo


def montar(nome: str, resultado: dict, enviado: dict | None, ledger=None) -> dict:
    """Monta o exemplo a partir do que voltou e do que foi enviado."""
    ledger = list(ledger or [])
    enviado = enviado or {}
    return {
        "id": novo_id(),
        "name": nome,
        "savedAt": datetime.now().isoformat(timespec="seconds"),
        "status": resultado.get("status"),
        "reason": resultado.get("reason") or "",
        "ok": bool(resultado.get("ok")),
        "error": resultado.get("error") or "",
        "elapsedMs": resultado.get("elapsedMs"),
        "sizeBytes": resultado.get("sizeBytes"),
        "request": {
            "method": enviado.get("method") or "",
            "url": redact(enviado.get("url") or "", ledger),
            "headers": _pares(enviado.get("headers") or {}, ledger),
            "body": _corpo(enviado.get("body") or "", ledger),
        },
        "response": {
            "headers": _pares(resultado.get("headers") or [], ledger),
            "body": _corpo(resultado.get("body") or "", ledger),
        },
    }


def para_resposta(exemplo: dict) -> tuple[dict, dict]:
    """Devolve o par que o painel de resposta consome, no formato de um envio de verdade."""
    resposta = exemplo.get("response") or {}
    pedido = exemplo.get("request") or {}
    corpo = resposta.get("body") or ""
    dados = {
        "ok": bool(exemplo.get("ok", True)),
        "error": exemplo.get("error") or "",
        "status": exemplo.get("status"),
        "reason": exemplo.get("reason") or "",
        "elapsedMs": exemplo.get("elapsedMs"),
        # exemplo antigo gravava a chave como "size"; le as duas pra nao perder o que ja
        # esta no disco
        "sizeBytes": (
            exemplo.get("sizeBytes")
            if exemplo.get("sizeBytes") is not None
            else exemplo.get("size", len(corpo.encode("utf-8")))
        ),
        "headers": [(p[0], p[1]) for p in resposta.get("headers") or []],
        "body": corpo,
        "url": pedido.get("url") or "",
        "cookies": {},
        "exemplo": exemplo.get("name") or "exemplo",
    }
    enviado = {
        "method": pedido.get("method") or "",
        "url": pedido.get("url") or "",
        "headers": {p[0]: p[1] for p in pedido.get("headers") or []},
        "body": pedido.get("body") or "",
    }
    return dados, enviado


def resumo(exemplo: dict) -> str:
    partes = [str(exemplo.get("status") or "?")]
    quando = (exemplo.get("savedAt") or "")[:16].replace("T", " ")
    if quando:
        partes.append(quando)
    tamanho = exemplo.get("sizeBytes") or exemplo.get("size")
    if tamanho:
        partes.append(f"{tamanho} B")
    return "   ·   ".join(partes)
