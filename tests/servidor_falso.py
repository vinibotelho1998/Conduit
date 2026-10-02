# -*- coding: utf-8 -*-
"""Servidor SFTP local, so pros testes.

Serve uma pasta temporaria numa porta livre da propria maquina. E paramiko dos dois
lados, entao o que o teste exercita e o protocolo de verdade, e nao um dublê que
concorda com tudo que o cliente faz.
"""

import os
import socket
import threading

import paramiko
from paramiko import SFTPAttributes, SFTPServer, SFTPServerInterface, SFTPHandle, SFTP_OK

USUARIO = "vini"
SENHA = "segredo-do-teste"

# chaves publicas que o teste cadastra pra exercitar o login por chave privada
CHAVES_ACEITAS: list = []


class Servidor(paramiko.ServerInterface):
    def check_auth_password(self, username, password):
        if username == USUARIO and password == SENHA:
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def check_auth_publickey(self, username, key):
        if username == USUARIO and any(key.asbytes() == c.asbytes() for c in CHAVES_ACEITAS):
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED

    def get_allowed_auths(self, username):
        return "password,publickey"


class Handle(SFTPHandle):
    def stat(self):
        try:
            return SFTPAttributes.from_stat(os.fstat(self.readfile.fileno()))
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)

    def chattr(self, attr):
        return SFTP_OK


class Interface(SFTPServerInterface):
    RAIZ = ""
    RENOMEAR_ATOMICO = True

    def _real(self, caminho):
        return os.path.join(self.RAIZ, caminho.lstrip("/").replace("/", os.sep))

    def list_folder(self, path):
        try:
            saida = []
            for nome in os.listdir(self._real(path)):
                attr = SFTPAttributes.from_stat(os.stat(os.path.join(self._real(path), nome)))
                attr.filename = nome
                saida.append(attr)
            return saida
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)

    def stat(self, path):
        try:
            return SFTPAttributes.from_stat(os.stat(self._real(path)))
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)

    def lstat(self, path):
        try:
            return SFTPAttributes.from_stat(os.lstat(self._real(path)))
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)

    def open(self, path, flags, attr):
        real = self._real(path)
        try:
            binario = getattr(os, "O_BINARY", 0)
            fd = os.open(real, flags | binario)
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_APPEND):
            modo = "r+b" if flags & os.O_RDWR else "wb"
        else:
            modo = "rb"
        try:
            arquivo = os.fdopen(fd, modo)
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)
        alca = Handle(flags)
        alca.filename = real
        alca.readfile = arquivo
        alca.writefile = arquivo
        return alca

    def remove(self, path):
        try:
            os.remove(self._real(path))
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)
        return SFTP_OK

    def rename(self, oldpath, newpath):
        # O rename SFTP padrao deve recusar um destino existente em qualquer SO.
        if os.path.lexists(self._real(newpath)):
            return paramiko.SFTP_FAILURE
        try:
            os.rename(self._real(oldpath), self._real(newpath))
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)
        return SFTP_OK

    def posix_rename(self, oldpath, newpath):
        if not self.RENOMEAR_ATOMICO:
            return paramiko.SFTP_OP_UNSUPPORTED
        try:
            os.replace(self._real(oldpath), self._real(newpath))
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)
        return SFTP_OK

    def mkdir(self, path, attr):
        try:
            os.mkdir(self._real(path))
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)
        return SFTP_OK

    def rmdir(self, path):
        try:
            os.rmdir(self._real(path))
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)
        return SFTP_OK

    def chattr(self, path, attr):
        try:
            SFTPServer.set_file_attr(self._real(path), attr)
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)
        return SFTP_OK

    def canonicalize(self, path):
        return "/" + os.path.normpath(path).replace("\\", "/").lstrip("/")


def subir(raiz: str, com_sftp: bool = True, renomear_atomico: bool = True) -> int:
    """Sobe o servidor numa porta livre e devolve a porta.

    Sem SFTP ele aceita o login e recusa o subsistema, como servidor que so da shell.
    """
    interface = type("InterfaceLocal", (Interface,), {
        "RAIZ": raiz, "RENOMEAR_ATOMICO": renomear_atomico,
    })
    chave = paramiko.RSAKey.generate(2048)

    tomada = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tomada.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tomada.bind(("127.0.0.1", 0))
    tomada.listen(5)
    porta = tomada.getsockname()[1]

    def atender():
        while True:
            try:
                canal, _ = tomada.accept()
            except OSError:
                return
            transporte = paramiko.Transport(canal)
            transporte.add_server_key(chave)
            if com_sftp:
                transporte.set_subsystem_handler("sftp", SFTPServer, interface)
            try:
                transporte.start_server(server=Servidor())
            except Exception:
                continue

    threading.Thread(target=atender, daemon=True).start()
    return porta
