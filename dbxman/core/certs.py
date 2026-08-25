"""Certificado cliente por host, o mTLS.

Por que isso existe aqui. Varios bancos e orgaos publicos exigem certificado cliente
`.pfx`, e o Postman trata isso mal. httpx e a `ssl` do Python nao carregam `.pfx`
direto, so PEM, entao o arquivo e convertido em memoria e escrito num PEM temporario
com permissao restrita, usado no handshake e apagado logo depois.

A senha do `.pfx` nunca fica no arquivo de configuracao: ela vive no cofre, com a mesma
protecao das variaveis secretas.
"""

from __future__ import annotations

import os
import ssl
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12

CHAVE_SENHA = "cert:{host}:senha"


@dataclass
class Certificado:
    host: str
    arquivo: str
    ativo: bool = True

    def combina(self, url: str) -> bool:
        alvo = (urlparse(url).hostname or "").lower()
        padrao = (self.host or "").lower().strip()
        if not padrao or not alvo:
            return False
        if padrao.startswith("*."):
            return alvo == padrao[2:] or alvo.endswith(padrao[1:])
        return alvo == padrao


def listar(tree: dict) -> list[Certificado]:
    return [
        Certificado(
            host=item.get("host") or "",
            arquivo=item.get("file") or "",
            ativo=item.get("enabled", True) is not False,
        )
        for item in tree.get("certificates") or []
    ]


def para_url(tree: dict, url: str) -> Certificado | None:
    for cert in listar(tree):
        if cert.ativo and cert.combina(url):
            return cert
    return None


def _pem_de_pfx(caminho: Path, senha: str) -> bytes:
    dados = caminho.read_bytes()
    chave, certificado, cadeia = pkcs12.load_key_and_certificates(
        dados, senha.encode("utf-8") if senha else None
    )
    if chave is None or certificado is None:
        raise ValueError("o pfx nao trouxe chave privada e certificado")

    partes = [
        chave.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ),
        certificado.public_bytes(serialization.Encoding.PEM),
    ]
    for extra in cadeia or []:
        partes.append(extra.public_bytes(serialization.Encoding.PEM))
    return b"".join(partes)


def contexto_verificacao(ca_arquivo: str) -> ssl.SSLContext:
    """Contexto que confia tambem na CA que voce apontou.

    Serve pro caso classico de servidor que devolve a cadeia incompleta ou que usa CA
    interna: sem isso a unica saida seria desligar a verificacao do request inteiro, o
    que troca um problema pontual por um buraco permanente.
    """
    contexto = ssl.create_default_context()
    contexto.load_verify_locations(cafile=str(ca_arquivo))
    return contexto


def contexto_ssl(
    cert: Certificado, senha: str, verificar: bool = True, ca_arquivo: str = ""
) -> tuple[ssl.SSLContext, str]:
    """Monta o contexto TLS ja com a identidade do cliente carregada.

    Devolve tambem o caminho do PEM temporario, que o chamador apaga depois do envio.
    """
    caminho = Path(cert.arquivo)
    if not caminho.exists():
        raise FileNotFoundError(f"certificado nao encontrado: {caminho}")

    if caminho.suffix.lower() in (".pfx", ".p12"):
        pem = _pem_de_pfx(caminho, senha)
    else:
        pem = caminho.read_bytes()

    contexto = ssl.create_default_context()
    if ca_arquivo and Path(ca_arquivo).exists():
        contexto.load_verify_locations(cafile=str(ca_arquivo))
    if not verificar:
        contexto.check_hostname = False
        contexto.verify_mode = ssl.CERT_NONE

    descritor, temporario = tempfile.mkstemp(suffix=".pem", prefix="dbxwire-")
    try:
        os.write(descritor, pem)
    finally:
        os.close(descritor)

    if os.name == "nt":
        # tira heranca e deixa so o usuario atual, que e o dono do processo
        os.system(f'icacls "{temporario}" /inheritance:r /grant:r "%USERNAME%":F >nul 2>&1')

    contexto.load_cert_chain(temporario)
    return contexto, temporario


def descartar(temporario: str | None) -> None:
    if temporario:
        try:
            Path(temporario).unlink(missing_ok=True)
        except OSError:
            pass


def inspecionar(caminho: str, senha: str) -> dict:
    """Le o certificado e devolve o que da pra mostrar na tela, ja separado.

    Devolve dict com dono, emissor, validade, dias que faltam e erro. Em texto puro,
    como era antes, a tela nao tinha como pintar de vermelho o que ja venceu, e
    certificado vencido descoberto na hora do envio custa caro.
    """
    from datetime import datetime, timezone

    alvo = Path(caminho)
    if not alvo.exists():
        return {"erro": "arquivo nao encontrado"}
    try:
        if alvo.suffix.lower() in (".pfx", ".p12"):
            _, certificado, _ = pkcs12.load_key_and_certificates(
                alvo.read_bytes(), senha.encode("utf-8") if senha else None
            )
        else:
            from cryptography import x509

            certificado = x509.load_pem_x509_certificate(alvo.read_bytes())
    except Exception as exc:  # noqa: BLE001
        return {"erro": f"nao consegui ler: {type(exc).__name__}"}

    if certificado is None:
        return {"erro": "sem certificado dentro do arquivo"}

    fim = certificado.not_valid_after_utc
    inicio = certificado.not_valid_before_utc
    faltam = (fim - datetime.now(timezone.utc)).days
    return {
        "erro": "",
        "dono": certificado.subject.rfc4514_string(),
        "emissor": certificado.issuer.rfc4514_string(),
        "de": inicio.strftime("%d/%m/%Y"),
        "ate": fim.strftime("%d/%m/%Y"),
        "dias": faltam,
    }


def descrever(caminho: str, senha: str) -> str:
    """Le o pfx so pra mostrar quem e o dono e ate quando vale."""
    alvo = Path(caminho)
    if not alvo.exists():
        return "arquivo nao encontrado"
    try:
        if alvo.suffix.lower() in (".pfx", ".p12"):
            _, certificado, _ = pkcs12.load_key_and_certificates(
                alvo.read_bytes(), senha.encode("utf-8") if senha else None
            )
        else:
            from cryptography import x509

            certificado = x509.load_pem_x509_certificate(alvo.read_bytes())
    except Exception as exc:  # noqa: BLE001
        return f"nao consegui ler: {type(exc).__name__}"

    if certificado is None:
        return "sem certificado dentro"

    dono = certificado.subject.rfc4514_string()
    validade = certificado.not_valid_after_utc.strftime("%d/%m/%Y")
    return f"{dono[:80]}  ·  vale ate {validade}"
