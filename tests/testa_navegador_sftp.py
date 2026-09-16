"""Sobe a janela, conecta no servidor de teste e navega pela interface de verdade.

Aqui nao ha dublê: a janela e a janela, a conexao e uma sessao SSH real numa porta local
e os arquivos existem no disco. A unica coisa trocada e a resposta da caixa que pergunta
se voce confia na chave do servidor, que nenhum teste pode clicar.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from comum import Placar, casa_limpa, girar, sem_tela  # noqa: E402

sem_tela()
casa_limpa("navegador")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import servidor_falso  # noqa: E402
from conduit.core import sftp, workspaces as ws  # noqa: E402
from conduit.gui import theme  # noqa: E402
from conduit.seed import seed  # noqa: E402


def main() -> int:
    p = Placar("SFTP, a interface")

    raiz = Path(tempfile.mkdtemp(prefix="sftp-tela-"))
    (raiz / "entrada").mkdir()
    (raiz / "entrada" / "lote.csv").write_text("a;b\n1;2\n", encoding="utf-8")
    (raiz / "leiame.txt").write_text("primeira linha\nsegunda linha\n", encoding="utf-8")
    porta = servidor_falso.subir(str(raiz))

    app = QApplication([])
    app.setStyle("Fusion")
    ws.ensure_root()
    seed()
    theme.aplicar(None, "escuro")
    app.setPalette(theme.paleta_qt())
    app.setStyleSheet(theme.folha())

    from conduit.gui.main_window import MainWindow

    janela = MainWindow()
    janela.resize(1500, 900)
    janela.show()

    p.secao("cadastro")
    p.confere("aba SFTP na lateral", janela.side.tabText(4) == "SFTP", janela.side.tabText(4))
    sftp.gravar_perfis(janela.tree_data, [sftp.Perfil(
        id="gui1", nome="cofre do parceiro", host="127.0.0.1", porta=porta,
        usuario=servidor_falso.USUARIO, auth="senha",
    )])
    janela.sftp_panel.refresh()
    p.confere("perfil aparece na lista", janela.sftp_panel.lista.count() == 1)

    janela._save_now()
    perfis = sftp.listar_perfis(ws.read_tree(janela.workspace_id))
    p.confere("gravou no settings.yaml", len(perfis) == 1 and perfis[0].host == "127.0.0.1")

    p.secao("segredo no cofre, contrato no arquivo")
    cofre = ws.cofre(janela.workspace_id)
    cofre.set(sftp.CHAVE_SENHA.format(id="gui1"), servidor_falso.SENHA)
    yaml = (Path(ws.get_workspace(janela.workspace_id)["path"]) / "settings.yaml").read_text(encoding="utf-8")
    p.confere("senha fora do arquivo versionado", servidor_falso.SENHA not in yaml)
    p.confere("host dentro do arquivo versionado", "127.0.0.1" in yaml)
    p.confere("cofre devolve a senha", cofre.get(sftp.CHAVE_SENHA.format(id="gui1")) == servidor_falso.SENHA)

    p.secao("conectar")
    import conduit.gui.sftp_dialog as dialogos

    perguntas: list = []

    def confia_sim(erro, parent=None):
        perguntas.append(erro)
        return True

    dialogos.ChaveDialog.confia = staticmethod(confia_sim)

    janela.sftp_abrir("gui1")
    girar(app)
    p.confere("perguntou sobre a chave", len(perguntas) == 1)
    p.confere("mostrou a impressao digital", bool(perguntas) and perguntas[0].digital.startswith("SHA256:"))
    p.confere("abriu a aba", "gui1" in janela.sftp_abas)

    navegador = janela.sftp_abas.get("gui1")
    p.confere("aba na area principal", navegador is not None and janela.tabs.indexOf(navegador) >= 0)
    p.confere("aba marcada como sftp", navegador is not None and navegador.property("aba_tipo") == "sftp")
    p.confere("lateral marca conectado", "gui1" in janela.sftp_panel.ligados)
    girar(app)

    p.secao("listagem")
    nomes = [navegador.tabela.item(i, 0).text() for i in range(navegador.tabela.rowCount())]
    p.confere("listou a raiz", set(nomes) >= {"entrada", "leiame.txt"}, str(nomes))
    p.confere("pasta primeiro", nomes and nomes[0] == "entrada", str(nomes))
    p.confere("coluna de permissoes preenchida", bool(navegador.tabela.item(0, 3).text()))
    p.confere("resumo conta o que tem", "pastas" in navegador.resumo.text(), navegador.resumo.text())

    p.secao("navegar")
    navegador.ir_para("/entrada")
    girar(app)
    dentro = [navegador.tabela.item(i, 0).text() for i in range(navegador.tabela.rowCount())]
    p.confere("entrou na pasta", dentro == ["lote.csv"], str(dentro))
    navegador.subir()
    girar(app)
    p.confere("voltou pra raiz", navegador.caminho == "/", navegador.caminho)
    navegador.ir_para("/nao-existe")
    girar(app)
    p.confere("pasta invalida esvazia a tabela", navegador.tabela.rowCount() == 0)
    p.confere("e explica no rodape", "nao existe" in navegador.resumo.text(), navegador.resumo.text())
    navegador.ir_para("/")
    girar(app)

    p.secao("previa")
    alvo = next(
        navegador.tabela.item(i, 0).data(Qt.ItemDataRole.UserRole)
        for i in range(navegador.tabela.rowCount())
        if navegador.tabela.item(i, 0).text() == "leiame.txt"
    )
    navegador.espiar(alvo)
    girar(app)
    p.confere("mostra o conteudo", "segunda linha" in navegador.espiada.toPlainText())
    p.confere("painel abre", not navegador.caixa_espiada.isHidden() and navegador.divisor.sizes()[1] > 0)
    p.confere("avisa que e so leitura", "so leitura" in navegador.espiada_nome.text())
    navegador.fechar_espiada()
    app.processEvents()
    p.confere("fecha sem deixar caixa vazia", navegador.caixa_espiada.isHidden())

    p.secao("mexer no servidor")
    navegador._rodar(navegador.conexao.criar_pasta, "/nova-pela-tela",
                     ao_pronto=lambda _: navegador.recarregar())
    girar(app)
    p.confere("pasta criada de verdade", (raiz / "nova-pela-tela").is_dir())
    nomes = [navegador.tabela.item(i, 0).text() for i in range(navegador.tabela.rowCount())]
    p.confere("tabela recarregou sozinha", "nova-pela-tela" in nomes, str(nomes))

    p.secao("tema com a aba aberta")
    antes = navegador.estado.styleSheet()
    theme.aplicar(app, "claro")
    girar(app, 5)
    p.confere("estado repintou", navegador.estado.styleSheet() != antes, navegador.estado.styleSheet())
    theme.aplicar(app, "escuro")

    p.secao("desconectar")
    janela.sftp_desconectar("gui1")
    girar(app, 10)
    p.confere("aba fechou", "gui1" not in janela.sftp_abas)
    p.confere("lateral desmarcou", "gui1" not in janela.sftp_panel.ligados)

    janela.sftp_abrir("gui1")
    girar(app)
    p.confere("reconecta", "gui1" in janela.sftp_abas)
    p.confere("nao pergunta a chave de novo", len(perguntas) == 1, str(len(perguntas)))

    for aberto in list(janela.sftp_abas.values()):
        aberto.encerrar()
    shutil.rmtree(raiz, ignore_errors=True)
    return p.fechar()


if __name__ == "__main__":
    sys.exit(main())
