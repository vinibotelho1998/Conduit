"""Acesso SFTP: perfil de conexao, navegacao e transferencia de arquivo.

Por que isso mora num cliente de API. O trabalho de integracao raramente acaba na
resposta HTTP: o arquivo que alimenta a chamada, o retorno em lote que o parceiro
deposita, o log que o servidor guarda, tudo isso viaja por SFTP. Ter as duas coisas na
mesma janela, com o mesmo cofre e o mesmo workspace, evita a peregrinacao pro FileZilla
com a senha anotada num bloco de notas ao lado.

Tres decisoes que valem o comentario:

Chave do servidor. A politica NAO e aceitar qualquer chave. Servidor desconhecido faz a
conexao parar com `ChaveDesconhecida`, que carrega a impressao digital pra tela mostrar;
so depois de alguem dizer que confia a chave entra no `known_hosts` do workspace. Aceitar
calado e o que transforma um ataque no meio do caminho em algo que ninguem percebe, e e
exatamente o padrao que a maioria dos exemplos de paramiko ensina.

Segredo. Senha e frase da chave privada nunca encostam no YAML versionado. Elas vao pro
mesmo cofre AES-256-GCM das variaveis secretas, sob as chaves `sftp:<id>:senha` e
`sftp:<id>:frase`, e o arquivo do workspace guarda so o contrato: host, porta, usuario e
onde fica a chave.

Uma conexao por vez. O SFTPClient do paramiko nao e seguro pra usar de duas threads ao
mesmo tempo. Aqui cada `Conexao` tem um cadeado proprio e toda operacao passa por ele,
entao a interface pode disparar de onde quiser sem risco de embaralhar dois pedidos no
mesmo canal.
"""

from __future__ import annotations

import posixpath
import secrets
import stat as statmod
import threading
import time
from dataclasses import dataclass
from pathlib import Path

PORTA_PADRAO = 22
TEMPO_CONEXAO = 20

# Ate onde vale a pena abrir um arquivo pra espiar dentro do proprio app. Acima disso a
# resposta certa e baixar, nao encher a memoria com um dump de 400 MB.
LIMITE_ESPIADA = 512 * 1024

AUTH = {
    "senha": "Usuario e senha",
    "chave": "Chave privada",
    "agente": "Agente de chaves do sistema",
}

CHAVE_SENHA = "sftp:{id}:senha"
CHAVE_FRASE = "sftp:{id}:frase"


class ErroSftp(Exception):
    """Falha que a tela sabe mostrar sem precisar traduzir nada."""


class ChaveDesconhecida(ErroSftp):
    """O servidor apresentou uma chave que este workspace ainda nao viu."""

    def __init__(self, host: str, tipo: str, digital: str):
        super().__init__(f"{host} apresentou uma chave {tipo} ainda nao conhecida")
        self.host = host
        self.tipo = tipo
        self.digital = digital


class ChaveTrocada(ErroSftp):
    """A chave do servidor mudou desde a ultima vez. Pode ser troca legitima, pode nao ser."""

    def __init__(self, host: str, digital: str):
        super().__init__(
            f"a chave de {host} mudou desde a ultima conexao. "
            "Confirme com quem cuida do servidor antes de seguir"
        )
        self.host = host
        self.digital = digital


def novo_id() -> str:
    return f"sftp-{secrets.token_hex(3)}"


@dataclass
class Perfil:
    """Um servidor guardado. So o contrato, nunca o segredo."""

    id: str = ""
    nome: str = ""
    host: str = ""
    porta: int = PORTA_PADRAO
    usuario: str = ""
    auth: str = "senha"
    chave: str = ""          # caminho do arquivo de chave privada
    raiz: str = ""           # pasta em que abrir, vazio quer dizer a do usuario

    @classmethod
    def de_dict(cls, dados: dict) -> "Perfil":
        return cls(
            id=dados.get("id") or novo_id(),
            nome=dados.get("name") or dados.get("host") or "servidor",
            host=dados.get("host") or "",
            porta=int(dados.get("port") or PORTA_PADRAO),
            usuario=dados.get("user") or "",
            auth=dados.get("auth") or "senha",
            chave=dados.get("keyFile") or "",
            raiz=dados.get("root") or "",
        )

    def para_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.nome,
            "host": self.host,
            "port": self.porta,
            "user": self.usuario,
            "auth": self.auth,
            "keyFile": self.chave,
            "root": self.raiz,
        }

    def rotulo(self) -> str:
        porta = "" if self.porta == PORTA_PADRAO else f":{self.porta}"
        return f"{self.usuario}@{self.host}{porta}" if self.usuario else f"{self.host}{porta}"

    def problema(self) -> str:
        """O que impede este perfil de conectar, em uma frase, ou vazio."""
        if not self.host.strip():
            return "falta o endereco do servidor"
        if not self.usuario.strip():
            return "falta o usuario"
        if not 1 <= self.porta <= 65535:
            return "a porta precisa estar entre 1 e 65535"
        if self.auth == "chave":
            if not self.chave.strip():
                return "falta apontar o arquivo da chave privada"
            if not Path(self.chave).exists():
                return f"nao encontrei a chave em {self.chave}"
        return ""


def listar_perfis(tree: dict) -> list[Perfil]:
    return [Perfil.de_dict(item) for item in tree.get("sftp") or []]


def gravar_perfis(tree: dict, perfis: list[Perfil]) -> None:
    tree["sftp"] = [p.para_dict() for p in perfis]


@dataclass
class Entrada:
    """Uma linha do diretorio remoto."""

    nome: str
    caminho: str
    pasta: bool = False
    link: bool = False
    tamanho: int = 0
    modificado: float = 0.0
    modo: int = 0

    def permissoes(self) -> str:
        return statmod.filemode(self.modo) if self.modo else ""

    def quando(self) -> str:
        if not self.modificado:
            return ""
        marca = time.localtime(self.modificado)
        # ano so aparece quando nao e deste ano, igual ao ls: economiza coluna no caso
        # comum e nao esconde a informacao no caso raro
        formato = "%d/%m %H:%M" if marca.tm_year == time.localtime().tm_year else "%d/%m/%Y"
        return time.strftime(formato, marca)

    def tamanho_legivel(self) -> str:
        if self.pasta:
            return ""
        valor = float(self.tamanho)
        for unidade in ("B", "KB", "MB", "GB", "TB"):
            if valor < 1024 or unidade == "TB":
                return f"{valor:.0f} {unidade}" if unidade == "B" else f"{valor:.1f} {unidade}"
            valor /= 1024
        return ""

    def ordenacao(self) -> tuple:
        # pasta antes de arquivo, e dentro de cada grupo em ordem alfabetica sem ligar
        # pra maiuscula, que e como todo gerenciador de arquivo se comporta
        return (0 if self.pasta else 1, self.nome.lower())


def juntar(base: str, nome: str) -> str:
    return posixpath.normpath(posixpath.join(base or "/", nome))


def pai(caminho: str) -> str:
    return posixpath.dirname(caminho.rstrip("/")) or "/"


def migalhas(caminho: str) -> list[tuple[str, str]]:
    """A trilha do caminho, como pares de rotulo e destino, pra barra de navegacao."""
    caminho = posixpath.normpath(caminho or "/")
    trilha = [("/", "/")]
    acumulado = ""
    for pedaco in caminho.strip("/").split("/"):
        if not pedaco:
            continue
        acumulado = f"{acumulado}/{pedaco}"
        trilha.append((pedaco, acumulado))
    return trilha


class Conexao:
    """Uma sessao SFTP aberta. Toda operacao passa pelo cadeado interno."""

    def __init__(self, perfil: Perfil, known_hosts: str | Path):
        self.perfil = perfil
        self.known_hosts = Path(known_hosts)
        self._cliente = None
        self._sftp = None
        self._cadeado = threading.RLock()
        self.digital = ""

    # -------------------------------------------------------------------- abrir e fechar

    def abrir(self, senha: str = "", frase: str = "", confiar: bool = False) -> None:
        """Conecta. Levanta ChaveDesconhecida quando o servidor ainda nao e conhecido.

        `confiar` e a resposta afirmativa de quem viu a impressao digital na tela: so ele
        autoriza gravar a chave nova no known_hosts do workspace.
        """
        import paramiko

        problema = self.perfil.problema()
        if problema:
            raise ErroSftp(problema)

        cliente = paramiko.SSHClient()
        self.known_hosts.parent.mkdir(parents=True, exist_ok=True)
        if self.known_hosts.exists():
            try:
                cliente.load_host_keys(str(self.known_hosts))
            except OSError:
                pass
        cliente.set_missing_host_key_policy(_Politica(self, confiar))

        chave = None
        if self.perfil.auth == "chave":
            chave = _carregar_chave(self.perfil.chave, frase)

        try:
            cliente.connect(
                hostname=self.perfil.host,
                port=self.perfil.porta,
                username=self.perfil.usuario,
                password=senha or None if self.perfil.auth == "senha" else None,
                pkey=chave,
                allow_agent=self.perfil.auth == "agente",
                look_for_keys=self.perfil.auth == "agente",
                timeout=TEMPO_CONEXAO,
                auth_timeout=TEMPO_CONEXAO,
                banner_timeout=TEMPO_CONEXAO,
            )
        except ErroSftp:
            cliente.close()
            raise
        except paramiko.BadHostKeyException as exc:
            cliente.close()
            raise ChaveTrocada(self.perfil.host, _digital(exc.key)) from exc
        except paramiko.AuthenticationException as exc:
            cliente.close()
            raise ErroSftp(
                "usuario ou credencial recusados pelo servidor"
                if self.perfil.auth == "senha"
                else "o servidor recusou esta chave para este usuario"
            ) from exc
        except paramiko.SSHException as exc:
            cliente.close()
            raise ErroSftp(f"nao consegui abrir a sessao SSH: {exc}") from exc
        except OSError as exc:
            cliente.close()
            raise ErroSftp(f"nao alcancei {self.perfil.host}:{self.perfil.porta}: {exc}") from exc

        transporte = cliente.get_transport()
        if transporte is not None:
            # o servidor derruba sessao parada, e reconectar no meio de uma navegacao e
            # o tipo de atrito que faz a pessoa voltar pro cliente antigo
            transporte.set_keepalive(30)
            chave_servidor = transporte.get_remote_server_key()
            if chave_servidor is not None:
                self.digital = _digital(chave_servidor)

        self._cliente = cliente
        self._sftp = cliente.open_sftp()
        if self.perfil.raiz:
            try:
                self._sftp.chdir(self.perfil.raiz)
            except OSError:
                pass

    def fechar(self) -> None:
        with self._cadeado:
            for alvo in (self._sftp, self._cliente):
                try:
                    if alvo is not None:
                        alvo.close()
                except Exception:  # noqa: BLE001
                    pass
            self._sftp = None
            self._cliente = None

    @property
    def aberta(self) -> bool:
        transporte = self._cliente.get_transport() if self._cliente is not None else None
        return bool(transporte is not None and transporte.is_active())

    def _canal(self):
        if self._sftp is None:
            raise ErroSftp("a conexao nao esta aberta")
        return self._sftp

    # ------------------------------------------------------------------------ navegacao

    def inicio(self) -> str:
        """A pasta em que abrir: a do perfil, senao a do usuario no servidor."""
        with self._cadeado:
            if self.perfil.raiz:
                return posixpath.normpath(self.perfil.raiz)
            try:
                # nem todo servidor devolve o caminho ja limpo; um deles respondia "/."
                return posixpath.normpath(self._canal().normalize("."))
            except OSError:
                return "/"

    def normalizar(self, caminho: str) -> str:
        with self._cadeado:
            try:
                return self._canal().normalize(caminho or ".")
            except OSError as exc:
                raise ErroSftp(f"{caminho}: {exc}") from exc

    def listar(self, caminho: str, ocultos: bool = False) -> list[Entrada]:
        with self._cadeado:
            canal = self._canal()
            try:
                atributos = canal.listdir_attr(caminho)
            except FileNotFoundError as exc:
                raise ErroSftp(f"a pasta {caminho} nao existe mais") from exc
            except PermissionError as exc:
                raise ErroSftp(f"sem permissao de leitura em {caminho}") from exc
            except OSError as exc:
                raise ErroSftp(f"nao consegui listar {caminho}: {exc}") from exc

            saida = []
            for item in atributos:
                nome = item.filename
                if not ocultos and nome.startswith("."):
                    continue
                modo = item.st_mode or 0
                link = statmod.S_ISLNK(modo)
                pasta = statmod.S_ISDIR(modo)
                completo = juntar(caminho, nome)
                if link:
                    # o alvo do link e que decide se da pra entrar; sem resolver, uma
                    # pasta apontada por link parecia arquivo e o duplo clique nao fazia nada
                    try:
                        pasta = statmod.S_ISDIR(canal.stat(completo).st_mode or 0)
                    except OSError:
                        pasta = False
                saida.append(
                    Entrada(
                        nome=nome,
                        caminho=completo,
                        pasta=pasta,
                        link=link,
                        tamanho=item.st_size or 0,
                        modificado=float(item.st_mtime or 0),
                        modo=modo,
                    )
                )
            saida.sort(key=Entrada.ordenacao)
            return saida

    # --------------------------------------------------------------------- transferencia

    def baixar(self, remoto: str, local: str | Path, progresso=None) -> Path:
        destino = Path(local)
        with self._cadeado:
            destino.parent.mkdir(parents=True, exist_ok=True)
            # grava num .parcial e so renomeia no fim: transferencia interrompida nao
            # deixa pra tras um arquivo pela metade com o nome do arquivo bom
            parcial = destino.with_name(destino.name + ".parcial")
            try:
                self._canal().get(remoto, str(parcial), callback=progresso)
                parcial.replace(destino)
            except OSError as exc:
                parcial.unlink(missing_ok=True)
                raise ErroSftp(f"falhou ao baixar {posixpath.basename(remoto)}: {exc}") from exc
        return destino

    def enviar(self, local: str | Path, remoto: str, progresso=None) -> str:
        origem = Path(local)
        if not origem.is_file():
            raise ErroSftp(f"{origem} nao e um arquivo")
        with self._cadeado:
            try:
                self._canal().put(str(origem), remoto, callback=progresso, confirm=True)
            except OSError as exc:
                raise ErroSftp(f"falhou ao enviar {origem.name}: {exc}") from exc
        return remoto

    def espiar(self, caminho: str, limite: int = LIMITE_ESPIADA) -> tuple[str, bool]:
        """Le o comeco do arquivo como texto. Devolve o texto e se ele foi cortado."""
        with self._cadeado:
            try:
                with self._canal().open(caminho, "rb") as arquivo:
                    arquivo.prefetch()
                    bruto = arquivo.read(limite + 1)
            except OSError as exc:
                raise ErroSftp(f"nao consegui abrir {posixpath.basename(caminho)}: {exc}") from exc
        cortado = len(bruto) > limite
        if b"\0" in bruto[:8192]:
            raise ErroSftp("este arquivo e binario, use Baixar em vez de abrir")
        return bruto[:limite].decode("utf-8", errors="replace"), cortado

    # ---------------------------------------------------------------------- manutencao

    def criar_pasta(self, caminho: str) -> None:
        with self._cadeado:
            try:
                self._canal().mkdir(caminho)
            except OSError as exc:
                raise ErroSftp(f"nao consegui criar {caminho}: {exc}") from exc

    def renomear(self, de: str, para: str) -> None:
        with self._cadeado:
            canal = self._canal()
            try:
                # posix_rename troca o destino de forma atomica, mas depende de uma
                # extensao do OpenSSH que nem todo servidor anuncia; o rename comum fica
                # de reserva pros que nao tem
                canal.posix_rename(de, para)
            except (AttributeError, OSError):
                try:
                    canal.rename(de, para)
                except OSError as exc:
                    raise ErroSftp(f"nao consegui renomear: {exc}") from exc

    def remover(self, entrada: Entrada) -> None:
        with self._cadeado:
            canal = self._canal()
            try:
                if entrada.pasta and not entrada.link:
                    canal.rmdir(entrada.caminho)
                else:
                    canal.remove(entrada.caminho)
            except OSError as exc:
                if entrada.pasta:
                    raise ErroSftp(
                        f"nao consegui apagar {entrada.nome}. "
                        "Pasta precisa estar vazia pra ser removida"
                    ) from exc
                raise ErroSftp(f"nao consegui apagar {entrada.nome}: {exc}") from exc


class _Politica:
    """O que fazer com a chave de um servidor que o workspace ainda nao viu."""

    def __init__(self, conexao: Conexao, confiar: bool):
        self.conexao = conexao
        self.confiar = confiar

    def missing_host_key(self, cliente, hostname, chave):
        digital = _digital(chave)
        if not self.confiar:
            raise ChaveDesconhecida(hostname, chave.get_name(), digital)
        cliente.get_host_keys().add(hostname, chave.get_name(), chave)
        try:
            cliente.get_host_keys().save(str(self.conexao.known_hosts))
        except OSError:
            # sem gravar, a proxima conexao pergunta de novo. Melhor perguntar duas vezes
            # do que confiar sem registro.
            pass


def _digital(chave) -> str:
    """Impressao digital no formato que o OpenSSH mostra, pra dar pra comparar."""
    import base64
    import hashlib

    resumo = hashlib.sha256(chave.asbytes()).digest()
    return "SHA256:" + base64.b64encode(resumo).decode("ascii").rstrip("=")


def _carregar_chave(caminho: str, frase: str):
    """Le a chave privada sem exigir que a pessoa saiba de que tipo ela e."""
    import paramiko

    alvo = Path(caminho)
    if not alvo.exists():
        raise ErroSftp(f"nao encontrei a chave em {alvo}")

    erro_frase = False
    for classe in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey, paramiko.DSSKey):
        try:
            return classe.from_private_key_file(str(alvo), password=frase or None)
        except paramiko.PasswordRequiredException:
            erro_frase = True
        except paramiko.SSHException:
            continue
        except OSError as exc:
            raise ErroSftp(f"nao consegui ler a chave: {exc}") from exc

    if erro_frase:
        raise ErroSftp("esta chave privada e protegida por frase secreta")
    raise ErroSftp("nao reconheci o formato desta chave privada")
