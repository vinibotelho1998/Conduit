"""Confere o que a pessoa percebe usando: segredo que vira arquivo, aba que mostra outra
coisa, clique que nao faz nada, pergunta que nao chega.

Cada conferencia roda protegida: se uma parte do app mudar de forma, o erro vira uma
linha de falha em vez de derrubar a suite inteira. Nenhuma caixa pode esperar clique,
entao toda pergunta e trocada por uma resposta pronta antes de qualquer coisa abrir.
"""

from __future__ import annotations

import json
import socket
import sys
import tempfile
import threading
import time
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from comum import Placar, casa_limpa, girar, sem_tela  # noqa: E402

sem_tela()
casa_limpa("uso")

from PySide6.QtCore import QMimeData, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog, QMessageBox  # noqa: E402

import servidor_falso  # noqa: E402
from conduit import seed as mod_seed  # noqa: E402
from conduit.core import curl_import, engine, sftp, storage, workspaces as ws  # noqa: E402
from conduit.gui import theme  # noqa: E402


def main() -> int:
    p = Placar("Uso, o que a pessoa percebe")

    app = QApplication([])
    app.setStyle("Fusion")
    ws.ensure_root()
    mod_seed.seed()
    theme.aplicar(None, "escuro")
    app.setPalette(theme.paleta_qt())
    app.setStyleSheet(theme.folha())

    # nenhuma caixa espera clique: no offscreen ela prende o teste pra sempre
    QMessageBox.exec = lambda self: 0
    QDialog.exec = lambda self: 0
    respostas = {"pergunta": QMessageBox.StandardButton.Yes, "texto": ("", False)}
    QMessageBox.question = staticmethod(lambda *a, **k: respostas["pergunta"])
    QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QInputDialog.getText = staticmethod(lambda *a, **k: respostas["texto"])

    from conduit.gui import main_window as mod_janela
    from conduit.gui.main_window import MainWindow

    janela = MainWindow()
    janela.resize(1500, 900)
    janela.show()
    app.processEvents()

    def caso(rotulo: str, funcao) -> None:
        try:
            resultado = funcao()
        except Exception as erro:  # noqa: BLE001
            p.confere(rotulo, False, f"{type(erro).__name__}: {erro}")
            return
        ok, detalhe = resultado if isinstance(resultado, tuple) else (resultado, "")
        p.confere(rotulo, ok, str(detalhe))

    def requests_de(nos, saida=None):
        saida = saida if saida is not None else []
        for no in nos or []:
            if no.get("type") == "request":
                saida.append(no)
            requests_de(no.get("items"), saida)
        return saida

    def fechar_abas() -> None:
        for indice in reversed(range(janela.tabs.count())):
            janela.close_tab(indice)

    # ------------------------------------------------------------------------------
    p.secao("segredo de global, collection e pasta sai do arquivo versionado")
    pasta = Path(tempfile.mkdtemp(prefix="conduit-uso-cofre-"))
    arvore = {
        "globals": [{"key": "tokenGlobal", "value": "SEGREDO-GLOBAL-123", "secret": True}],
        "environments": [],
        "collections": [{
            "id": "c-seg", "type": "collection", "name": "Api",
            "variables": [{"key": "chaveCol", "value": "SEGREDO-COL-456", "secret": True},
                          {"key": "base", "value": "https://publico"}],
            "items": [{"id": "f-seg", "type": "folder", "name": "Pasta",
                       "variables": [{"key": "chavePasta", "value": "SEGREDO-PASTA-789", "secret": True}],
                       "items": []}],
        }],
    }
    storage.gravar_workspace(pasta, arvore)
    textos = " ".join(a.read_text(encoding="utf-8") for a in pasta.rglob("*.yaml"))
    caso("valor secreto nao aparece em nenhum yaml",
         lambda: (all(s not in textos for s in ("SEGREDO-GLOBAL-123", "SEGREDO-COL-456", "SEGREDO-PASTA-789")),
                  [s for s in ("GLOBAL", "COL", "PASTA") if f"SEGREDO-{s}" in textos]))
    caso("valor publico continua no arquivo", lambda: "https://publico" in textos)

    def relido():
        lida = storage.ler_workspace(pasta)
        colecao = lida["collections"][0]
        valores = {
            "g": lida["globals"][0]["value"],
            "c": colecao["variables"][0]["value"],
            "f": colecao["items"][0]["variables"][0]["value"],
        }
        return valores == {"g": "SEGREDO-GLOBAL-123", "c": "SEGREDO-COL-456", "f": "SEGREDO-PASTA-789"}, valores

    caso("e volta do cofre na leitura", relido)

    antigo = Path(tempfile.mkdtemp(prefix="conduit-uso-antigo-"))
    (antigo / "globals.yaml").write_text(
        "schemaVersion: 1\nvalues:\n- key: velho\n  value: EM-CLARO-ANTIGO\n  secret: true\n", encoding="utf-8"
    )

    def recolhe():
        from conduit.core import workspaces as modulo

        lida = storage.ler_workspace(antigo)
        modulo._recolher_segredos_soltos(antigo, lida)
        texto = (antigo / "globals.yaml").read_text(encoding="utf-8")
        de_novo = storage.ler_workspace(antigo)["globals"][0]["value"]
        return "EM-CLARO-ANTIGO" not in texto and de_novo == "EM-CLARO-ANTIGO", texto

    caso("arquivo antigo com segredo em claro abre e e recolhido pro cofre", recolhe)

    def exporta():
        from conduit.core import importer

        destino = Path(tempfile.mkdtemp(prefix="conduit-uso-export-")) / "api.postman_collection.json"
        colecao = arvore["collections"][0]
        importer.exportar({"environments": [{"id": "e", "name": "hml", "values": [
            {"key": "base", "value": "https://hml"}]}]}, [colecao], "postman", destino)
        dados = json.loads(destino.read_text(encoding="utf-8"))
        valores = {v["key"]: v["value"] for v in dados.get("variable") or []}
        ambientes = list(destino.parent.glob("*.postman_environment.json"))
        return valores.get("chaveCol") == "" and valores.get("base") == "https://publico" and len(ambientes) == 1, (
            valores, [a.name for a in ambientes])

    caso("exportar uma collection pro Postman leva ambiente e esconde o segredo dela", exporta)

    # ------------------------------------------------------------------------------
    p.secao("ambiente ativo, ordem e pasta aberta ficam fora do git")

    def estado_fora_do_git():
        pasta_estado = Path(tempfile.mkdtemp(prefix="conduit-uso-estado-"))
        storage.gravar_workspace(pasta_estado, {
            "activeEnv": "e2", "sortMode": "nome",
            "environments": [{"id": "e1", "name": "hml", "values": []}, {"id": "e2", "name": "prd", "values": []}],
            "collections": [{"id": "c1", "type": "collection", "name": "Api", "expanded": True, "items": [
                {"id": "f1", "type": "folder", "name": "Pasta", "expanded": True, "items": []},
                {"id": "f2", "type": "folder", "name": "Outra", "expanded": False, "items": []},
            ]}],
        })
        versionado = " ".join(a.read_text(encoding="utf-8") for a in pasta_estado.rglob("*.yaml"))
        fora = not any(chave in versionado for chave in ("activeEnv", "sortMode", "expanded"))
        lida = storage.ler_workspace(pasta_estado)
        pastas = {n["id"]: n["expanded"] for n in lida["collections"][0]["items"]}
        volta = (lida["activeEnv"] == "e2" and lida["sortMode"] == "nome"
                 and lida["collections"][0]["expanded"] and pastas == {"f1": True, "f2": False})
        return fora and volta, (fora, lida["activeEnv"], lida["sortMode"], pastas)

    caso("o arquivo versionado nao leva o estado de quem usa, e ele volta na leitura", estado_fora_do_git)

    def workspace_de_antes():
        pasta_antiga = Path(tempfile.mkdtemp(prefix="conduit-uso-estado-antigo-"))
        (pasta_antiga / "settings.yaml").write_text(
            "schemaVersion: 1\nactiveEnv: e1\nsortMode: metodo\n", encoding="utf-8")
        (pasta_antiga / "environments").mkdir()
        (pasta_antiga / "environments" / "hml.yaml").write_text(
            "schemaVersion: 1\nid: e1\nname: hml\nvalues: []\n", encoding="utf-8")
        (pasta_antiga / "collections" / "api").mkdir(parents=True)
        (pasta_antiga / "collections" / "api" / "_collection.yaml").write_text(
            "schemaVersion: 1\nid: c1\nseq: 0\nname: Api\nexpanded: true\n", encoding="utf-8")
        lida = storage.ler_workspace(pasta_antiga)
        certo = lida["activeEnv"] == "e1" and lida["sortMode"] == "metodo" and lida["collections"][0]["expanded"]
        storage.gravar_workspace(pasta_antiga, lida)
        de_novo = storage.ler_workspace(pasta_antiga)
        mantido = de_novo["activeEnv"] == "e1" and de_novo["collections"][0]["expanded"]
        return certo and mantido, (lida["activeEnv"], lida["sortMode"], de_novo["activeEnv"])

    caso("workspace gravado pela versao anterior abre com o ambiente e a pasta de antes", workspace_de_antes)

    # ------------------------------------------------------------------------------
    p.secao("importar curl sem aba aberta")
    fechar_abas()
    comando = "curl -X POST https://api.exemplo.com/login -H 'Content-Type: application/json' -d '{\"a\":1}'"
    from conduit.gui import curl_dialog

    colecao = janela.tree_data["collections"][0]
    janela.tree_panel.select(colecao["id"])
    antes = len(requests_de(janela.tree_data["collections"]))
    pedir_original = curl_dialog.CurlDialog.pedir
    curl_dialog.CurlDialog.pedir = staticmethod(lambda *a, **k: None)
    janela.importar_curl()
    caso("cancelar o curl nao deixa request vazio na arvore",
         lambda: (len(requests_de(janela.tree_data["collections"])) == antes,
                  len(requests_de(janela.tree_data["collections"])) - antes))
    curl_dialog.CurlDialog.pedir = staticmethod(lambda *a, **k: curl_import.importar(comando))
    janela.importar_curl()
    curl_dialog.CurlDialog.pedir = pedir_original

    def aba_do_curl():
        editor = janela.tabs.currentWidget()
        pedido = editor.request
        return (pedido.get("method") == "POST" and pedido.get("url") == "https://api.exemplo.com/login"
                and not janela._sujo(editor)), (pedido.get("method"), pedido.get("url"), janela._sujo(editor))

    caso("a aba mostra o que foi importado, sem ponto de nao salvo", aba_do_curl)
    caso("e o request novo ganha nome pelo metodo e caminho",
         lambda: (janela.tabs.tabText(janela.tabs.currentIndex()) == "POST /login",
                  janela.tabs.tabText(janela.tabs.currentIndex())))

    # ------------------------------------------------------------------------------
    p.secao("envio que nao responde tem cancelar")
    fechar_abas()
    lento = socket.socket()
    lento.bind(("127.0.0.1", 0))
    lento.listen(5)

    def responder_tarde():
        # aceita e so responde depois de o teste ja ter cancelado
        try:
            conexao, _ = lento.accept()
        except OSError:
            return
        time.sleep(2.5)
        try:
            conexao.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\nConnection: close\r\n\r\ntarde")
        finally:
            conexao.close()

    threading.Thread(target=responder_tarde, daemon=True).start()
    alvo = requests_de(janela.tree_data["collections"])[0]
    janela.open_request(alvo)
    editor = janela.editors[alvo["id"]]
    editor.url.setPlainText(f"http://127.0.0.1:{lento.getsockname()[1]}/tarde")
    total_antes = janela.history.stats()["total"] if janela.history else 0
    janela.send_current()
    app.processEvents()
    caso("enquanto envia, o botao vira Cancelar e segue clicavel",
         lambda: (editor.send_btn.text() == "Cancelar" and editor.send_btn.isEnabled(), editor.send_btn.text()))
    janela.close_tab(janela.tabs.indexOf(editor))
    janela.open_request(alvo)
    editor = janela.editors[alvo["id"]]
    caso("fechar e reabrir a aba mostra o envio em curso",
         lambda: (editor.send_btn.text() == "Cancelar", editor.send_btn.text()))
    janela.send_current()
    caso("mandar de novo avisa que ja ha envio em curso",
         lambda: ("em curso" in janela.statusBar().currentMessage(), janela.statusBar().currentMessage()))
    editor.send_btn.click()
    app.processEvents()
    caso("cancelar solta a aba", lambda: (alvo["id"] not in janela.pending and editor.send_btn.text() == "Enviar",
                                        editor.send_btn.text()))
    girar(app, 110)  # a resposta chega depois do cancelar
    lento.close()
    caso("o resultado abandonado nao vai pro historico",
         lambda: (janela.history.stats()["total"] == total_antes, janela.history.stats()["total"] - total_antes))
    janela.reverter_aba()

    # ------------------------------------------------------------------------------
    p.secao("guardar como exemplo usa o que esta na tela")
    fechar_abas()
    janela.open_request(alvo)
    real = janela.editors[alvo["id"]].no_real
    ao_vivo = {"ok": True, "status": 200, "reason": "OK", "headers": [], "body": "vivo", "elapsedMs": 1}
    janela.respostas[alvo["id"]] = (ao_vivo, {"method": "GET", "url": "https://x"}, [])
    entrada = {"id": "h1", "ts": "2026-09-22T14:03:00", "requestId": alvo["id"],
               "request": {"method": "GET", "url": "https://x", "headers": [], "body": ""},
               "response": {"ok": True, "status": 500, "reason": "Erro", "headers": [], "body": "antigo"}}
    janela.tabs.setCurrentIndex(janela.tabs.indexOf(janela.editors[alvo["id"]]))
    janela.show_history_response(entrada)
    respostas["texto"] = ("do historico", True)
    quantos = len(real.get("examples") or [])
    janela.salvar_exemplo()
    respostas["texto"] = ("", False)
    caso("o exemplo gravado e o 500 que esta na tela, e nao o 200 ao vivo",
         lambda: (len(real.get("examples") or []) == quantos + 1
                  and real["examples"][-1].get("status") == 500,
                  (real.get("examples") or [{}])[-1].get("status")))
    caso("resposta do historico ganha etiqueta",
         lambda: ("historico" in janela.response.marca.text() and not janela.response.marca.isHidden(),
                  janela.response.marca.text()))

    def exemplo_de_outro_request():
        de_outro = dict(entrada, id="h2", requestId="request-que-nao-e-esta-aba")
        janela.show_history_response(de_outro)
        antes = len(real.get("examples") or [])
        respostas["texto"] = ("nao devia gravar", True)
        janela.salvar_exemplo()
        respostas["texto"] = ("", False)
        depois = len(real.get("examples") or [])
        return depois == antes, f"{antes} -> {depois}"

    caso("execucao de outro request na tela nao vira exemplo desta aba", exemplo_de_outro_request)

    def historico_com_ambiente():
        fechar_abas()
        janela.open_environment(janela.tree_data["environments"][0]["id"])
        janela.show_history_response(entrada)
        return janela.response.isVisible()

    caso("clicar no historico com aba de ambiente na frente mostra a resposta", historico_com_ambiente)

    # ------------------------------------------------------------------------------
    p.secao("variavel nao nasce sozinha")
    fechar_abas()
    janela.open_request(alvo)
    editor = janela.editors[alvo["id"]]
    editor.url.setPlainText("https://x/{{tokn_digitado_errado}}")
    girar(app, 45)
    nomes = {v.get("key") for env in janela.tree_data.get("environments") or [] for v in env.get("values") or []}
    nomes |= {v.get("key") for v in janela.tree_data.get("globals") or []}
    caso("pausa na digitacao nao cria variavel no ambiente", lambda: "tokn_digitado_errado" not in nomes)
    caso("a faixa com o criar continua la",
         lambda: (editor.aviso.isVisible() and editor.aviso.botao.text() == "criar", editor.aviso.botao.text()))
    janela.reverter_aba()

    # ------------------------------------------------------------------------------
    p.secao("ajustes do request")
    fechar_abas()
    sujos = []
    for no in requests_de(janela.tree_data["collections"]):
        janela.open_request(no)
        if janela._sujo(janela.editors[no["id"]]):
            sujos.append(no.get("name"))
        janela.close_tab(janela.tabs.indexOf(janela.editors[no["id"]]))
    caso("nenhum request dos exemplos abre com ponto de nao salvo", lambda: (not sujos, sujos))

    janela.open_request(alvo)
    editor = janela.editors[alvo["id"]]

    def mexer_nos_ajustes():
        editor.ajuste_tls.setChecked(False)
        editor.ajuste_tempo.setValue(5)
        app.processEvents()
        return janela._sujo(editor)

    caso("mexer nos ajustes acende o ponto de nao salvo", mexer_nos_ajustes)
    caso("certificado desligado aparece na faixa",
         lambda: (editor.aviso.isVisible() and "certificado" in editor.aviso.texto.texto_cheio(), editor.aviso.texto.texto_cheio()))
    janela.salvar_aba()

    def ajustes_no_disco():
        janela._save_now()
        lido = next(n for n in requests_de(ws.read_tree(janela.workspace_id)["collections"])
                    if n["id"] == alvo["id"])
        ajustes = lido.get("settings") or {}
        return ajustes.get("verifyTls") is False and float(ajustes.get("timeout")) == 5, ajustes

    caso("salvar grava os ajustes no arquivo", ajustes_no_disco)
    if hasattr(editor, "ajuste_tls"):
        editor.ajuste_tls.setChecked(True)
        editor.ajuste_tempo.setValue(30)
        janela.salvar_aba()

    # ------------------------------------------------------------------------------
    p.secao("ambiente trocado pela barra de cima")
    fechar_abas()
    ambientes = janela.tree_data["environments"]
    janela._usar_ambiente(ambientes[0]["id"])
    janela.open_environment(ambientes[0]["id"])
    aba_env = janela.env_editors[ambientes[0]["id"]]
    janela.env_combo.setCurrentIndex(janela.env_combo.findData(ambientes[1]["id"]))
    caso("a aba do ambiente antigo deixa de dizer ativo",
         lambda: (not aba_env._ativo and aba_env.btn_ativar.isEnabled(), aba_env.marca.text()))
    caso("sem ambiente o rodape nao diz ambiente sem ambiente",
         lambda: (janela.env_combo.setCurrentIndex(0) or "sem ambiente ativo" in janela.status_right.texto_cheio(),
                  janela.status_right.texto_cheio()))
    janela.env_combo.setCurrentIndex(janela.env_combo.findData(ambientes[0]["id"]))
    caso("contagem no singular", lambda: ("1 secretas" not in janela.status_right.texto_cheio(), janela.status_right.texto_cheio()))

    def desfazer_no_ambiente():
        env = ambientes[0]
        janela.open_environment(env["id"])
        aba = janela.env_editors[env["id"]]
        antes = [v.get("key") for v in env["values"]]
        linha = env["values"][0]
        aba.tabela._remove(linha)
        sumiu = linha.get("key") not in [v.get("key") for v in env["values"]]
        oferecido = not aba.desfazer.isHidden() and aba.desfazer.botao.text() == "desfazer"
        aba.desfazer.acao.emit()
        depois = [v.get("key") for v in env["values"]]
        return sumiu and oferecido and depois == antes and aba.desfazer.isHidden(), (sumiu, oferecido, depois[:3])

    caso("apagar variavel na aba do ambiente oferece desfazer, e volta no mesmo lugar", desfazer_no_ambiente)

    # ------------------------------------------------------------------------------
    p.secao("arvore conversa com as abas")
    fechar_abas()
    janela._ir_para_lateral(0)
    janela.open_request(alvo)
    item = janela.tree_panel._item_by_id(alvo["id"])
    item.setText(0, "Nome trocado na arvore")
    app.processEvents()
    caso("renomear na arvore chega na aba",
         lambda: (janela.tabs.tabText(janela.tabs.indexOf(janela.editors[alvo["id"]])) == "Nome trocado na arvore",
                  janela.tabs.tabText(janela.tabs.indexOf(janela.editors[alvo["id"]]))))
    item.setText(0, "")
    app.processEvents()
    caso("nome vazio devolve o nome na linha", lambda: (item.text(0) == "Nome trocado na arvore", item.text(0)))

    visiveis = lambda: sum(  # noqa: E731
        1 for i in janela.tree_panel.tree.findItems("", Qt.MatchFlag.MatchContains | Qt.MatchFlag.MatchRecursive)
        if not i.isHidden()
    )
    expandidos = {n["id"]: bool(n.get("expanded")) for n in janela.tree_panel._iter_nodes() if n.get("type") != "request"}
    janela.search.setText("cep")
    filtrados = visiveis()
    janela.tree_panel.refresh()
    caso("refresh da arvore mantem o filtro da busca",
         lambda: (visiveis() == filtrados, f"{filtrados} antes, {visiveis()} depois"))
    janela.search.setText("")
    depois = {n["id"]: bool(n.get("expanded")) for n in janela.tree_panel._iter_nodes() if n.get("type") != "request"}
    caso("buscar e limpar nao muda pasta aberta no arquivo",
         lambda: (depois == expandidos, [k for k in depois if depois[k] != expandidos.get(k)]))

    def busca_com_lateral_em_ambientes():
        janela._ir_para_lateral(2)
        janela.search.setText("x")
        indice = janela.side.currentIndex()
        janela.search.setText("")
        return indice == 0, indice

    caso("digitar na busca com a lateral em Ambientes leva pra arvore", busca_com_lateral_em_ambientes)

    def busca_sem_resultado():
        janela.search.setText("zzz-nada-assim")
        dito = not janela.tree_panel.sem_achado.isHidden() and "nada encontrado" in janela.tree_panel.sem_achado.text()
        janela.search.setText("")
        some = janela.tree_panel.sem_achado.isHidden()
        return dito and some, janela.tree_panel.sem_achado.text()

    caso("busca sem resultado diz que nada bateu", busca_sem_resultado)

    # ------------------------------------------------------------------------------
    p.secao("desfazer e duplicar")
    fechar_abas()
    primeiro, segundo = requests_de(janela.tree_data["collections"])[:2]
    janela.open_request(primeiro)
    aba_viva = janela.editors[primeiro["id"]]
    aba_viva.url.setPlainText("https://edicao-que-fica.exemplo")
    app.processEvents()
    respostas["pergunta"] = QMessageBox.StandardButton.Yes
    janela._excluir_no(segundo)
    janela.undo_tree()
    caso("desfazer nao fecha a aba sem relacao",
         lambda: (primeiro["id"] in janela.editors and janela.tabs.indexOf(janela.editors[primeiro["id"]]) >= 0,
                  list(janela.editors)))
    caso("e a edicao dela continua na aba",
         lambda: (janela.editors[primeiro["id"]].request.get("url") == "https://edicao-que-fica.exemplo"
                  and janela._sujo(janela.editors[primeiro["id"]]),
                  janela.editors.get(primeiro["id"]).request.get("url") if primeiro["id"] in janela.editors else "-"))
    caso("o request excluido voltou",
         lambda: any(n.get("id") == segundo["id"] for n in janela.tree_panel._iter_nodes()))

    def pergunta_de_excluir():
        perguntas = []
        original = QMessageBox.question
        QMessageBox.question = staticmethod(
            lambda *a, **k: perguntas.append(a[2]) or QMessageBox.StandardButton.No)
        try:
            janela._excluir_no(janela.tree_data["collections"][0])
        finally:
            QMessageBox.question = original
        texto = perguntas[0] if perguntas else ""
        return ("a collection" in texto and "requests" in texto and "Ctrl+Z" in texto
                and "definitivo" not in texto), texto.replace("\n", " ")

    caso("excluir collection diz o que vai junto e que da pra desfazer", pergunta_de_excluir)

    def duplicar_com_edicao():
        editor = janela.editors[primeiro["id"]]
        janela._duplicar_aba(janela.tabs.indexOf(editor))
        copia = next(n for n in requests_de(janela.tree_data["collections"])
                     if n.get("name", "").endswith(" copia"))
        return copia.get("url") == "https://edicao-que-fica.exemplo", copia.get("url")

    caso("duplicar a aba com edicao leva a edicao pra copia", duplicar_com_edicao)
    for no in [n for n in requests_de(janela.tree_data["collections"]) if n.get("name", "").endswith(" copia")]:
        editor_copia = janela.editors.get(no["id"])
        if editor_copia is not None:
            janela.close_tab(janela.tabs.indexOf(editor_copia))
        janela.tree_panel.remove(no)
    if primeiro["id"] in janela.editors:
        janela.reverter_aba()

    def renomear_com_foco_na_url():
        from PySide6.QtWidgets import QAbstractItemView

        janela.open_request(primeiro)
        url = janela.editors[primeiro["id"]].url
        janela.tree_panel.select(primeiro["id"])
        # no offscreen a janela nao ganha foco de verdade, entao o foco e dito na mao
        foco_original = QApplication.focusWidget
        QApplication.focusWidget = staticmethod(lambda: url)
        try:
            janela.rename_selected()
        finally:
            QApplication.focusWidget = foco_original
        editando = janela.tree_panel.tree.state() == QAbstractItemView.State.EditingState
        janela.tree_panel.tree.closePersistentEditor(janela.tree_panel.tree.currentItem())
        return editando

    caso("Renomear do menu funciona com o cursor na url", renomear_com_foco_na_url)

    # ------------------------------------------------------------------------------
    p.secao("request novo")
    fechar_abas()
    janela.side.setVisible(False)
    janela.tree_panel.select(janela.tree_data["collections"][0]["id"])
    janela.new_request()
    caso("Ctrl+N com a lateral escondida mostra a lateral", janela.side.isVisible)
    caso("terminado o nome, o request novo abre na aba",
         lambda: (janela.tree_panel._fim_do_nome() or janela.tabs.count() == 1, janela.tabs.count()))
    novo = janela.current_node()
    if novo is not None:
        janela.close_tab(janela.tabs.currentIndex())
        janela.tree_panel.remove(janela.tree_panel._by_id.get(novo["id"]) or novo)

    # ------------------------------------------------------------------------------
    p.secao("variaveis de collection e pasta")
    from conduit.gui.variables_dialog import VariablesDialog

    fora = {"id": "f-fora", "type": "folder", "name": "De fora", "variables": [], "items": []}
    dentro = {"id": "f-dentro", "type": "folder", "name": "De dentro", "variables": [], "items": []}
    colecao_x = {"id": "c-x", "type": "collection", "name": "X", "variables": [], "items": []}

    def uma_aba_por_pasta():
        dialogo = VariablesDialog({"globals": [], "environments": []}, [colecao_x, fora, dentro], {}, None,
                                  "pasta", "De fora")
        abas = [dialogo.tabs.tabText(i) for i in range(dialogo.tabs.count())]
        atual = dialogo.tabs.tabText(dialogo.tabs.currentIndex())
        dialogo.deleteLater()
        return len([a for a in abas if a.startswith("Pasta")]) == 2 and atual == "Pasta De fora", (abas, atual)

    caso("pasta dentro de pasta ganha uma aba por pasta, e abre na de origem", uma_aba_por_pasta)

    def menu_da_collection():
        abertos = []
        original = mod_janela.VariablesDialog
        mod_janela.VariablesDialog = lambda *a, **k: abertos.append(a) or SimpleNamespace(exec=lambda: 0)
        try:
            janela.tree_panel.variaveis_pedidas.emit(janela.tree_data["collections"][0])
        finally:
            mod_janela.VariablesDialog = original
        return bool(abertos) and abertos[0][1][-1] is janela.tree_data["collections"][0], len(abertos)

    caso("variaveis da collection pelo botao direito, sem request aberto", menu_da_collection)

    # ------------------------------------------------------------------------------
    p.secao("gerar codigo ve o segredo da auth")

    def segredo_na_auth():
        vistos = []
        original = mod_janela.CodegenDialog
        mod_janela.CodegenDialog = lambda construir, tem, parent=None: vistos.append(tem) or SimpleNamespace(
            exec=lambda: 0)
        janela.tree_data.setdefault("globals", []).append(
            {"key": "tokenDaAuth", "value": "valor-secreto", "secret": True, "enabled": True})
        fechar_abas()
        janela.open_request(alvo)
        editor = janela.editors[alvo["id"]]
        editor.request["auth"] = {"type": "bearer", "token": "{{tokenDaAuth}}"}
        try:
            janela.open_codegen()
        finally:
            mod_janela.CodegenDialog = original
            janela.tree_data["globals"].pop()
            janela.reverter_aba()
        return vistos == [True], vistos

    caso("Bearer com variavel secreta conta como segredo", segredo_na_auth)

    # ------------------------------------------------------------------------------
    p.secao("url colada")
    fechar_abas()
    janela.open_request(alvo)
    editor = janela.editors[alvo["id"]]
    editor.url.clear()
    colado = QMimeData()
    colado.setText("https://api.exemplo.com/cep\r\n")
    editor.url.insertFromMimeData(colado)
    caso("colar com fim de linha nao deixa segunda linha", lambda: ("\n" not in editor.url.toPlainText(),
                                                                   repr(editor.url.toPlainText())))
    janela.reverter_aba()
    caso("espaco nas pontas sai da url no envio",
         lambda: (engine.prepare({"url": "  https://x/y  "}, {}).url == "https://x/y",
                  engine.prepare({"url": "  https://x/y  "}, {}).url))
    caso("localhost sem http vira http://",
         lambda: (engine.prepare({"url": "localhost:8080/api"}, {}).url == "http://localhost:8080/api",
                  engine.prepare({"url": "localhost:8080/api"}, {}).url))
    caso("url com variavel sem valor nao ganha esquema",
         lambda: engine.prepare({"url": "{{base}}/a"}, {}).url == "{{base}}/a")

    # ------------------------------------------------------------------------------
    p.secao("erro de rede em frase")
    caso("endereco que nao resolve",
         lambda: "nao achei o endereco" in engine.explicar_erro(
             "ConnectError: [Errno 11001] getaddrinfo failed", "https://nao-existe.exemplo/x"))
    caso("porta fechada",
         lambda: "nada respondendo em 127.0.0.1:9" in engine.explicar_erro(
             "ConnectError: [WinError 10061] conexao recusada", "http://127.0.0.1:9/x"))
    caso("certificado desconhecido aponta pra CA",
         lambda: "Certificados e CA" in engine.explicar_erro(
             "ConnectError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed", "https://x"))

    def erro_na_tela():
        janela.response.setVisible(True)
        janela.response.show_response(
            {"ok": False, "error": "ConnectError: [Errno 11001] getaddrinfo failed", "elapsedMs": 3},
            {"method": "GET", "url": "https://nao-existe.exemplo/x"})
        texto = janela.response.pretty.edit.toPlainText()
        return texto.startswith("nao achei") and "getaddrinfo" in texto, texto[:80]

    caso("a resposta mostra a frase e o detalhe tecnico embaixo", erro_na_tela)

    # ------------------------------------------------------------------------------
    p.secao("resposta grande")

    def grande():
        linhas = [{"id": n, "nome": f"item {n}", "valor": "x" * 20} for n in range(26000)]
        corpo = json.dumps(linhas, indent=2)
        comeco = time.perf_counter()
        janela.response.show_response(
            {"ok": True, "status": 200, "reason": "OK", "headers": [["content-type", "application/json"]],
             "body": corpo, "sizeBytes": len(corpo), "elapsedMs": 5, "url": "https://x"}, None)
        app.processEvents()
        gasto = time.perf_counter() - comeco
        return gasto < 1.5 and janela.response.faixa.isVisible(), f"{len(corpo) // 1024} KB em {gasto:.2f} s"

    caso("resposta de mais de 1 MB nao prende a janela e avisa na faixa", grande)

    def copiar_na_raw():
        janela.response.show_response(
            {"ok": True, "status": 200, "reason": "OK", "headers": [["content-type", "application/json"]],
             "body": '{"a":1,"b":[1,2]}', "sizeBytes": 17, "elapsedMs": 5, "url": "https://x"}, None)
        janela.response.tabs.setCurrentIndex(1)
        janela.response._copiar()
        copiado = QGuiApplication.clipboard().text()
        janela.response.tabs.setCurrentIndex(0)
        return copiado == '{"a":1,"b":[1,2]}', copiado

    caso("copiar na aba Raw copia o corpo como veio", copiar_na_raw)

    def texto_com_prefixo_de_binario():
        vistos = {}
        for tipo, corpo in (
            ("application/x-www-form-urlencoded", "access_token=abc&scope=repo"),
            ("application/x-amz-json-1.1", '{"TableNames": []}'),
            ("image/png", "\x89PNG"),
        ):
            janela.response.show_response(
                {"ok": True, "status": 200, "reason": "OK", "headers": [["content-type", tipo]],
                 "body": corpo, "content": corpo.encode("latin-1"), "sizeBytes": len(corpo),
                 "elapsedMs": 5, "url": "https://x"}, None)
            vistos[tipo] = janela.response.pretty.edit.toPlainText()
        return (
            "access_token=abc" in vistos["application/x-www-form-urlencoded"]
            and "TableNames" in vistos["application/x-amz-json-1.1"]
            and vistos["image/png"].startswith("resposta binaria"),
            vistos,
        )

    caso("token em form urlencoded e json da AWS aparecem como texto, e imagem nao",
         texto_com_prefixo_de_binario)

    def sem_resposta():
        janela.response.clear()
        return not janela.response.btn_copiar.isEnabled() and not janela.response.btn_exemplo.isEnabled()

    caso("sem resposta, copiar e guardar exemplo ficam apagados", sem_resposta)
    caso("sem aba aberta o painel de resposta sai",
         lambda: (fechar_abas() or not janela.response.isVisible(), janela.response.isVisible()))

    # ------------------------------------------------------------------------------
    p.secao("historico")
    from conduit.core.history import History, Query

    pasta_hist = Path(tempfile.mkdtemp(prefix="conduit-uso-hist-"))
    hist = History(pasta_hist)
    ids = [
        hist.record(request={"id": f"r{n}", "name": f"req {n}"},
                    prepared=SimpleNamespace(method="GET", url=f"https://x/{n}", headers={}, body="",
                                             secrets=[], missing=[]),
                    result={"ok": True, "status": 200, "body": f"corpo {n}"})
        for n in range(3)
    ]
    hist.delete(ids[1])
    hist.rebuild_index()
    caso("excluir do historico nao volta no Reconstruir",
         lambda: ({r["id"] for r in hist.query(Query())} == {ids[0], ids[2]}, [r["id"] for r in hist.query(Query())]))
    caso("e a linha de depois continua abrindo",
         lambda: ((hist.get(ids[2]) or {}).get("response", {}).get("body") == "corpo 2"))

    def expurgado():
        for arquivo in (pasta_hist / "history").glob("*.jsonl"):
            arquivo.unlink()
        return hist.get(ids[0]) is None and (hist.resumo(ids[0]) or {}).get("url") == "https://x/0"

    caso("execucao sem corpo ainda tem o resumo", expurgado)
    hist.close()

    def dia_na_linha():
        from conduit.gui.history_panel import quando

        hoje = date(2026, 9, 23)
        return (quando("2026-09-23T14:32:10", hoje), quando("2026-09-22T14:32:10", hoje),
                quando("2026-09-20T14:32:10", hoje)) == ("14:32:10", "ontem 14:32", "20/09 14:32")

    caso("historico mostra ontem e o dia, e nao so a hora", dia_na_linha)

    def reenviar_em_outro_ambiente():
        registro = SimpleNamespace(get=lambda _i: {"id": "e1", "env": "local", "requestId": alvo["id"],
                                                    "request": {"method": "GET", "url": "https://x"}},
                                   resumo=lambda _i: None)
        historico_real, janela.history = janela.history, registro
        janela.env_combo.setCurrentIndex(janela.env_combo.findText("publico"))
        enviados = []
        original = janela.send_current
        janela.send_current = lambda: enviados.append(1)
        try:
            janela.replay_entry("e1")
        finally:
            janela.send_current = original
            janela.history = historico_real
        return not enviados, enviados

    caso("reenviar execucao de outro ambiente pergunta antes, e cancelar nao envia", reenviar_em_outro_ambiente)

    def reenviar_expurgado():
        def resumo_de(metodo):
            return {"id": "e2", "ts": "2026-08-01T10:00:00", "request_id": "request-que-saiu",
                    "method": metodo, "url": "https://x/pagamentos", "env": "", "ok": 1, "status": 201}

        tarefas = []
        historico_real, pool_real = janela.history, janela.pool
        janela.pool = SimpleNamespace(start=tarefas.append)
        try:
            for metodo in ("POST", "GET"):
                janela.history = SimpleNamespace(get=lambda _i: None, resumo=lambda _i, m=metodo: resumo_de(m))
                janela.replay_entry("e2")
        finally:
            janela.history, janela.pool = historico_real, pool_real
            for tarefa in tarefas:
                janela._tasks.discard(tarefa)
        iniciados = [tarefa.prepared.method for tarefa in tarefas]
        return iniciados == ["GET"], iniciados

    caso("POST expurgado, sem corpo nem headers, nao e reenviado so com a url", reenviar_expurgado)

    # ------------------------------------------------------------------------------
    p.secao("exportar")

    def destino_reinicia():
        from conduit.gui.transfer_dialogs import ExportDialog

        arvore_export = {"environments": [], "collections": [
            {"id": "a", "type": "collection", "name": "A", "items": []},
            {"id": "b", "type": "collection", "name": "B", "items": []}]}
        dialogo = ExportDialog(arvore_export)
        dialogo.destino = Path(tempfile.gettempdir())
        dialogo._destino_pasta = True
        dialogo.lista.item(1).setCheckState(Qt.CheckState.Unchecked)
        zerado = dialogo.destino is None
        dialogo.deleteLater()
        return zerado

    caso("desmarcar uma collection zera o destino de pasta", destino_reinicia)

    # ------------------------------------------------------------------------------
    p.secao("curl e OAuth2")
    caso("curl -F com arquivo nao vira texto calado",
         lambda: (any("arquivo" in i for i in curl_import.importar(
             "curl https://x -F nota=@nota.pdf").ignorados), curl_import.importar("curl https://x -F nota=@nota.pdf").ignorados))

    def audiencia():
        from conduit.core import auth

        # pelo token_oauth2 inteiro, sem rede: o token guardado pra api-a nao serve pra api-b
        base = {"type": "oauth2", "tokenUrl": "https://t", "clientId": "c"}
        chave_a = auth._assinatura(base, "https://t", "c", "", "api-a")
        guardado = json.dumps({"token": "TOKEN-DA-API-A", "expira": time.time() + 3600})
        cofre = SimpleNamespace(get=lambda chave: guardado if chave == chave_a else "")
        mesmo = auth.token_oauth2(dict(base, audience="api-a"), {}, [], cofre, rede=False)[0]
        outro = auth.token_oauth2(dict(base, audience="api-b"), {}, [], cofre, rede=False)[0]
        return mesmo == "TOKEN-DA-API-A" and outro == "", (mesmo, outro)

    caso("token do OAuth2 guardado separa por audience", audiencia)

    # ------------------------------------------------------------------------------
    p.secao("tela")
    caso("botoes do Qt em portugues", lambda: botoes_em_portugues(app))
    caso("Excluir desligado nao parece ligado", lambda: "QPushButton#perigo:disabled" in theme.folha())
    caso("auth sem origem nao diz vem de nenhum",
         lambda: ("nenhum:" not in janela._texto_heranca({"id": "x", "auth": {"type": "inherit"}}),
                  janela._texto_heranca({"id": "x", "auth": {"type": "inherit"}})))
    caso("lateral nao encolhe abaixo do que cabe as abas", lambda: janela.side.minimumWidth() >= 250)

    def workspace_vazio():
        from conduit.gui.tree_panel import TreePanel

        painel = TreePanel()
        painel.load({"collections": []})
        painel.show()
        app.processEvents()
        visivel = painel.vazio.isVisible() and not painel.tree.isVisible()
        painel.deleteLater()
        return visivel

    caso("workspace sem collection mostra o que fazer", workspace_vazio)

    def rodape_nao_alarga():
        app.processEvents()
        antes = janela.minimumSizeHint().width()
        janela.statusBar().showMessage("enviando GET https://api.exemplo.com/" + "segmento/" * 30)
        app.processEvents()
        depois = janela.minimumSizeHint().width()
        janela.statusBar().clearMessage()
        return depois <= antes, f"{antes} -> {depois}"

    caso("mensagem comprida no rodape nao alarga a janela", rodape_nao_alarga)

    def faixa_nao_alarga():
        fechar_abas()
        janela.open_request(alvo)
        editor = janela.editors[alvo["id"]]
        editor.url.setPlainText("https://x/" + "".join("{{semDono%d}}/" % i for i in range(6)))
        app.processEvents()
        minimo = editor.aviso.minimumSizeHint().width()
        visivel = editor.aviso.isVisible()
        janela.reverter_aba()
        return visivel and minimo < 400, minimo

    caso("faixa com muitos nomes nao alarga o editor", faixa_nao_alarga)

    def mono_de_verdade():
        fechar_abas()
        janela.open_request(alvo)
        editor = janela.editors[alvo["id"]]
        app.processEvents()
        familias = {
            "url": editor.url.font().family(),
            "corpo": editor.body.font().family(),
            "pretty": janela.response.pretty.edit.font().family(),
        }
        return all(f and f in theme.MONO for f in familias.values()), familias

    caso("url, corpo e resposta saem em fonte de largura fixa", mono_de_verdade)

    def enviado_inteiro():
        janela.response.setVisible(True)
        janela.response.show_response(
            {"ok": True, "status": 200, "reason": "OK", "headers": [], "body": "", "elapsedMs": 1},
            {"method": "GET", "url": "https://x", "headers": {"Accept": "application/json"}, "body": ""})
        from PySide6.QtWidgets import QTableWidget

        tabelas = janela.response.enviado_box.findChildren(QTableWidget)
        if not tabelas:
            return False, "sem tabela"
        tabela = tabelas[-1]
        precisa = tabela.horizontalHeader().sizeHint().height() + tabela.rowHeight(0)
        return tabela.maximumHeight() >= precisa, f"{tabela.maximumHeight()} pra {precisa}"

    caso("aba Enviado mostra o header inteiro", enviado_inteiro)

    def curl_sem_comentario():
        from conduit.gui import highlight

        regra = highlight.CODE_RULES[0][0]
        return (not regra.match("curl https://x/cep").hasMatch()
                and regra.match("  // comentario").hasMatch()
                and regra.match("x = 1  # comentario").hasMatch())

    caso("no curl gerado a url nao vira comentario", curl_sem_comentario)

    def auth_so_do_tipo():
        from conduit.gui.auth_editor import AuthEditor

        dono = {"auth": {"type": "bearer", "token": "token-antigo"}}
        editor_auth = AuthEditor(dono)
        editor_auth.combo.setCurrentIndex(editor_auth.combo.findData("basic"))
        editor_auth.campos["username"].setPlainText("fulano")
        guardado = dict(dono["auth"])
        volta = editor_auth.campos["token"].toPlainText()
        editor_auth.deleteLater()
        return "token" not in guardado and guardado.get("username") == "fulano" and volta == "token-antigo", guardado

    caso("trocar de Bearer pra Basic nao grava o token antigo", auth_so_do_tipo)

    def falha_em_vermelho():
        from conduit.gui.history_panel import status_color

        return status_color(None, False) == theme.ERR

    caso("falha de rede no historico sai na cor de erro", falha_em_vermelho)

    def paleta_mostra_atalho():
        from conduit.gui.palette import LinhaPaleta, Palette, PaletteItem

        dialogo = Palette([PaletteItem(label="Enviar o request aberto", sub="Ctrl+Enter")], "Comando")
        altura = dialogo.lista.sizeHintForRow(0)
        certo = isinstance(dialogo.lista.itemDelegate(), LinhaPaleta) and altura >= 30
        dialogo.deleteLater()
        return certo, altura

    caso("paleta desenha o comando com o atalho", paleta_mostra_atalho)

    def fantasma_num_clique():
        from PySide6.QtWidgets import QAbstractItemView

        from conduit.gui.kvtable import KvTable

        grade = KvTable([{"key": "a", "value": "1", "enabled": True}], ("Chave", "Valor"))
        grade.show()
        app.processEvents()
        grade.table.cellClicked.emit(0, 1)
        linha_com_dado = grade.table.state() == QAbstractItemView.State.EditingState
        grade.table.cellClicked.emit(1, 1)
        fantasma = grade.table.state() == QAbstractItemView.State.EditingState
        grade.deleteLater()
        return fantasma and not linha_com_dado, (fantasma, linha_com_dado)

    caso("linha vazia da grade abre a edicao num clique so", fantasma_num_clique)

    def troca_de_tema():
        janela.registrar("linha de teste do console", "ok", 0)
        janela.open_request(alvo)
        editor = janela.editors[alvo["id"]]
        editor.method.setCurrentText("POST")
        theme.aplicar(app, "claro")
        app.processEvents()
        documento = janela.console.texto.document()
        ultimo = documento.findBlockByNumber(max(0, documento.blockCount() - 2))
        cores = {frag.charFormat().foreground().color().name() for frag in _fragmentos(ultimo)}
        metodo_claro = theme.METHOD_COLORS["POST"].lower() in editor.method.styleSheet().lower()
        console_claro = QColor(theme.OK).name() in cores
        theme.aplicar(app, "escuro")
        app.processEvents()
        janela.reverter_aba()
        return metodo_claro and console_claro, (metodo_claro, sorted(cores))

    caso("trocar pro tema claro repinta o console e o metodo", troca_de_tema)

    # ------------------------------------------------------------------------------
    p.secao("SFTP")
    pasta_sftp = Path(tempfile.mkdtemp(prefix="conduit-uso-sftp-"))
    (pasta_sftp / "backup").mkdir()
    (pasta_sftp / "grande.zip").write_bytes(b"z" * 10)
    (pasta_sftp / "remessa.rem").write_text("antiga", encoding="utf-8")
    porta = servidor_falso.subir(str(pasta_sftp))
    import conduit.gui.sftp_dialog as dialogos

    dialogos.ChaveDialog.confia = staticmethod(lambda erro, parent=None: True)
    sftp.gravar_perfis(janela.tree_data, [sftp.Perfil(
        id="uso1", nome="parceiro", host="127.0.0.1", porta=porta,
        usuario=servidor_falso.USUARIO, auth="senha",
    )])
    janela.sftp_panel.refresh()
    cofre = ws.cofre(janela.workspace_id)
    cofre.set(sftp.CHAVE_SENHA.format(id="uso1"), "senha-antiga-que-mudou")
    perguntas = []

    def pergunta_senha(perfil, frase=False, parent=None):
        perguntas.append(frase)
        return servidor_falso.SENHA, True

    dialogos.SenhaDialog.pedir = staticmethod(pergunta_senha)
    janela.sftp_abrir("uso1")
    girar(app, 80)
    caso("senha guardada recusada pergunta de novo", lambda: (perguntas == [False], perguntas))
    caso("e a senha nova conecta e vai pro cofre",
         lambda: ("uso1" in janela.sftp_abas
                  and ws.cofre(janela.workspace_id).get(sftp.CHAVE_SENHA.format(id="uso1")) == servidor_falso.SENHA,
                  list(janela.sftp_abas)))
    if "uso1" not in janela.sftp_abas:
        # sem a pergunta de novo, conecta com a senha certa pra seguir com o resto
        ws.cofre(janela.workspace_id).set(sftp.CHAVE_SENHA.format(id="uso1"), servidor_falso.SENHA)
        janela.sftp_abrir("uso1")
        girar(app, 80)
    navegador = janela.sftp_abas.get("uso1")
    if navegador is not None:
        girar(app, 20)

        def navegar_ocupado():
            antes = navegador.caminho
            navegador._marcar_ocupado(True, "baixando grande.zip")
            navegador.ir_para("/backup")
            mudou = navegador.caminho != antes
            navegador._marcar_ocupado(False)
            return not mudou, navegador.caminho

        caso("navegar durante a transferencia nao troca a pasta por dentro", navegar_ocupado)

        def trilha_sem_barra_dupla():
            navegador.ir_para("/backup")
            girar(app, 30)
            textos = []
            for indice in range(navegador.trilha.count()):
                peca = navegador.trilha.itemAt(indice).widget()
                if peca is not None and peca is not navegador.campo_caminho:
                    textos.append(peca.text())
            navegador.ir_para("/")
            girar(app, 30)
            return textos == ["/", "backup"], textos

        caso("trilha do SFTP nao repete a barra depois da raiz", trilha_sem_barra_dupla)

        def listagem_troca_de_tema():
            theme.aplicar(app, "claro")
            app.processEvents()
            cor = navegador.tabela.item(0, 1).foreground().color().name()
            esperado = QColor(theme.DIM).name()
            theme.aplicar(app, "escuro")
            app.processEvents()
            return cor == esperado, f"{cor} e devia ser {esperado}"

        caso("listagem do SFTP acompanha a troca de tema", listagem_troca_de_tema)
        caso("resumo do SFTP no singular",
             lambda: ("1 pastas" not in navegador.resumo.text(), navegador.resumo.text()))

        def renomear_fica_na_pasta():
            navegador.caminho = "/backup"  # a tela ainda mostra a raiz
            linha = next(i for i in range(navegador.tabela.rowCount())
                         if navegador.tabela.item(i, 0).text() == "grande.zip")
            navegador.tabela.selectRow(linha)
            respostas["texto"] = ("grande-v2.zip", True)
            navegador.renomear()
            girar(app, 30)
            respostas["texto"] = ("", False)
            navegador.caminho = "/"
            return (pasta_sftp / "grande-v2.zip").exists() and not (pasta_sftp / "backup" / "grande-v2.zip").exists()

        caso("renomear troca o nome sem mover pra outra pasta", renomear_fica_na_pasta)

        def enviar_repetido():
            from PySide6.QtWidgets import QFileDialog

            navegador.recarregar()
            girar(app, 30)
            local = Path(tempfile.mkdtemp(prefix="conduit-uso-envio-")) / "remessa.rem"
            local.write_text("nova", encoding="utf-8")
            original = QFileDialog.getOpenFileNames
            QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([str(local)], ""))
            perguntado = []
            navegador._perguntar_repetidos = lambda *a: perguntado.append(a) or None
            try:
                navegador.enviar()
                girar(app, 30)
            finally:
                QFileDialog.getOpenFileNames = original
            return bool(perguntado) and (pasta_sftp / "remessa.rem").read_text(encoding="utf-8") == "antiga"

        caso("enviar arquivo de mesmo nome pergunta, e cancelar nao sobrescreve", enviar_repetido)

        def sessao_caiu():
            navegador.conexao.fechar()
            navegador.recarregar()
            girar(app, 30)
            return (navegador.estado.text() == "desconectado" and not navegador.btn_reconectar.isHidden()
                    and "uso1" not in janela.sftp_panel.ligados), navegador.estado.text()

        caso("sessao que caiu aparece como desconectada, com reconectar", sessao_caiu)
        caso("com a aba SFTP na frente, Ctrl+L abre o campo de caminho",
             lambda: (janela.tabs.setCurrentWidget(navegador) or janela.focus_url()
                      or not navegador.campo_caminho.isHidden()))
        janela.sftp_desconectar("uso1")

    def esquecer_senha():
        dialogo = dialogos.PerfilDialog(janela._sftp_perfil("uso1"), janela, guardada=True)
        dialogo.guardar.setChecked(False)
        dialogo._aceitar()
        return dialogo.senha_nova == "", repr(dialogo.senha_nova)

    caso("desmarcar Guardar esquece a senha guardada", esquecer_senha)

    for aberto in list(janela.sftp_abas.values()):
        aberto.encerrar()

    # ------------------------------------------------------------------------------
    p.secao("workspace fora da lista")

    def nome_repetido():
        ws.create_workspace("Nome que repete")
        try:
            ws.create_workspace("Nome que repete")
        except ValueError as erro:
            return "id" not in str(erro) and "nome" in str(erro), str(erro)
        return False, "criou dois"

    caso("nome repetido e explicado sem falar de id", nome_repetido)

    def escolher(texto):
        return lambda self: next((b for b in self.buttons() if b.text() == texto), None)

    def recriar_fora_da_lista():
        from conduit.gui.workspaces_dialog import criar_workspace

        antigo = ws.create_workspace("Volta ou nao")
        (Path(antigo["path"]) / "marca.txt").write_text("x", encoding="utf-8")
        ws.delete_workspace(antigo["id"], apagar_arquivos=False)
        original = QMessageBox.clickedButton
        QMessageBox.clickedButton = escolher("Criar outro vazio")
        try:
            vazio = criar_workspace(janela, "Volta ou nao")
            QMessageBox.clickedButton = escolher("Trazer de volta")
            trazido = criar_workspace(janela, "Volta ou nao")
        finally:
            QMessageBox.clickedButton = original
        return (vazio is not None and vazio["id"] != antigo["id"]
                and not (Path(vazio["path"]) / "marca.txt").exists()
                and trazido is not None and trazido["id"] == antigo["id"]
                and (Path(trazido["path"]) / "marca.txt").exists()), (vazio and vazio["id"], trazido and trazido["id"])

    caso("nome de workspace fora da lista pergunta: trazer de volta ou criar outro vazio", recriar_fora_da_lista)

    def exemplos_dispensados():
        ws.write_preferences(exemplosDispensados=True)
        ws.delete_workspace(mod_seed.EXAMPLES_ID, apagar_arquivos=False)
        try:
            mod_seed.seed()
            voltou = any(w["id"] == mod_seed.EXAMPLES_ID for w in ws.list_workspaces()["workspaces"])
        finally:
            ws.write_preferences(exemplosDispensados=False)
            mod_seed.ensure_examples()
        return not voltou

    caso("exemplos tirado da lista nao volta sozinho na abertura seguinte", exemplos_dispensados)
    return p.fechar()


def _fragmentos(bloco):
    iterador = bloco.begin()
    while not iterador.atEnd():
        fragmento = iterador.fragment()
        if fragmento.isValid():
            yield fragmento
        iterador += 1


def botoes_em_portugues(app) -> tuple:
    from PySide6.QtWidgets import QDialogButtonBox

    from conduit.gui.app import instalar_traducao

    instalar_traducao(app)
    caixa = QDialogButtonBox(QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.Cancel)
    textos = [b.text().replace("&", "") for b in caixa.buttons()]
    caixa.deleteLater()
    return "Sim" in textos and "Cancelar" in textos, textos


if __name__ == "__main__":
    sys.exit(main())
