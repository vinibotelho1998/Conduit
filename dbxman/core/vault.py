"""Cofre de segredos do workspace, conforme a secao 5.2 do PLANO.md.

Modelo de envelope. Uma chave de conteudo aleatoria de 32 bytes cifra o cofre em
AES-256-GCM. Essa chave e que fica protegida, e o provedor de protecao e trocavel:

    chave de conteudo aleatoria
            |
            +-- envelope DPAPI, amarrado a sua conta Windows
            +-- envelope por senha mestra, derivada com scrypt
            |
       .secrets/vault.dbx  em AES-256-GCM

Ganho do envelope: ligar ou desligar a senha mestra troca so o envelope, nunca recifra
o conteudo.

Por que isso existe. Sem cofre, o valor da variavel marcada como secreta ficava em texto
puro dentro de environments/*.yaml, que e justamente o arquivo que vai pro git. Todo o
resto do caminho ja estava protegido, historico, codigo gerado e espiada, mas a fonte
estava aberta.
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import secrets
from ctypes import wintypes
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SCHEMA_VERSION = 1
ARQUIVO = "vault.dbx"
ENTROPIA = b"dbxwire-vault-v1"


# ------------------------------------------------------------------- DPAPI


class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _para_blob(dados: bytes):
    buffer = ctypes.create_string_buffer(dados, len(dados))
    return _BLOB(len(dados), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _dpapi(funcao: str, dados: bytes) -> bytes:
    """Chama CryptProtectData ou CryptUnprotectData sem depender de pywin32."""
    if os.name != "nt":
        raise OSError("DPAPI so existe no Windows")

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    entrada, _guarda1 = _para_blob(dados)
    extra, _guarda2 = _para_blob(ENTROPIA)
    saida = _BLOB()

    metodo = getattr(crypt32, funcao)
    ok = metodo(
        ctypes.byref(entrada), None, ctypes.byref(extra), None, None, 0, ctypes.byref(saida)
    )
    if not ok:
        raise OSError(f"{funcao} falhou, codigo {kernel32.GetLastError()}")

    try:
        return ctypes.string_at(saida.pbData, saida.cbData)
    finally:
        kernel32.LocalFree(saida.pbData)


def proteger(dados: bytes) -> bytes:
    return _dpapi("CryptProtectData", dados)


def desproteger(dados: bytes) -> bytes:
    return _dpapi("CryptUnprotectData", dados)


# -------------------------------------------------------------------- cofre


def chave_de(env_id: str, nome: str) -> str:
    """Nome do segredo dentro do cofre, separado por ambiente."""
    return f"env:{env_id}:{nome}"


class Vault:
    """Cofre de um workspace. Abre sozinho quando o provedor e DPAPI."""

    def __init__(self, workspace_path: str | Path):
        self.dir = Path(workspace_path) / ".secrets"
        self.caminho = self.dir / ARQUIVO
        self._dados: dict[str, str] | None = None
        self._erro: str | None = None

    # ------------------------------------------------------------- interno

    def _nova_chave(self) -> bytes:
        return AESGCM.generate_key(bit_length=256)

    def _carregar(self) -> dict[str, str]:
        if self._dados is not None:
            return self._dados

        if not self.caminho.exists():
            self._dados = {}
            return self._dados

        try:
            envelope = json.loads(self.caminho.read_text(encoding="utf-8"))
            chave = desproteger(base64.b64decode(envelope["wrappedKey"]))
            nonce = base64.b64decode(envelope["nonce"])
            corpo = base64.b64decode(envelope["ciphertext"])
            claro = AESGCM(chave).decrypt(nonce, corpo, ENTROPIA)
            self._dados = json.loads(claro.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            # cofre de outra conta Windows, arquivo corrompido, ou provedor indisponivel
            self._erro = f"{type(exc).__name__}: {exc}"
            self._dados = {}
        return self._dados

    def _gravar(self, dados: dict[str, str]) -> None:
        chave = self._nova_chave()
        nonce = secrets.token_bytes(12)
        corpo = AESGCM(chave).encrypt(nonce, json.dumps(dados, ensure_ascii=False).encode("utf-8"), ENTROPIA)

        envelope = {
            "schemaVersion": SCHEMA_VERSION,
            "provider": "dpapi",
            "wrappedKey": base64.b64encode(proteger(chave)).decode("ascii"),
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(corpo).decode("ascii"),
        }

        self.dir.mkdir(parents=True, exist_ok=True)
        temporario = self.caminho.with_suffix(".tmp")
        temporario.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
        temporario.replace(self.caminho)
        self._dados = dict(dados)

    # ------------------------------------------------------------- publico

    @property
    def erro(self) -> str | None:
        self._carregar()
        return self._erro

    @property
    def disponivel(self) -> bool:
        return os.name == "nt"

    def get(self, chave: str, padrao: str = "") -> str:
        return self._carregar().get(chave, padrao)

    def set(self, chave: str, valor: str) -> None:
        dados = dict(self._carregar())
        if valor:
            dados[chave] = valor
        else:
            dados.pop(chave, None)
        self._gravar(dados)

    def set_muitos(self, pares: dict[str, str]) -> int:
        """Grava varios de uma vez, que e o caso da gravacao do workspace."""
        dados = dict(self._carregar())
        antes = dict(dados)
        for chave, valor in pares.items():
            if valor:
                dados[chave] = valor
            else:
                dados.pop(chave, None)
        if dados == antes:
            return 0
        self._gravar(dados)
        return len(dados)

    def remover_prefixo(self, prefixo: str) -> int:
        dados = dict(self._carregar())
        alvos = [c for c in dados if c.startswith(prefixo)]
        for chave in alvos:
            dados.pop(chave)
        if alvos:
            self._gravar(dados)
        return len(alvos)

    def chaves(self) -> list[str]:
        return sorted(self._carregar())

    def resumo(self) -> dict:
        dados = self._carregar()
        return {
            "total": len(dados),
            "arquivo": str(self.caminho),
            "existe": self.caminho.exists(),
            "erro": self._erro,
        }
