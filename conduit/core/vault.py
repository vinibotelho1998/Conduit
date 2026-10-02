"""Cofre de segredos do workspace.

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
import shutil
import threading
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SCHEMA_VERSION = 1
ARQUIVO = "vault.dbx"
# Entropia do DPAPI. Nao se troca junto com o nome do programa: ela entra na
# derivacao e mudar o valor torna ilegivel todo cofre ja gravado.
ENTROPIA = b"dbxwire-vault-v1"

# Um cadeado pro processo inteiro, e nao por instancia: cada tela abre o seu Vault, e o
# envio grava o token do OAuth2 de uma thread do pool enquanto a interface salva.
_TRAVA = threading.RLock()


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


    def _nova_chave(self) -> bytes:
        return AESGCM.generate_key(bit_length=256)

    def _carregar(self) -> dict[str, str]:
        if self._dados is not None:
            return self._dados

        # no Windows o replace de quem grava falha se outra thread esta com o arquivo
        # aberto pra ler, entao a leitura do disco tambem passa pelo cadeado
        with _TRAVA:
            if not self.caminho.exists():
                self._dados = {}
                return self._dados

            try:
                envelope = json.loads(self.caminho.read_text(encoding="utf-8"))
                if (not isinstance(envelope, dict) or envelope.get("schemaVersion") != SCHEMA_VERSION
                        or envelope.get("provider") != "dpapi"):
                    raise ValueError("formato de cofre nao suportado")
                chave = desproteger(base64.b64decode(envelope["wrappedKey"], validate=True))
                nonce = base64.b64decode(envelope["nonce"], validate=True)
                corpo = base64.b64decode(envelope["ciphertext"], validate=True)
                claro = AESGCM(chave).decrypt(nonce, corpo, ENTROPIA)
                dados = json.loads(claro.decode("utf-8"))
                if (not isinstance(dados, dict)
                        or not all(isinstance(k, str) and isinstance(v, str) for k, v in dados.items())):
                    raise ValueError("conteudo do cofre precisa ser um mapa de segredos")
                self._dados = dados
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
        try:
            temporario.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
            if self._erro and self.caminho.exists():
                # Preserva o original ate o replace final. Se o disco encher ou o
                # replace falhar, a versao anterior continua no caminho conhecido.
                copia = self.dir / f"{ARQUIVO}.ilegivel-{datetime.now():%Y%m%d-%H%M%S-%f}"
                shutil.copy2(self.caminho, copia)
            temporario.replace(self.caminho)
        finally:
            temporario.unlink(missing_ok=True)
        self._erro = None
        self._dados = dict(dados)

    def _para_alterar(self) -> dict[str, str]:
        """O que esta no disco agora, e nao o que esta instancia leu la atras.

        Cada tela pega o seu Vault. O de um dialogo aberto ha minutos nao sabe o que o
        salvar automatico gravou nesse meio tempo, e gravar a partir dele apagava o
        segredo que tinha acabado de entrar.
        """
        self._dados = None
        self._erro = None
        return dict(self._carregar())


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
        with _TRAVA:
            dados = self._para_alterar()
            if valor:
                dados[chave] = valor
            else:
                dados.pop(chave, None)
            self._gravar(dados)

    def set_muitos(self, pares: dict[str, str]) -> int:
        """Grava varios de uma vez, que e o caso da gravacao do workspace."""
        with _TRAVA:
            dados = self._para_alterar()
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
        with _TRAVA:
            dados = self._para_alterar()
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
