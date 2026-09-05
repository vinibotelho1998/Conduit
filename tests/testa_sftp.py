"""Exercita dbxwire/core/sftp.py contra um servidor SFTP de verdade, local.

Servidor de mentira mas protocolo de verdade: e paramiko atendendo numa porta livre da
propria maquina. Testar SFTP com dublê de mentira nao prova nada, porque o que costuma
quebrar e justamente o que o protocolo faz, tipo o modo binario do arquivo aberto e o
comportamento do rename quando o destino ja existe.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from comum import Placar  # noqa: E402  (comum ajusta o sys.path)

import servidor_falso  # noqa: E402
from dbxwire.core import sftp  # noqa: E402


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

    shutil.rmtree(raiz, ignore_errors=True)
    return p.fechar()


if __name__ == "__main__":
    sys.exit(main())
