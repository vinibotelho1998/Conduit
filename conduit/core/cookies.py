"""Cookie jar por dominio, guardado no workspace.

Sem isso, fluxo que depende de sessao nao funciona: o servidor manda Set-Cookie, e a
chamada seguinte sai sem o Cookie de volta. O jar fica fora do git, junto com o cofre e
o historico, porque cookie de sessao e credencial.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse


class CookieJar:
    def __init__(self, workspace_path: str | Path):
        self.caminho = Path(workspace_path) / "cookies" / "jar.json"
        self._dados: dict[str, dict[str, str]] | None = None

    def _carregar(self) -> dict[str, dict[str, str]]:
        if self._dados is None:
            try:
                dados = json.loads(self.caminho.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                dados = {}
            # O jar e lido em todo envio. Arquivo que nao e mapa de host pra mapa de
            # cookie, ou que nao e UTF-8, estourava ali, e nenhum request saia mais.
            if not isinstance(dados, dict):
                dados = {}
            self._dados = {h: c for h, c in dados.items() if isinstance(c, dict)}
        return self._dados

    def _gravar(self) -> None:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        temporario = self.caminho.with_suffix(".tmp")
        temporario.write_text(
            json.dumps(self._carregar(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        temporario.replace(self.caminho)

    @staticmethod
    def _host(url: str) -> str:
        return (urlparse(url).hostname or "").lower()

    def para_url(self, url: str) -> dict[str, str]:
        return dict(self._carregar().get(self._host(url), {}))

    def guardar(self, url: str, cookies: dict) -> int:
        if not cookies:
            return 0
        host = self._host(url)
        if not host:
            return 0
        dados = self._carregar()
        dados.setdefault(host, {}).update({str(k): str(v) for k, v in cookies.items()})
        self._gravar()
        return len(cookies)

    def limpar(self, host: str | None = None) -> int:
        dados = self._carregar()
        if host:
            quantos = len(dados.pop(host, {}))
        else:
            quantos = sum(len(v) for v in dados.values())
            dados.clear()
        self._gravar()
        return quantos

    def resumo(self) -> dict:
        dados = self._carregar()
        return {
            "dominios": len(dados),
            "cookies": sum(len(v) for v in dados.values()),
            "arquivo": str(self.caminho),
        }

    def tudo(self) -> dict[str, dict[str, str]]:
        return dict(self._carregar())
