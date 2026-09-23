"""Exercita conduit/core/sftp.py contra um servidor SFTP de verdade, local.

Servidor de mentira mas protocolo de verdade: e paramiko atendendo numa porta livre da
propria maquina. Testar SFTP com dublê de mentira nao prova nada, porque o que costuma
quebrar e justamente o que o protocolo faz, tipo o modo binario do arquivo aberto e o
comportamento do rename quando o destino ja existe.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

from comum import Placar  # noqa: E402  (comum ajusta o sys.path)

import servidor_falso  # noqa: E402
from conduit.core import sftp  # noqa: E402


def main() -> int:
    p = Placar("SFTP, o motor")

    raiz = Path(tempfile.mkdtemp(prefix="sftp-motor-"))
    (raiz / "entrada").mkdir()
    (raiz / "saida").mkdir()
    (raiz / "entrada" / "retorno.csv").write_text("id;valor\n1;10,50\n2;99,00\n", encoding="utf-8")
    (raiz / "entrada" / "config.json").write_text('{"lote": 42, "ativo": true}', encoding="utf-8")
    (raiz / ".oculto").write_text("nao aparece por padrao", encoding="utf-8")
    (raiz / "binario.bin").write_bytes(bytes(range(256)) * 8)

    porta = servidor_falso.subir(str(raiz))
    perfil = sftp.Perfil(
        id="t1", nome="teste local", host="127.0.0.1", porta=porta,
        usuario=servidor_falso.USUARIO, auth="senha",
    )
    known = raiz / "known_hosts"

    p.secao("perfil")
    p.confere("rotulo com porta fora do padrao", f":{porta}" in perfil.rotulo(), perfil.rotulo())
    p.confere("perfil completo nao reclama", perfil.problema() == "")
    p.confere("sem host reclama", sftp.Perfil(usuario="x").problema() != "")
    p.confere("sem usuario reclama", sftp.Perfil(host="x").problema() != "")
    p.confere("chave sem arquivo reclama", sftp.Perfil(host="x", usuario="y", auth="chave").problema() != "")
    p.confere("ida e volta pelo dicionario", sftp.Perfil.de_dict(perfil.para_dict()).porta == porta)

    p.secao("caminho")
    p.confere("juntar", sftp.juntar("/var/log", "app.txt") == "/var/log/app.txt")
    p.confere("juntar sobe com ..", sftp.juntar("/var/log", "..") == "/var")
    p.confere("pai", sftp.pai("/var/log/nginx") == "/var/log")
    p.confere("pai da raiz e a raiz", sftp.pai("/") == "/")
    p.confere("migalhas", sftp.migalhas("/var/log") == [("/", "/"), ("var", "/var"), ("log", "/var/log")])

    p.secao("chave do servidor")
    conexao = sftp.Conexao(perfil, known)
    try:
        conexao.abrir(senha=servidor_falso.SENHA)
        p.confere("servidor novo para a conexao", False)
    except sftp.ChaveDesconhecida as erro:
        p.confere("servidor novo para a conexao", True)
        p.confere("traz a impressao digital", erro.digital.startswith("SHA256:"), erro.digital)
        p.confere("nao grava known_hosts sem permissao", not known.exists())

    conexao = sftp.Conexao(perfil, known)
    conexao.abrir(senha=servidor_falso.SENHA, confiar=True)
    p.confere("conecta depois de confiar", conexao.aberta)
    p.confere("grava o known_hosts", known.exists())

    outra = sftp.Conexao(perfil, known)
    outra.abrir(senha=servidor_falso.SENHA)
    p.confere("segunda vez nao pergunta", outra.aberta)
    outra.fechar()

    ruim = sftp.Conexao(perfil, known)
    try:
        ruim.abrir(senha="nao-e-essa")
        p.confere("recusa senha errada", False)
    except sftp.ErroSftp as erro:
        p.confere("recusa senha errada", "recusad" in str(erro), str(erro))

    p.secao("listar")
    itens = conexao.listar("/")
    nomes = [e.nome for e in itens]
    p.confere("lista a raiz", set(nomes) >= {"entrada", "saida", "binario.bin"}, str(nomes))
    p.confere("esconde o que comeca com ponto", ".oculto" not in nomes)
    p.confere("mostra oculto quando pedido", ".oculto" in [e.nome for e in conexao.listar("/", ocultos=True)])
    p.confere("pasta antes de arquivo", itens[0].pasta and not itens[-1].pasta)

    dentro = conexao.listar("/entrada")
    p.confere("lista subpasta", {e.nome for e in dentro} == {"retorno.csv", "config.json"})
    csv = next(e for e in dentro if e.nome == "retorno.csv")
    p.confere("tamanho legivel", csv.tamanho_legivel().endswith("B"), csv.tamanho_legivel())
    p.confere("permissoes", csv.permissoes().startswith("-"), csv.permissoes())
    p.confere("data preenchida", bool(csv.quando()), csv.quando())

    try:
        conexao.listar("/nao-existe")
        p.confere("erro legivel em pasta inexistente", False)
    except sftp.ErroSftp as erro:
        p.confere("erro legivel em pasta inexistente", "nao existe" in str(erro), str(erro))

    p.secao("espiar")
    texto, cortado = conexao.espiar("/entrada/config.json")
    p.confere("le o conteudo", '"lote": 42' in texto, texto.strip())
    p.confere("nao corta arquivo pequeno", not cortado)
    try:
        conexao.espiar("/binario.bin")
        p.confere("recusa espiar binario", False)
    except sftp.ErroSftp as erro:
        p.confere("recusa espiar binario", "binario" in str(erro), str(erro))
    texto, cortado = conexao.espiar("/entrada/retorno.csv", limite=10)
    p.confere("corta no limite e avisa", cortado and len(texto) == 10, repr(texto))

    p.secao("transferir")
    local = raiz / "baixados" / "retorno.csv"
    conexao.baixar("/entrada/retorno.csv", local)
    p.confere("baixa", local.exists())
    p.confere("conteudo igual", local.read_text(encoding="utf-8") == "id;valor\n1;10,50\n2;99,00\n")
    p.confere("nao deixa .parcial pra tras", not list((raiz / "baixados").glob("*.parcial")))

    andou: list = []
    conexao.baixar("/binario.bin", raiz / "baixados" / "b.bin", progresso=lambda f, t: andou.append((f, t)))
    p.confere("chama o progresso", bool(andou), str(andou[-1]) if andou else "")
    p.confere("binario integro", (raiz / "baixados" / "b.bin").read_bytes() == (raiz / "binario.bin").read_bytes())

    origem = raiz / "baixados" / "envio.txt"
    origem.write_text("subiu daqui", encoding="utf-8")
    conexao.enviar(origem, "/saida/envio.txt")
    p.confere("envia", (raiz / "saida" / "envio.txt").read_text(encoding="utf-8") == "subiu daqui")
    try:
        conexao.enviar(raiz / "nao-existe.txt", "/saida/x.txt")
        p.confere("recusa enviar o que nao existe", False)
    except sftp.ErroSftp:
        p.confere("recusa enviar o que nao existe", True)

    p.secao("criar, renomear e apagar")
    conexao.criar_pasta("/saida/lote-2026")
    p.confere("cria pasta", (raiz / "saida" / "lote-2026").is_dir())
    conexao.renomear("/saida/envio.txt", "/saida/envio-final.txt")
    p.confere("renomeia", (raiz / "saida" / "envio-final.txt").exists())

    alvo = next(e for e in conexao.listar("/saida") if e.nome == "envio-final.txt")
    conexao.remover(alvo)
    p.confere("apaga arquivo", not (raiz / "saida" / "envio-final.txt").exists())

    pasta = next(e for e in conexao.listar("/saida") if e.nome == "lote-2026")
    conexao.remover(pasta)
    p.confere("apaga pasta vazia", not (raiz / "saida" / "lote-2026").exists())

    conexao.criar_pasta("/saida/cheia")
    (raiz / "saida" / "cheia" / "x.txt").write_text("x", encoding="utf-8")
    cheia = next(e for e in conexao.listar("/saida") if e.nome == "cheia")
    try:
        conexao.remover(cheia)
        p.confere("recusa apagar pasta cheia", False)
    except sftp.ErroSftp as erro:
        p.confere("recusa apagar pasta cheia", "vazia" in str(erro), str(erro))

    p.secao("navegacao")
    p.confere("inicio ja vem normalizado", conexao.inicio() == "/", conexao.inicio())
    p.confere("normalizar resolve ..", conexao.normalizar("/entrada/../saida") == "/saida")

    conexao.fechar()
    p.confere("fecha", not conexao.aberta)

    p.secao("chave privada")
    import paramiko
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    pasta_chaves = raiz / "chaves"
    pasta_chaves.mkdir()
    privada = ed25519.Ed25519PrivateKey.generate()
    sem_frase = pasta_chaves / "id_ed25519"
    sem_frase.write_bytes(privada.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption(),
    ))
    com_frase = pasta_chaves / "id_ed25519_frase"
    com_frase.write_bytes(privada.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
        serialization.BestAvailableEncryption(b"frase-do-teste"),
    ))

    # A lista de tipos citava paramiko.DSSKey, que saiu na versao 4: toda chave estourava
    # AttributeError antes de ser lida, e o login por chave nao funcionava pra ninguem.
    try:
        lida = sftp._carregar_chave(str(sem_frase), "")
        p.confere("le chave ed25519 sem frase", lida.get_name() == "ssh-ed25519", lida.get_name())
    except Exception as erro:  # noqa: BLE001
        p.confere("le chave ed25519 sem frase", False, f"{type(erro).__name__}: {erro}")
    try:
        sftp._carregar_chave(str(com_frase), "")
        p.confere("chave com frase pede a frase", False)
    except sftp.ErroSftp as erro:
        p.confere("chave com frase pede a frase", "frase secreta" in str(erro), str(erro))
    except Exception as erro:  # noqa: BLE001
        p.confere("chave com frase pede a frase", False, f"{type(erro).__name__}: {erro}")
    try:
        p.confere("abre com a frase certa", sftp._carregar_chave(str(com_frase), "frase-do-teste") is not None)
    except Exception as erro:  # noqa: BLE001
        p.confere("abre com a frase certa", False, f"{type(erro).__name__}: {erro}")

    servidor_falso.CHAVES_ACEITAS.append(paramiko.Ed25519Key.from_private_key_file(str(sem_frase)))
    por_chave = sftp.Conexao(
        sftp.Perfil(id="t2", nome="por chave", host="127.0.0.1", porta=porta,
                    usuario=servidor_falso.USUARIO, auth="chave", chave=str(sem_frase)),
        known,
    )
    try:
        por_chave.abrir()
        p.confere("conecta no servidor com chave privada", por_chave.aberta)
    except Exception as erro:  # noqa: BLE001
        p.confere("conecta no servidor com chave privada", False, f"{type(erro).__name__}: {erro}")
    por_chave.fechar()

    p.secao("fechar no meio de uma transferencia")
    (raiz / "grande.bin").write_bytes(os.urandom(3 * 1024 * 1024))
    lenta = sftp.Conexao(perfil, known)
    lenta.abrir(senha=servidor_falso.SENHA)
    estouros: list = []

    def baixar_devagar() -> None:
        try:
            lenta.baixar("/grande.bin", raiz / "lento" / "grande.bin",
                         progresso=lambda feito, total: time.sleep(0.05))
        except Exception as erro:  # noqa: BLE001
            estouros.append(erro)

    fio = threading.Thread(target=baixar_devagar)
    fio.start()
    time.sleep(0.4)
    comeco = time.perf_counter()
    lenta.fechar()
    gasto = time.perf_counter() - comeco
    fio.join(60)
    # O fechar pegava o mesmo cadeado da transferencia e esperava ela acabar, com a
    # janela congelada. Servidor que parou de responder congelava pra sempre.
    p.confere("fechar nao espera a transferencia acabar", gasto < 1.0, f"{gasto:.2f} s")
    p.confere("transferencia cortada vira ErroSftp",
              len(estouros) == 1 and isinstance(estouros[0], sftp.ErroSftp), repr(estouros))
    sobras = [a.name for a in (raiz / "lento").glob("*")] if (raiz / "lento").exists() else []
    p.confere("nao sobra .parcial nem arquivo pela metade", not sobras, str(sobras))

    p.secao("servidor que aceita o login e recusa o SFTP")
    porta_shell = servidor_falso.subir(str(raiz), com_sftp=False)
    so_shell = sftp.Conexao(
        sftp.Perfil(id="t3", nome="so shell", host="127.0.0.1", porta=porta_shell,
                    usuario=servidor_falso.USUARIO, auth="senha"),
        known,
    )
    try:
        so_shell.abrir(senha=servidor_falso.SENHA, confiar=True)
        p.confere("recusa do subsistema vira ErroSftp", False, "abriu")
    except sftp.ErroSftp as erro:
        p.confere("recusa do subsistema vira ErroSftp", "SFTP" in str(erro), str(erro))
    except Exception as erro:  # noqa: BLE001
        p.confere("recusa do subsistema vira ErroSftp", False, f"{type(erro).__name__}: {erro}")
    # sem fechar, o transporte seguia vivo com a thread e o socket dele, sem aba nenhuma
    p.confere("e a sessao SSH nao fica aberta", not so_shell.aberta)

    p.secao("nome de arquivo que vem do servidor")
    pasta_local = raiz / "lote"
    for nome in ("..\\..\\fora.bat", "../fora.txt", "C:\\Windows\\x.dll", "..", ".", "...", "relatorio 12:30.csv"):
        try:
            alvo = sftp.destino_local(pasta_local, nome)
            ok = alvo.parent == pasta_local and ":" not in alvo.name and alvo.name not in ("", ".", "..")
            p.confere(f"{nome!r} fica dentro da pasta escolhida", ok, str(alvo))
        except Exception as erro:  # noqa: BLE001
            p.confere(f"{nome!r} fica dentro da pasta escolhida", False, f"{type(erro).__name__}: {erro}")
    try:
        p.confere("nome de dispositivo do Windows nao vira dispositivo",
                  sftp.nome_local("NUL").lower() != "nul" and sftp.nome_local("con.txt").lower() != "con.txt",
                  f"{sftp.nome_local('NUL')} {sftp.nome_local('con.txt')}")
        # o Windows ainda le estes como dispositivo: espaco antes do ponto, o console e
        # o numero sobrescrito
        estranhos = ["nul .txt", "CONIN$", "conout$.log", "COM¹.csv"]
        reservado = getattr(os.path, "isreserved", lambda nome: nome in estranhos)
        ainda = [n for n in estranhos if reservado(sftp.nome_local(n))]
        p.confere("variantes de dispositivo tambem viram arquivo comum", not ainda, str(ainda))
        p.confere("nome comum passa igual", sftp.nome_local("retorno 2026.csv") == "retorno 2026.csv")
        # o ponto do comeco e o do arquivo oculto: tirado, o .env baixava como env
        ocultos = [sftp.nome_local(n) for n in (".env", ".htaccess")]
        p.confere("arquivo oculto do servidor mantem o ponto", ocultos == [".env", ".htaccess"], str(ocultos))
    except Exception as erro:  # noqa: BLE001
        p.confere("nome local existe", False, f"{type(erro).__name__}: {erro}")

    shutil.rmtree(raiz, ignore_errors=True)
    return p.fechar()


if __name__ == "__main__":
    sys.exit(main())
