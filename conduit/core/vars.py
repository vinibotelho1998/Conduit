"""Resolucao de {{variavel}} com ledger de segredo.

O ledger e o mecanismo central de seguranca do modulo: alem do texto resolvido,
devolve quais trechos vieram de variavel marcada como secreta. Historico, log e
prompt de IA usam esse ledger pra desresolver o segredo antes de gravar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import dinamicas

VAR_RE = re.compile(r"\{\{\s*([\w.$-]+)\s*\}\}")


@dataclass
class Resolved:
    text: str
    missing: list[str] = field(default_factory=list)
    secrets: list[tuple[str, str]] = field(default_factory=list)


def env_map(tree: dict) -> dict[str, dict]:
    """Mapa de variaveis do ambiente ativo. Precedencia maior fica pra frente."""
    out: dict[str, dict] = {}
    for env in tree.get("environments") or []:
        if env.get("id") != tree.get("activeEnv"):
            continue
        for item in env.get("values") or []:
            if item.get("enabled") is False or not item.get("key"):
                continue
            out[item["key"]] = {
                "value": item.get("value") or "",
                "secret": bool(item.get("secret")),
            }
    return out


def resolve(text: str, variables: dict[str, dict]) -> Resolved:
    if not isinstance(text, str) or not text:
        return Resolved(text or "")

    missing: list[str] = []
    secrets: list[tuple[str, str]] = []

    def repl(match: re.Match) -> str:
        name = match.group(1)
        # Cifrao e namespace reservado das geradas na hora, tipo {{$guid}}. Ele resolve
        # antes de olhar os escopos de proposito: quem ja tem um $guid vazio salvo de
        # quando o app nao conhecia essas variaveis nao fica preso a ele.
        if dinamicas.eh_dinamica(name):
            gerado = dinamicas.gerar(name)
            if gerado is not None:
                return gerado
            missing.append(name)
            return match.group(0)
        if name not in variables:
            missing.append(name)
            return match.group(0)
        entry = variables[name]
        if entry["secret"] and entry["value"]:
            secrets.append((name, entry["value"]))
        return entry["value"]

    return Resolved(VAR_RE.sub(repl, text), missing, secrets)


def redact(text: str, secrets: list[tuple[str, str]]) -> str:
    """Troca o valor real de volta pelo {{nome}}. Por valor, nao por nome de header."""
    out = text
    for name, value in secrets or []:
        if value:
            out = out.replace(value, "{{%s}}" % name)
    return out
