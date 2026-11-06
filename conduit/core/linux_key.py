"""Chave que protege as chaves de cada cofre, fora dos workspaces do usuário."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def account_key(*, create: bool) -> bytes:
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    directory = config / "conduit"
    path = directory / "vault.key"
    if create:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not path.exists():
            # A chave só fica visível depois de gravada inteira. Duas instâncias
            # simultâneas competem pelo link sem substituir a chave vencedora.
            with tempfile.NamedTemporaryFile(dir=directory) as temporary:
                temporary.write(AESGCM.generate_key(bit_length=256))
                temporary.flush()
                os.fsync(temporary.fileno())
                try:
                    os.link(temporary.name, path)
                except FileExistsError:
                    pass
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        st = os.fstat(stream.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise PermissionError(f"A chave {path} precisa pertencer ao usuário e ter permissão 0600.")
        key = stream.read(33)
    if len(key) != 32:
        raise ValueError(f"Chave inválida em {path}")
    return key
