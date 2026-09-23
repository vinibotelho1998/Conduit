"""Sobe a janela de verdade e confere o que so aparece com ela montada.

O foco e a classe de defeito que ja mordeu este app mais de uma vez: cor resolvida cedo
demais e presa pra sempre. Trocar de tema e checar que nada ficou na paleta anterior e
o unico jeito honesto de garantir isso, porque no olho a diferenca so aparece no tema
que voce nao estava usando na hora de programar.
"""

from __future__ import annotations

import colorsys
import inspect
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

from comum import Placar, casa_limpa, sem_tela  # noqa: E402

sem_tela()
casa_limpa("interface")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from conduit import recursos, seed as mod_seed  # noqa: E402
from conduit.core import codegen, curl_import, examples, sftp, workspaces as ws  # noqa: E402
from conduit.gui import theme, tokens  # noqa: E402


def saturacao(cor: str) -> float:
    r, g, b = tokens._hex_para_rgb(cor)
    return colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)[1]


def eh_neutro(cor: str) -> bool:
    """Cinza de verdade: quase sem saturacao, entao o olho nao le matiz nenhuma.

    E o que sustenta a paleta preto e cinza. O cromo do app inteiro precisa passar
    aqui, pra que qualquer mancha de cor na tela queira dizer alguma coisa.
    """
    return saturacao(cor) <= 0.10


def main() -> int:
    p = Placar("Interface, tema e nucleo")

    app = QApplication([])
    app.setStyle("Fusion")
    ws.ensure_root()
    mod_seed.seed()
    theme.aplicar(None, "escuro")
    app.setPalette(theme.paleta_qt())
    app.setStyleSheet(theme.folha())

    from conduit.gui.main_window import MainWindow

    janela = MainWindow()
    janela.resize(1500, 900)
    janela.show()

    p.secao("paleta")
    # A estrutura e neutra nos dois temas: superficie, borda e texto sem matiz nenhuma.
    # Marca, selecao e foco ficam de fora de proposito, sao a camada do acento.
    for nome, paleta in (("escuro", tokens.ESCURO), ("claro", tokens.CLARO)):
        for papel in ("fundo", "superficie", "superficie_alta", "elevado", "borda",
                      "borda_forte", "texto", "texto_medio", "texto_fraco", "texto_apagado"):
            p.confere(
                f"{papel} do {nome} e neutro",
                eh_neutro(paleta[papel]),
                f"{paleta[papel]}  saturacao {saturacao(paleta[papel]):.2f}",
            )
    # E o acento existe: sem ele a tela vira preto e branco e nada puxa o olho.
    for nome, paleta in (("escuro", tokens.ESCURO), ("claro", tokens.CLARO)):
        p.confere(
            f"marca do {nome} tem cor",
            not eh_neutro(paleta["marca"]),
            f"{paleta['marca']}  saturacao {saturacao(paleta['marca']):.2f}",
        )
    metodos = list(tokens.METODOS_ESCURO.items()) + list(tokens.METODOS_CLARO.items())
    marcas = {tokens.ESCURO["marca"], tokens.CLARO["marca"]}
    p.confere("nenhum metodo usa a cor da marca", not marcas & {c for _, c in metodos})
    # metodo e leitura de relance: dois metodos com a mesma cor derrubam o propósito
    for origem, mapa in (("escuro", tokens.METODOS_ESCURO), ("claro", tokens.METODOS_CLARO)):
        p.confere(f"sete cores distintas de metodo no {origem}", len(set(mapa.values())) == len(mapa))

    p.secao("contraste WCAG")
    ruins = []
    for paleta, cores in ((tokens.ESCURO, tokens.CODIGO_ESCURO), (tokens.CLARO, tokens.CODIGO_CLARO)):
        for papel in ("texto", "texto_medio", "texto_fraco", "marca", "ok", "aviso", "erro", "info"):
            if tokens.contraste(paleta[papel], paleta["superficie"]) < 4.5:
                ruins.append(f"{papel}@{paleta['nome']}")
        for papel, cor in cores.items():
            if papel != "achado" and tokens.contraste(cor, paleta["superficie_alta"]) < 4.5:
                ruins.append(f"codigo.{papel}@{paleta['nome']}")
        for metodo, cor in (tokens.METODOS_ESCURO if not paleta["claro"] else tokens.METODOS_CLARO).items():
            if tokens.contraste(cor, paleta["superficie"]) < 4.5:
                ruins.append(f"metodo.{metodo}@{paleta['nome']}")
    p.confere("todo token de informacao passa de 4.5", not ruins, str(ruins))
    p.confere(
        "tinta do botao cheio le sobre a marca",
        min(tokens.contraste(pal["marca_tinta"], pal["marca"]) for pal in (tokens.ESCURO, tokens.CLARO)) >= 4.5,
    )

    p.secao("editor de request")
    alvo = next(n for n in janela.tree_panel._iter_nodes()
                if n.get("type") == "request" and "CEP" in (n.get("name") or ""))
    janela.open_request(alvo)
    editor = janela.editors[alvo["id"]]
    p.confere("aba abriu", janela.tabs.count() == 1)
    p.confere("botao em portugues", editor.send_btn.text() == "Enviar", editor.send_btn.text())
    editor.set_sending(True)
    p.confere("estado de envio em portugues", editor.send_btn.text() == "Enviando")
    editor.set_sending(False)

    editor.url.setPlainText("https://x/{{nao_existe_em_lugar_nenhum}}")
    app.processEvents()
    p.confere("faixa avisa variavel sem dono", editor.aviso.isVisible())
    p.confere("faixa na cor de erro", tokens.ESCURO["erro"].lower() in editor.aviso.styleSheet().lower())

    p.secao("barra do request")
    editor.url.setPlainText("https://exemplo.com/{{cep}}")
    app.processEvents()
    p.confere("metodo e url num quadro so", editor.method.parent() is editor.grupo_url
              and editor.url.parent() is editor.grupo_url)
    p.confere("botao de copiar visivel", editor.copy_btn.isVisible())
    p.confere("botao de codigo visivel", editor.code_btn.isVisible())
    p.confere("os dois tem icone", not editor.copy_btn.icon().isNull()
              and not editor.code_btn.icon().isNull())
    p.confere("copiar abre as outras saidas",
              editor.copy_btn.menu() is not None
              and len([a for a in editor.copy_btn.menu().actions() if not a.isSeparator()]) == 4)

    from PySide6.QtGui import QGuiApplication  # noqa: PLC0415

    QGuiApplication.clipboard().setText("")
    editor.copy_btn.click()
    copiado = QGuiApplication.clipboard().text()
    p.confere("clicar poe o curl na area de transferencia", copiado.startswith("curl"),
              copiado[:48])
    segredos = [i.value for i in janela.variables_for(editor.request).values()
                if i.secret and i.value]
    p.confere("segredo nao vai em claro no clique",
              all(v not in copiado for v in segredos), f"{len(segredos)} no escopo")
    p.confere("o botao avisa que copiou", editor.copy_btn.text() == "Copiado")
    editor._timer_copiado.stop()
    editor._desmarcar_copiado()
    p.confere("e volta ao normal sozinho", editor.copy_btn.text() == "Copiar")

    editor.url.setFocus()
    app.processEvents()
    p.confere("o quadro inteiro acende com o foco na url",
              editor.grupo_url.property("foco") is True)
    editor.method.setFocus()
    app.processEvents()
    p.confere("continua aceso com o foco no metodo",
              editor.grupo_url.property("foco") is True)

    esquerda = Qt.AlignmentFlag.AlignLeft
    p.confere("cabecalho da grade fica em cima da coluna",
              int(editor.params.table.horizontalHeader().defaultAlignment()) & int(esquerda))
    p.confere("corpo mostra numero de linha", editor.body.largura_regua() > 0)

    p.secao("painel de resposta")
    resposta = {"ok": True, "status": 404, "reason": "Not Found",
                "headers": [["content-type", "application/json"]],
                "body": '{"erro":"nao achei"}', "sizeBytes": 20, "elapsedMs": 91, "url": "https://x/y"}
    enviado = {"method": "GET", "url": "https://x/y", "headers": {}, "body": ""}
    janela.response.show_response(resposta, enviado)
    p.confere("pilula visivel", janela.response.pill.isVisible())
    p.confere("pilula na cor de 4xx", tokens.ESCURO["aviso"].lower() in janela.response.pill.styleSheet().lower())

    p.secao("troca de tema nao deixa nada pra tras")
    vigiados = {
        "faixa do editor": editor.aviso,
        "pilula de status": janela.response.pill,
        "mensagem do rodape": janela.rodape.mensagem,
        "metricas da resposta": janela.response.metricas,
        "botao do console": janela.btn_console,
        "lista de ambientes": janela.env_panel.lista,
        "lista de servidores": janela.sftp_panel.lista,
    }
    antes = {nome: w.styleSheet() for nome, w in vigiados.items()}
    theme.aplicar(app, "claro")
    app.processEvents()
    presos = [nome for nome, w in vigiados.items() if w.styleSheet() == antes[nome]]
    p.confere("todo mundo repintou", not presos, str(presos))
    p.confere("pilula virou 4xx do claro", tokens.CLARO["aviso"].lower() in janela.response.pill.styleSheet().lower())
    p.confere("registro de folhas vivas nao vazou", len(theme._folhas) < 400, str(len(theme._folhas)))
    # A barra da resposta nao escreve folha nenhuma: ela usa o #silencioso do tema. O que
    # sobra pra conferir e o icone, que e desenho pronto com a cor dentro e por isso
    # precisa ser refeito na troca, senao ele fica na paleta anterior pra sempre.
    barra_resposta = (janela.response.btn_busca, janela.response.btn_curl,
                      janela.response.btn_copiar, janela.response.btn_exemplo)
    p.confere("barra da resposta usa o botao do tema",
              all(b.objectName() == "silencioso" and not b.styleSheet() for b in barra_resposta))
    chaves = [b.icon().cacheKey() for b in barra_resposta]
    theme.aplicar(app, "escuro")
    p.confere("icone da barra foi redesenhado",
              all(b.icon().cacheKey() != k for b, k in zip(barra_resposta, chaves)))
    p.confere("volta pro escuro", tokens.ESCURO["erro"].lower() in editor.aviso.styleSheet().lower())

    p.secao("exemplo de resposta")
    ex = examples.montar("404 salvo", resposta, enviado, [])
    p.confere("grava sizeBytes", ex["sizeBytes"] == 20, str(ex.get("sizeBytes")))
    p.confere("devolve sizeBytes", examples.para_resposta(ex)[0]["sizeBytes"] == 20)
    p.confere("resumo mostra o tamanho", "20 B" in examples.resumo(ex), examples.resumo(ex))
    antigo = {k: v for k, v in ex.items() if k != "sizeBytes"}
    antigo["size"] = 77
    p.confere("le exemplo antigo com a chave size", examples.para_resposta(antigo)[0]["sizeBytes"] == 77)

    segredo = [("token", "abc-123-secreto")]
    com_segredo = examples.montar("com token", dict(resposta, body='{"t":"abc-123-secreto"}'),
                                  dict(enviado, headers={"Authorization": "Bearer abc-123-secreto"}), segredo)
    inteiro = str(com_segredo)
    p.confere("segredo nao vai pro exemplo", "abc-123-secreto" not in inteiro)
    p.confere("segredo volta a ser {{nome}}", "{{token}}" in inteiro)

    p.secao("codigo gerado")
    go = codegen.generate("go", "GET", "https://x/y", {"Accept": "application/json"}, None)
    p.confere("Go sem import morto", '"strings"' not in go)
    p.confere("Go com corpo importa strings", '"strings"' in codegen.generate("go", "POST", "https://x", {}, '{"a":1}'))
    ps = codegen.generate("powershell", "GET", "https://x/it's", {"X-A": "as'pa"}, None)
    p.confere("PowerShell escapa aspa", "''" in ps, ps.splitlines()[-1])
    p.confere("C# importa System", "using System;" in codegen.generate("csharp", "GET", "https://x", {}, None))
    for linguagem, _ in codegen.LANGUAGES:
        saida = codegen.generate(linguagem, "POST", "https://x/y", {"A": "b"}, '{"c":1}')
        if not p.confere(f"{linguagem} gera algo util", len(saida) > 40 and "nao suportada" not in saida):
            break

    p.secao("curl")
    dados = curl_import.importar(
        "curl -X POST https://api/x -H 'Content-Type: application/json' -d '{\"a\":1}'"
    )
    p.confere("entende o comando", dados.erro is None and dados.method == "POST", str(dados.erro))
    p.confere("pega o corpo como json", dados.body["mode"] == "json")
    p.confere("texto que nao e curl recusa", curl_import.importar("select 1").erro is not None)

    p.secao("seletor de workspace")
    p.confere("chip tem nome sem enfeite", janela.ws_button.text() and "  " not in janela.ws_button.text(),
              repr(janela.ws_button.text()))
    p.confere("chip tem o ponto da cor", not janela.ws_button.icon().isNull())
    p.confere("chip nao escreve a propria folha", janela.ws_button.styleSheet() == "")
    p.confere("dica explica o que e", "Workspace aberto" in janela.ws_button.toolTip())
    p.confere("teclado nao nasce no seletor", not janela.ws_button.hasFocus())

    from conduit.gui.workspaces_dialog import NOMES_DE_COR, WorkspacesDialog

    p.confere("um nome por cor cadastrada", len(NOMES_DE_COR) == len(ws.COLORS))
    dialogo = WorkspacesDialog(janela)
    dialogo.show()          # foco so se resolve com a janela na tela
    app.processEvents()
    p.confere("lista os workspaces em cartao", dialogo.lista.count() == len(dialogo.entradas))
    p.confere("cartao tem widget proprio", dialogo.lista.itemWidget(dialogo.lista.item(0)) is not None)
    p.confere("abre com o aberto selecionado", dialogo.selecionado() is not None)
    p.confere("nao oferece abrir o que ja esta aberto", not dialogo.btn_usar.isEnabled())
    p.confere("nao deixa excluir o unico", not dialogo.btn_excluir.isEnabled() or len(dialogo.entradas) > 1)
    p.confere("teclado nasce na lista", dialogo.lista.hasFocus())
    dialogo.close()
    dialogo.deleteLater()

    p.secao("workspace e recursos")
    sftp.gravar_perfis(janela.tree_data, [sftp.Perfil(id="p1", nome="X", host="h", usuario="u", porta=2222)])
    janela._save_now()
    lidos = sftp.listar_perfis(ws.read_tree(janela.workspace_id))
    p.confere("perfil sftp sobrevive ao disco", len(lidos) == 1 and lidos[0].porta == 2222)
    p.confere("CHANGELOG localizado", recursos.arquivo("CHANGELOG.md") is not None)
    p.confere("LICENSE localizado", recursos.arquivo("LICENSE") is not None)
    p.confere("recurso ausente devolve None", recursos.arquivo("nao-existe.md") is None)

    fonte = inspect.getsource(mod_seed)
    sujeira = [t for t in ("mule" "soft", "vinicius") if t in fonte]
    p.confere("dado de exemplo sem nome proprio nem terceiro", not sujeira, str(sujeira))

    p.secao("fonte de largura fixa")
    # Pedir uma familia so, "Cascadia Code", entregava Tahoma nas maquinas sem ela, e
    # a url, o corpo e a tabela de variaveis ficavam em fonte proporcional.
    # Aqui se confere a intencao da fonte e nao a familia que sai: offscreen nao tem
    # as fontes do sistema, e o resultado mudaria de maquina pra maquina.
    from PySide6.QtGui import QFont

    from conduit.gui.request_editor import mono

    f = mono(9)
    esperadas = [n.strip() for n in tokens.FAMILIA_MONO.split(",")]
    p.confere("mono pede a cadeia inteira, e nao uma familia so", f.families() == esperadas,
              str(f.families()))
    p.confere("mono pede largura fixa", f.fixedPitch())
    p.confere("e a dica de estilo e monoespacada",
              f.styleHint() == QFont.StyleHint.Monospace)

    p.secao("excluir pelo menu da arvore")
    # Signal(dict) fazia o PySide entregar uma copia do node no slot, e o find_parent
    # compara por identidade: o excluir do menu nao achava o pai e nao apagava nada.
    # O teste vai pelo sinal de proposito, que e o caminho onde isso quebrava.
    def requests_de(nos, saida=None):
        saida = saida if saida is not None else []
        for no in nos or []:
            if no.get("type") == "request":
                saida.append(no)
            requests_de(no.get("items"), saida)
        return saida

    vitima = requests_de(janela.tree_data.get("collections"))[0]
    vitima_id = vitima.get("id")
    original = QMessageBox.question
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    try:
        janela.tree_panel.exclusao_pedida.emit(vitima)
    finally:
        QMessageBox.question = original
    janela._save_now()
    p.confere(
        "excluir pelo sinal do menu tira da arvore",
        vitima_id not in {n.get("id") for n in requests_de(janela.tree_data.get("collections"))},
    )
    p.confere(
        "e tira do disco tambem",
        vitima_id not in {
            n.get("id") for n in requests_de(ws.read_tree(janela.workspace_id).get("collections"))
        },
    )

    p.secao("edicao por fora aparece na tela")
    import yaml

    raiz = Path(ws.get_workspace(janela.workspace_id)["path"])
    janela._save_now()

    alvo = None
    for arquivo in raiz.rglob("*.yaml"):
        dados = yaml.safe_load(arquivo.read_text(encoding="utf-8")) or {}
        if dados.get("method") and dados.get("id"):
            alvo, conteudo = arquivo, dados
            break
    p.confere("achou um request no disco pra mexer", alvo is not None)

    def no_por_id(nos, alvo_id):
        for no in nos or []:
            if no.get("id") == alvo_id:
                return no
            achado = no_por_id(no.get("items"), alvo_id)
            if achado is not None:
                return achado
        return None

    if alvo is not None:
        no = no_por_id(janela.tree_data.get("collections"), conteudo["id"])
        p.confere("request achado na arvore em memoria", no is not None)
        janela.open_request(no)
        editor = janela.editors.get(conteudo["id"])
        p.confere("aba aberta pro request", editor is not None)

        # controle negativo: sem ninguem mexer no disco, checar nao pode recarregar nada
        antes = dict(janela._assinatura)
        janela._checar_disco()
        p.confere("disco parado nao recarrega", janela._assinatura == antes)

        conteudo["url"] = "https://mexido-por-fora.exemplo/teste"
        alvo.write_text(yaml.safe_dump(conteudo, allow_unicode=True, sort_keys=False), encoding="utf-8")
        janela._checar_disco()

        p.confere(
            "url editada por fora chegou na aba",
            editor is not None and editor.url.toPlainText() == "https://mexido-por-fora.exemplo/teste",
            editor.url.toPlainText() if editor else "",
        )
        p.confere("recarregar nao marca o workspace como alterado", not janela.save_timer.isActive())

        # rascunho escrito por fora chega como alteracao pendente, dando ao usuario a
        # chance de recusar. Editar o yaml da collection chegaria ja como salvo.
        import json as _json

        pasta = raiz / ".conduit"
        pasta.mkdir(exist_ok=True)
        (pasta / "rascunhos.json").write_text(
            _json.dumps({conteudo["id"]: {"url": "https://veio-como-rascunho.exemplo"}}),
            encoding="utf-8",
        )
        janela._checar_disco()
        p.confere(
            "rascunho de fora chegou na aba",
            editor.url.toPlainText() == "https://veio-como-rascunho.exemplo",
            editor.url.toPlainText(),
        )
        p.confere("e a aba ficou marcada como nao salva", janela._sujo(editor))

        # aba com alteracao sua nao pode ser atropelada pelo que veio do disco
        editor.url.setPlainText("https://minha-edicao-nao-salva.exemplo")
        conteudo["url"] = "https://segunda-mexida-por-fora.exemplo"
        alvo.write_text(yaml.safe_dump(conteudo, allow_unicode=True, sort_keys=False), encoding="utf-8")
        janela._checar_disco()
        p.confere(
            "aba com alteracao sua nao e atropelada",
            editor.url.toPlainText() == "https://minha-edicao-nao-salva.exemplo",
            editor.url.toPlainText(),
        )

    from conduit.core import engine, importer, scopes, storage, vars as resolvedor
    from conduit.core.vault import Vault

    p.secao("arquivo ilegivel no workspace nao some")
    solto = Path(tempfile.mkdtemp(prefix="conduit-storage-"))
    storage.gravar_workspace(solto, {
        "activeEnv": "e1",
        "environments": [{"id": "e1", "name": "local", "values": [{"key": "porta", "value": "1"}]}],
        "collections": [{
            "id": "c1", "type": "collection", "name": "Api", "variables": [{"key": "base", "value": "x"}],
            "items": [
                {"id": "r1", "type": "request", "name": "Um", "method": "GET", "url": "https://a"},
                {"id": "r2", "type": "request", "name": "Dois", "method": "GET", "url": "https://b"},
                {"id": "f1", "type": "folder", "name": "Pasta A", "items": []},
                {"id": "f2", "type": "folder", "name": "Pasta B", "items": []},
            ],
        }],
    })
    colecao_dir = solto / "collections" / "api"
    dois = colecao_dir / "dois.yaml"
    quebrado = "id: r2\nname: Dois\n  url: https://b\nmethod: [GET\n"
    dois.write_text(quebrado, encoding="utf-8")
    lida = storage.ler_workspace(solto)
    nomes = [n["name"] for n in lida["collections"][0]["items"] if n["type"] == "request"]
    p.confere("request com erro de digitacao sai so da tela", nomes == ["Um"], str(nomes))
    storage.gravar_workspace(solto, lida)
    # o salvar seguinte apagava o arquivo, sem copia nenhuma
    p.confere("e fica no disco esperando o conserto",
              dois.exists() and dois.read_text(encoding="utf-8") == quebrado)

    colecao_yaml = colecao_dir / "_collection.yaml"
    conflito_git = "<<<<<<< HEAD\nname: Api\nvariables:\n- key: base\n  value: x\n=======\nname: Api\n>>>>>>> outra\n"
    colecao_yaml.write_text(conflito_git, encoding="utf-8")
    resumo = storage.gravar_workspace(solto, storage.ler_workspace(solto))
    copias = list((solto / ".conduit" / "conflitos").rglob("_collection.yaml")) if (solto / ".conduit").exists() else []
    p.confere("collection ilegivel ganha copia antes de ser regravada",
              any(a.read_text(encoding="utf-8") == conflito_git for a in copias), f"{len(copias)} copias")
    p.confere("e o salvar avisa", any("_collection.yaml" in c for c in resumo["conflitos"]), str(resumo["conflitos"]))

    um = colecao_dir / "um.yaml"
    original_um = um.read_bytes()
    for rotulo, bruto in (
        ("arquivo fora do UTF-8 nao derruba a leitura", "id: r1\nname: Caf\xe9\n".encode("cp1252")),
        ("lista no lugar do mapa nao derruba a leitura", b"- uma lista\n- no lugar do mapa\n"),
    ):
        um.write_bytes(bruto)
        try:
            storage.ler_workspace(solto)
            p.confere(rotulo, True)
        except Exception as erro:  # noqa: BLE001
            p.confere(rotulo, False, f"{type(erro).__name__}: {erro}")
    um.write_bytes(original_um)
    um.write_text(um.read_text(encoding="utf-8").replace("seq: 0", "seq: primeiro"), encoding="utf-8")
    try:
        storage.ler_workspace(solto)
        p.confere("seq escrito como texto nao derruba a ordenacao", True)
    except Exception as erro:  # noqa: BLE001
        p.confere("seq escrito como texto nao derruba a ordenacao", False, f"{type(erro).__name__}: {erro}")
    um.write_bytes(original_um)

    ambiente = solto / "environments" / "local.yaml"
    ambiente.write_text(
        "id: e1\nname: local\nvalues:\n- key: porta\n  value: 8080\n- key: ligado\n  value: true\n",
        encoding="utf-8",
    )
    try:
        mapa = scopes.as_plain(scopes.build(storage.ler_workspace(solto)))
        final = resolvedor.resolve("http://h:{{porta}}/?x={{ligado}}", mapa).text
        p.confere("numero e booleano escritos na mao viram texto", final == "http://h:8080/?x=true", final)
    except Exception as erro:  # noqa: BLE001
        p.confere("numero e booleano escritos na mao viram texto", False, f"{type(erro).__name__}: {erro}")

    class CofreQuebrado:
        def get(self, chave, padrao=""):
            return padrao

        def set_muitos(self, pares):
            raise OSError("disco cheio")

    ambiente.write_text(
        "id: e1\nname: local\nvalues:\n- key: token\n  value: segredo-antigo-em-claro\n  secret: true\n",
        encoding="utf-8",
    )
    resumo = storage.gravar_workspace(
        solto, storage.ler_workspace(solto, cofre=CofreQuebrado()), cofre=CofreQuebrado()
    )
    # regravar o ambiente com o valor em branco apagava o unico lugar onde ele existia
    p.confere("cofre que falha nao apaga o segredo do arquivo",
              "segredo-antigo-em-claro" in ambiente.read_text(encoding="utf-8"))
    p.confere("e o salvar conta que o cofre falhou", bool(resumo.get("erro_cofre")))

    lida = storage.ler_workspace(solto)
    marca = storage.assinatura(solto)
    time.sleep(0.05)
    for pasta in ("pasta-a", "pasta-b"):
        arquivo = colecao_dir / pasta / "_folder.yaml"
        arquivo.write_text(arquivo.read_text(encoding="utf-8") + f"# mexido por fora em {pasta}\n", encoding="utf-8")
    storage.gravar_workspace(solto, lida, marca)
    guardados = [a.read_text(encoding="utf-8") for a in (solto / ".conduit" / "conflitos").rglob("_folder.yaml")]
    p.confere("dois _folder.yaml mexidos por fora ganham duas copias",
              any("pasta-a" in t for t in guardados) and any("pasta-b" in t for t in guardados),
              f"{len(guardados)} copias")

    p.secao("cofre")
    raiz_cofre = Path(tempfile.mkdtemp(prefix="conduit-cofre-"))
    antigo = Vault(raiz_cofre)
    antigo.get("qualquer")  # le agora e guarda em memoria, como um dialogo aberto ha tempo
    Vault(raiz_cofre).set("gravado-por-outra-tela", "valor-1")
    antigo.set("gravado-depois", "valor-2")
    novo = Vault(raiz_cofre)
    p.confere("instancia antiga nao apaga o que outra gravou",
              novo.get("gravado-por-outra-tela") == "valor-1" and novo.get("gravado-depois") == "valor-2")

    # O envio grava o token do OAuth2 de uma thread do pool enquanto a interface salva.
    # Sem cadeado, uma gravacao lia o cofre, a outra gravava por cima, e um segredo sumia.
    raiz_cofre_threads = Path(tempfile.mkdtemp(prefix="conduit-cofre-threads-"))
    falhas_threads: list = []

    def gravar_varias(prefixo: str) -> None:
        for numero in range(8):
            try:
                Vault(raiz_cofre_threads).set(f"{prefixo}-{numero}", "valor")
            except Exception as erro:  # noqa: BLE001
                falhas_threads.append(f"{type(erro).__name__}: {erro}")

    fios = [threading.Thread(target=gravar_varias, args=(f"t{n}",)) for n in range(4)]
    for fio in fios:
        fio.start()
    for fio in fios:
        fio.join(60)
    guardadas = Vault(raiz_cofre_threads).chaves()
    p.confere("quatro threads gravando no cofre nao perdem segredo",
              len(guardadas) == 32 and not falhas_threads,
              f"{len(guardadas)} de 32, {falhas_threads[:2]}")

    lixo = '{"schemaVersion": 1, "provider": "dpapi", "wrappedKey": "AAAA", "nonce": "AAAA", "ciphertext": "AAAA"}'
    (raiz_cofre / ".secrets" / "vault.dbx").write_text(lixo, encoding="utf-8")
    quebrado = Vault(raiz_cofre)
    p.confere("cofre que nao abre avisa", bool(quebrado.erro), str(quebrado.erro))
    quebrado.set("depois-do-erro", "x")
    copias = list((raiz_cofre / ".secrets").glob("vault.dbx.ilegivel-*"))
    p.confere("cofre que nao abre fica de lado, e nao sobrescrito",
              len(copias) == 1 and copias[0].read_text(encoding="utf-8") == lixo, str(copias))
    p.confere("e o cofre novo abre", Vault(raiz_cofre).get("depois-do-erro") == "x")

    p.secao("certificado cliente")
    from conduit.core import certs

    pasta_temp = Path(tempfile.mkdtemp(prefix="conduit-pem-"))
    pem_ruim = Path(tempfile.mkdtemp(prefix="conduit-cert-")) / "so-chave.pem"
    pem_ruim.write_bytes(b"-----BEGIN PRIVATE KEY-----\nMIIBsegredo\n-----END PRIVATE KEY-----\n")
    anterior = tempfile.tempdir
    tempfile.tempdir = str(pasta_temp)
    try:
        certs.contexto_ssl(certs.Certificado(host="x", arquivo=str(pem_ruim)), "")
        p.confere("pem sem certificado falha", False)
    except Exception:  # noqa: BLE001
        p.confere("pem sem certificado falha", True)
    finally:
        tempfile.tempdir = anterior
    sobras = [a.name for a in pasta_temp.glob("conduit-*.pem")]
    p.confere("e nao deixa copia da chave na pasta temporaria", not sobras, str(sobras))

    p.secao("cookie e redirect")
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    pedidos_token: list = []

    class Local(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def _responder(self, codigo, corpo=b"", extras=()):
            self.send_response(codigo)
            for chave, valor in extras:
                self.send_header(chave, valor)
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def do_GET(self):  # noqa: N802
            if self.path == "/vai-pra-outro-host":
                destino = f"http://localhost:{self.server.server_address[1]}/eco-cookie"
                self._responder(302, extras=[("Location", destino)])
            elif self.path == "/eco-cookie":
                self._responder(200, (self.headers.get("Cookie") or "").encode(),
                                [("Set-Cookie", "do_outro_host=1; Path=/")])
            elif self.path == "/eco-auth":
                self._responder(200, (self.headers.get("Authorization") or "").encode())
            else:
                self._responder(404)

        def do_POST(self):  # noqa: N802
            pedidos_token.append(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            if self.path == "/token-vida-texto":
                corpo = json.dumps({"access_token": "tok-vida", "expires_in": "3600.0"}).encode()
            elif self.path == "/token-vida-infinita":
                corpo = json.dumps({"access_token": "tok-vida", "expires_in": "1e999"}).encode()
            elif self.path == "/token-lista":
                corpo = b'["nao", "e", "objeto"]'
            else:
                time.sleep(0.8)
                corpo = json.dumps({"access_token": "tok-do-teste-123", "expires_in": 3600}).encode()
            self._responder(200, corpo, [("Content-Type", "application/json")])

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), Local)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    base_http = f"http://127.0.0.1:{servidor.server_address[1]}"

    volta = engine.send(engine.Prepared(
        method="GET", url=f"{base_http}/vai-pra-outro-host", cookies={"sessao": "do-primeiro-host"}
    ))
    p.confere("cookie guardado nao segue o redirect pra outro host",
              volta.get("ok") and "sessao" not in (volta.get("body") or ""),
              repr(volta.get("body") or volta.get("error")))
    p.confere("cookie do outro host nao vai pro jar do primeiro",
              "do_outro_host" not in (volta.get("cookies") or {}), str(volta.get("cookies")))
    mesmo = engine.send(engine.Prepared(
        method="GET", url=f"{base_http}/eco-cookie", cookies={"sessao": "do-primeiro-host"}
    ))
    p.confere("no mesmo host o cookie continua indo", "sessao=do-primeiro-host" in (mesmo.get("body") or ""))

    p.secao("OAuth2 sem travar a janela")
    auth_oauth = {"type": "oauth2", "tokenUrl": f"{base_http}/token", "clientId": "cliente-teste"}
    try:
        comeco = time.perf_counter()
        preparado = engine.prepare(
            {"id": "r-oauth", "method": "GET", "url": f"{base_http}/eco-auth", "auth": auth_oauth},
            {}, rede=False,
        )
        gasto = time.perf_counter() - comeco
        p.confere("preparar nao vai ao provedor de token", not pedidos_token and gasto < 0.5,
                  f"{len(pedidos_token)} pedidos, {gasto:.2f} s")
        p.confere("o token fica marcado como pendente",
                  "{{oauth2_token}}" in preparado.headers.get("Authorization", ""), str(preparado.headers))
        resposta_oauth = engine.send(preparado)
        p.confere("o envio pede o token e manda",
                  resposta_oauth.get("body") == "Bearer tok-do-teste-123",
                  repr(resposta_oauth.get("body") or resposta_oauth.get("error")))
        p.confere("e o token entra no ledger do historico",
                  any(v == "tok-do-teste-123" for _, v in preparado.secrets))
    except Exception as erro:  # noqa: BLE001
        p.confere("preparar sem ir a rede", False, f"{type(erro).__name__}: {erro}")

    pedidos_token.clear()
    colecao_oauth = {
        "id": "col-oauth", "type": "collection", "name": "Com OAuth", "expanded": True, "auth": auth_oauth,
        "items": [
            {"id": "req-proprio", "type": "request", "name": "proprio", "method": "GET",
             "url": f"{base_http}/eco-auth", "auth": dict(auth_oauth)},
            {"id": "req-herda", "type": "request", "name": "herda", "method": "GET",
             "url": f"{base_http}/eco-auth", "auth": {"type": "inherit"}},
        ],
    }
    janela.tree_data["collections"].append(colecao_oauth)
    QGuiApplication.clipboard().setText("")
    janela.copiar_curl(colecao_oauth["items"][0])
    copiado = QGuiApplication.clipboard().text()
    # o copiar pedia um token novo ao provedor com a janela parada, e o token vivo ia em
    # claro na copia que promete trocar segredo por {{nome}}
    p.confere("copiar como curl nao pede token ao provedor", not pedidos_token, f"{len(pedidos_token)} pedidos")
    p.confere("e o token sai como {{oauth2_token}}",
              "{{oauth2_token}}" in copiado and "tok-do-teste" not in copiado, copiado[:160])
    QGuiApplication.clipboard().setText("")
    janela.copiar_curl(colecao_oauth["items"][1])
    copiado = QGuiApplication.clipboard().text()
    p.confere("auth herdada da collection entra no curl copiado", "Authorization" in copiado, copiado[:160])
    janela.tree_data["collections"].remove(colecao_oauth)

    from conduit.core import auth as mod_auth_token

    for caminho_token, rotulo in (("/token-vida-texto", "expires_in em texto"),
                                  ("/token-vida-infinita", "expires_in infinito"),
                                  ("/token-lista", "resposta que nao e objeto")):
        try:
            token, erro_token, _ = mod_auth_token.token_oauth2(
                {"tokenUrl": f"{base_http}{caminho_token}", "clientId": "c"}, {}, [], None
            )
            # "3600.0" estourava ValueError e lista estourava AttributeError, no envio
            p.confere(f"provedor com {rotulo} nao derruba o envio", bool(token) or bool(erro_token),
                      repr(token or erro_token))
        except Exception as erro:  # noqa: BLE001
            p.confere(f"provedor com {rotulo} nao derruba o envio", False, f"{type(erro).__name__}: {erro}")
    servidor.shutdown()

    p.secao("codigo gerado com corpo de verdade")
    import ast

    corpo_json = '{\n  "msg": "ele disse \\"oi\\"\\nfim",\n  "pasta": "C:\\\\temp"\n}'
    fetch = codegen.generate("javascript-fetch", "POST", "https://x/y", {}, corpo_json)
    p.confere("fetch manda o JSON como texto, e nao [object Object]", "JSON.stringify(" in fetch)
    for corpo in (corpo_json, 'linha 1\nlinha com aspa no fim"'):
        literal = codegen._py_literal(corpo)
        try:
            p.confere("Python recebe o corpo sem trocar escape", ast.literal_eval(literal) == corpo, literal[:50])
        except (SyntaxError, ValueError) as erro:
            p.confere("Python recebe o corpo sem trocar escape", False, f"{type(erro).__name__}: {erro}")

    # url com aspa ou barra invertida ia crua entre aspas duplas e fechava a string antes
    url_estranha = 'https://x/busca?q="a\\b"'
    gerado = codegen.generate("python-httpx", "GET", url_estranha, {}, None)
    try:
        chamada = ast.parse(gerado)
        literais = [n.value for n in ast.walk(chamada) if isinstance(n, ast.Constant) and n.value == url_estranha]
        p.confere("url com aspa sai inteira no Python gerado", bool(literais))
    except SyntaxError as erro:
        p.confere("url com aspa sai inteira no Python gerado", False, f"SyntaxError: {erro}")

    p.secao("historico troca o segredo inteiro")
    trocado = resolvedor.redact("abc123xyz e abc", [("senha", "abc"), ("token", "abc123xyz")])
    p.confere("segredo mais longo troca primeiro", trocado == "{{token}} e {{senha}}", trocado)

    p.secao("importar e exportar")
    pasta_io = Path(tempfile.mkdtemp(prefix="conduit-io-"))
    com_bom = pasta_io / "com-bom.postman_collection.json"
    com_bom.write_text(json.dumps({
        "info": {"name": "Com BOM",
                 "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
        "item": [],
    }), encoding="utf-8-sig")
    detectados = importer.detectar(com_bom)
    p.confere("json com BOM do Bloco de Notas e reconhecido",
              bool(detectados) and detectados[0][0] == "Postman", str(detectados))
    torto = pasta_io / "torto.insomnia.json"
    torto.write_text(json.dumps({
        "_type": "export", "__export_format": 4, "resources": [{"_type": "request", "name": "sem id"}],
    }), encoding="utf-8")
    try:
        p.confere("arquivo torto vira erro legivel", bool(importer.importar(torto).erro))
    except Exception as erro:  # noqa: BLE001
        p.confere("arquivo torto vira erro legivel", False, f"{type(erro).__name__}: {erro}")
    parecidas = [
        {"id": "a", "type": "collection", "name": "Pagamentos v1", "items": []},
        {"id": "b", "type": "collection", "name": "Pagamentos (v1)", "items": []},
    ]
    saida = importer.exportar({"environments": []}, parecidas, "postman", pasta_io / "exportado")
    p.confere("collections de nome parecido viram dois arquivos",
              len(list(Path(saida).glob("*.postman_collection.json"))) == 2)
    for colecao, nome in zip(parecidas, ("um", "outro")):
        colecao["items"] = [{"id": f"r-{nome}", "type": "request", "name": "Consulta", "method": "GET",
                             "url": f"https://{nome}.exemplo"}]
    saida = importer.exportar({"environments": []}, parecidas, "bruno", pasta_io / "bruno")
    urls = {a.read_text(encoding="utf-8").split("url: ")[1].split("\n")[0] for a in Path(saida).rglob("consulta.bru")}
    p.confere("no Bruno tambem, cada collection na sua pasta", urls == {"https://um.exemplo", "https://outro.exemplo"},
              str(urls))

    from conduit.gui.history_panel import to_curl

    reproduzido = to_curl({"request": {"method": "POST", "url": "https://x/y", "headers": [["A", "b"]],
                                       "body": '{"casa": "$HOME", "cmd": "`ls`"}'}})
    p.confere("curl do historico nao deixa o terminal expandir o corpo",
              """'{"casa": "$HOME", "cmd": "`ls`"}'""" in reproduzido, reproduzido.splitlines()[-2])

    p.secao("excluir workspace com arquivo aberto")
    from conduit.core.history import History

    alvo_ws = ws.create_workspace("Para apagar no teste")
    preso = History(alvo_ws["path"])
    preso.stats()  # o indice fica aberto, como fica com o workspace na tela
    try:
        ws.delete_workspace(alvo_ws["id"], apagar_arquivos=True)
        p.confere("pasta presa nao e movida pela metade", False, "moveu com arquivo aberto")
    except OSError:
        p.confere("pasta presa nao e movida pela metade", Path(alvo_ws["path"], "collections").is_dir())
    p.confere("e o workspace continua na lista",
              any(e["id"] == alvo_ws["id"] for e in ws.list_workspaces()["workspaces"]))
    preso.close()
    try:
        resultado = ws.delete_workspace(alvo_ws["id"], apagar_arquivos=True)
        p.confere("solto, vai inteiro pra lixeira",
                  bool(resultado["lixeira"]) and Path(resultado["lixeira"], "collections").is_dir())
    except Exception as erro:  # noqa: BLE001
        p.confere("solto, vai inteiro pra lixeira", False, f"{type(erro).__name__}: {erro}")

    p.secao("indice do historico")
    from types import SimpleNamespace

    from conduit.core.history import Query

    pasta_hist = Path(tempfile.mkdtemp(prefix="conduit-hist-"))
    hist = History(pasta_hist)
    for n in range(2):
        hist.record(
            request={"id": f"r{n}", "name": f"req {n}"},
            prepared=SimpleNamespace(method="GET", url=f"https://x/{n}", headers={}, body="",
                                     secrets=[], missing=[]),
            result={"ok": True, "status": 200},
        )
    hist.close()
    (pasta_hist / "history" / "index.db").unlink()
    de_novo = History(pasta_hist)
    p.confere("indice apagado volta sozinho a partir do log", len(de_novo.query(Query())) == 2)
    de_novo.close()
    (pasta_hist / "history" / "index.db").write_bytes(b"isto nao e um banco sqlite " * 100)
    try:
        estragado = History(pasta_hist)
        p.confere("indice corrompido nao impede de abrir o workspace", len(estragado.query(Query())) == 2)
        estragado.close()
    except Exception as erro:  # noqa: BLE001
        p.confere("indice corrompido nao impede de abrir o workspace", False, f"{type(erro).__name__}: {erro}")

    p.secao("workspace tirado da lista volta com o que tinha")
    fora = ws.create_workspace("Tirado e trazido")
    arvore_fora = ws.read_tree(fora["id"])
    arvore_fora["collections"] = [{"id": "c-fora", "type": "collection", "name": "Minha API", "items": [
        {"id": "r-fora", "type": "request", "name": "Consulta", "method": "GET", "url": "https://x"}]}]
    arvore_fora["globals"] = [{"key": "base", "value": "https://x"}]
    ws.write_tree(fora["id"], arvore_fora)
    ws.delete_workspace(fora["id"], apagar_arquivos=False)
    ws.create_workspace("Tirado e trazido")
    # criar de novo com o mesmo nome gravava a arvore vazia por cima da pasta que a tela
    # de excluir prometeu deixar intacta
    de_volta = ws.read_tree(fora["id"])
    p.confere("criar de novo com o mesmo nome adota a pasta",
              [c["name"] for c in de_volta["collections"]] == ["Minha API"] and bool(de_volta["globals"]),
              str([c["name"] for c in de_volta["collections"]]))

    p.secao("aba e exemplo")
    dono, outro = requests_de(janela.tree_data.get("collections"))[:2]
    janela.open_request(dono)
    aba = janela.editors[dono["id"]]
    docs_salvo = dono.get("docs") or ""
    aba.docs.setPlainText(docs_salvo + " rascunho que vai ser descartado")
    app.processEvents()
    original_pergunta = QMessageBox.question
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    try:
        janela.reverter_aba()
    finally:
        QMessageBox.question = original_pergunta
    p.confere("reverter volta o Docs tambem", aba.docs.toPlainText() == docs_salvo, aba.docs.toPlainText()[:60])

    exemplo = examples.montar("guardado no dono", resposta, enviado, [])
    dono.setdefault("examples", []).append(exemplo)
    janela.tree_panel.refresh()
    janela.open_request(dono)
    janela.open_request(outro)  # a aba da frente passa a ser a de outro request
    involucro = janela.tree_panel._by_id.get(exemplo["id"])
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    try:
        janela.tree_panel.exemplo_exclusao_pedida.emit(involucro)
    finally:
        QMessageBox.question = original_pergunta
    p.confere("excluir exemplo pela arvore tira do dono, com outra aba na frente",
              exemplo["id"] not in {e.get("id") for e in dono.get("examples") or []})

    exemplo = examples.montar("vai junto na copia", resposta, enviado, [])
    dono.setdefault("examples", []).append(exemplo)
    janela.tree_panel.duplicate(dono)
    copia = next(
        n for n in requests_de(janela.tree_data.get("collections"))
        if n.get("name") == f"{dono.get('name')} copia"
    )
    p.confere("duplicar da id novo ao exemplo", copia["examples"][-1]["id"] != exemplo["id"])

    p.secao("workspace aberto que sai do registro")
    janela._save_now()
    guardado_id = janela.workspace_id
    janela.workspace_id = "saiu-do-registro"
    try:
        janela._checar_disco()
        p.confere("checar o disco nao estoura", True)
    except Exception as erro:  # noqa: BLE001
        p.confere("checar o disco nao estoura", False, f"{type(erro).__name__}: {erro}")
    finally:
        janela.workspace_id = guardado_id

    # daqui pra baixo nenhuma caixa pode ficar esperando clique: no offscreen ela trava
    original_aviso = QMessageBox.warning
    QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)

    p.secao("envio que estoura nao prende a aba")
    from conduit.gui import main_window as mod_janela

    envio_original = mod_janela.engine.send

    def envio_quebrado(_preparado):
        raise RuntimeError("estouro de teste")

    mod_janela.engine.send = envio_quebrado
    entregues: list = []
    try:
        tarefa = mod_janela.SendTask(engine.Prepared(url="https://x"), {"id": "n"})
        tarefa.signals.done.connect(lambda resultado, _no: entregues.append(resultado))
        tarefa.run()
        app.processEvents()
        p.confere("sinal sai com o erro, e a aba sai de Enviando",
                  len(entregues) == 1 and "estouro de teste" in (entregues[0].get("error") or ""),
                  str(entregues))
    except Exception as erro:  # noqa: BLE001
        p.confere("sinal sai com o erro, e a aba sai de Enviando", False, f"{type(erro).__name__}: {erro}")
    finally:
        mod_janela.engine.send = envio_original

    p.secao("rascunho de fora que nao e mapa")
    rascunhos_de_fora = raiz / ".conduit" / "rascunhos.json"
    rascunhos_de_fora.write_text("[1, 2]", encoding="utf-8")
    try:
        janela._checar_disco()
        p.confere("lista no rascunhos.json nao derruba o timer do disco", True)
    except Exception as erro:  # noqa: BLE001
        p.confere("lista no rascunhos.json nao derruba o timer do disco", False, f"{type(erro).__name__}: {erro}")
    rascunhos_de_fora.unlink(missing_ok=True)
    janela.rascunhos = {}

    p.secao("texto do servidor nao vira HTML")
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QLabel, QTextBrowser

    from conduit.gui.history_panel import HistoryDetail

    # Uma imagem local grande: carregada, ela estica o rotulo; e o mesmo caminho que um
    # file://maquina/pasta percorreria, so que sem sair da maquina
    isca = Path(tempfile.mkdtemp(prefix="conduit-isca-")) / "isca.png"
    quadro = QImage(300, 300, QImage.Format.Format_RGB32)
    quadro.fill(QColor("red"))
    quadro.save(str(isca))
    tag = f"<img src='{QUrl.fromLocalFile(str(isca)).toString()}'>"

    janela.response.show_response(
        {"ok": True, "status": 200, "reason": f"OK {tag}",
         "headers": [["content-type", "text/html"], ["x-eco", tag]],
         "body": f"<p>pagina</p>{tag}", "sizeBytes": 10, "elapsedMs": 5, "url": "https://x/y"},
        enviado,
    )
    app.processEvents()
    p.confere("frase de status fica em texto, sem carregar imagem",
              janela.response.pill.sizeHint().height() < 100, str(janela.response.pill.sizeHint()))
    previa = janela.response.preview_box.layout().itemAt(0).widget()
    if isinstance(previa, QTextBrowser):
        previa.document().adjustSize()
    p.confere("previa do HTML nao le arquivo apontado pela pagina",
              isinstance(previa, QTextBrowser) and previa.document().size().height() < 100,
              f"{type(previa).__name__} {previa.document().size() if isinstance(previa, QTextBrowser) else ''}")
    tabela_headers = janela.response.headers_box.layout().itemAt(0).widget()
    dica = tabela_headers.item(1, 1).toolTip()
    p.confere("dica do header mostra a tag como texto", "<img" not in dica, dica[:60])

    import base64

    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    bruto_png = QByteArray()
    buffer_png = QBuffer(bruto_png)
    buffer_png.open(QIODevice.OpenModeFlag.WriteOnly)
    quadro.save(buffer_png, "PNG")
    embutida = "data:image/png;base64," + base64.b64encode(bytes(bruto_png)).decode()
    janela.response.show_response(
        {"ok": True, "status": 200, "reason": "OK", "headers": [["content-type", "text/html"]],
         "body": f"<p>pagina</p><img src='{embutida}'>", "sizeBytes": 10, "elapsedMs": 5,
         "url": "https://x/y"},
        enviado,
    )
    app.processEvents()
    previa = janela.response.preview_box.layout().itemAt(0).widget()
    if isinstance(previa, QTextBrowser):
        previa.document().adjustSize()
    # o data: nao sai da resposta, e barrado junto com o file: a pagina perdia o logo
    p.confere("imagem embutida no proprio HTML continua na previa",
              isinstance(previa, QTextBrowser) and previa.document().size().height() >= 250,
              f"{type(previa).__name__} {previa.document().size() if isinstance(previa, QTextBrowser) else ''}")

    detalhe = HistoryDetail({
        "id": "abc123", "ts": "2026-09-01T10:00:00", "trace": {"x-request-id": tag},
        "request": {"method": "GET", "url": "https://x/y", "headers": [], "body": ""},
        "response": {"ok": False, "status": 500, "reason": tag, "error": tag, "headers": [], "body": ""},
    })
    altos = [r.text()[:40] for r in detalhe.findChildren(QLabel) if r.sizeHint().height() >= 250]
    p.confere("detalhe do historico nao carrega o que veio do servidor", not altos, str(altos))
    detalhe.deleteLater()

    p.secao("salvar que falha nao se perde")
    for indice in reversed(range(janela.tabs.count())):
        janela.close_tab(indice)
    colecao_viva = janela.tree_data["collections"][0]
    nome_antigo = colecao_viva.get("name")
    outro_ws = ws.create_workspace("Destino da troca")
    escrever_original = ws.write_tree

    def disco_recusa(*_a, **_k):
        # grava metade e para, como faz o gravar_workspace quando um arquivo esta preso
        import os

        meio = raiz / "globals.yaml"
        os.utime(meio, (time.time() + 30, time.time() + 30))
        raise PermissionError(13, "arquivo preso por outro programa")

    perguntas: list = []
    QMessageBox.question = staticmethod(
        lambda *a, **k: perguntas.append(a[1:3]) or QMessageBox.StandardButton.No
    )
    ws.write_tree = disco_recusa
    try:
        colecao_viva["name"] = "Renomeada sem disco"
        janela.mark_dirty()
        gravou = janela._save_now()
        p.confere("salvar avisa que nao gravou", gravou is False, repr(gravou))
        janela._checar_disco()
        p.confere("e o timer do disco nao troca a memoria pelo disco",
                  janela.tree_data["collections"][0].get("name") == "Renomeada sem disco")

        from PySide6.QtGui import QCloseEvent

        fechar = QCloseEvent()
        janela.closeEvent(fechar)
        p.confere("fechar com o disco recusando pergunta e fica", not fechar.isAccepted() and bool(perguntas),
                  f"aceito={fechar.isAccepted()} perguntas={len(perguntas)}")
        antes_de_trocar = janela.workspace_id
        janela.load_workspace(outro_ws["id"])
        p.confere("trocar de workspace tambem pergunta e fica", janela.workspace_id == antes_de_trocar,
                  str(janela.workspace_id))

        from conduit.gui.workspaces_dialog import WorkspacesDialog

        exec_original, clicado_original = QMessageBox.exec, QMessageBox.clickedButton
        QMessageBox.exec = lambda self: 0
        QMessageBox.clickedButton = lambda self: next(b for b in self.buttons() if b.text() == "Tirar da lista")
        try:
            dialogo = WorkspacesDialog(janela)
            dialogo.excluir()
            dialogo.deleteLater()
        finally:
            QMessageBox.exec, QMessageBox.clickedButton = exec_original, clicado_original
        # a troca recusada deixa o workspace aberto, e excluir ele levava junto o que o
        # disco nao gravou
        p.confere("excluir o aberto com a troca recusada nao exclui nada",
                  janela.workspace_id == antes_de_trocar
                  and any(e["id"] == antes_de_trocar for e in ws.list_workspaces()["workspaces"]),
                  str(janela.workspace_id))

        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
        janela.load_workspace(outro_ws["id"])
        # aceito perder, a arvore e a do disco: com a marca ligada o timer do disco ficava
        # parado no workspace novo
        p.confere("trocar aceitando perder nao deixa nada pendente",
                  janela.workspace_id == outro_ws["id"] and not janela._falta_gravar)
        if janela.workspace_id != antes_de_trocar:
            janela.load_workspace(antes_de_trocar)
    except Exception as erro:  # noqa: BLE001
        p.confere("salvar que falha nao se perde", False, f"{type(erro).__name__}: {erro}")
    finally:
        ws.write_tree = escrever_original
        QMessageBox.question = original_pergunta
    colecao_viva["name"] = nome_antigo
    janela.mark_dirty()
    p.confere("com o disco de volta grava", janela._save_now() is True and not janela._falta_gravar)

    p.secao("request apagado por fora com a aba aberta")
    orfao = requests_de(janela.tree_data.get("collections"))[0]
    janela.open_request(orfao)
    aba_orfa = janela.editors[orfao["id"]]
    aba_orfa.url.setPlainText("https://edicao-que-nao-pode-sumir.exemplo")
    app.processEvents()
    pai_do_orfao = janela.tree_panel.find_parent(orfao)
    pai_do_orfao["items"].remove(orfao)
    janela.tree_panel.refresh()
    indice_orfa = janela.tabs.indexOf(aba_orfa)
    try:
        janela._duplicar_aba(indice_orfa)
        p.confere("duplicar a aba do request sumido nao estoura", True)
    except Exception as erro:  # noqa: BLE001
        p.confere("duplicar a aba do request sumido nao estoura", False, f"{type(erro).__name__}: {erro}")
    salvou = janela.salvar_aba(indice_orfa)
    p.confere("salvar nao diz salvo pra request que saiu da arvore",
              salvou is False and "salvo" not in janela.statusBar().currentMessage(),
              janela.statusBar().currentMessage())
    p.confere("e a alteracao continua na aba", janela._sujo(aba_orfa))
    pai_do_orfao["items"].append(orfao)
    janela.tree_panel.refresh()
    janela.close_tab(janela.tabs.indexOf(aba_orfa))
    janela._save_now()

    p.secao("OAuth2 com Authorization escrito a mao")
    servidor2 = ThreadingHTTPServer(("127.0.0.1", 0), Local)
    threading.Thread(target=servidor2.serve_forever, daemon=True).start()
    base2 = f"http://127.0.0.1:{servidor2.server_address[1]}"
    import socket

    fechado = socket.socket()
    fechado.bind(("127.0.0.1", 0))
    porta_fechada = fechado.getsockname()[1]
    fechado.close()
    pedidos_token.clear()
    manual = engine.prepare(
        {"id": "r-manual", "method": "GET", "url": f"{base2}/eco-auth",
         "headers": [{"key": "Authorization", "value": "Bearer escrito-a-mao"}],
         "auth": {"type": "oauth2", "tokenUrl": f"http://127.0.0.1:{porta_fechada}/token", "clientId": "c"}},
        {}, rede=False,
    )
    volta_manual = engine.send(manual)
    p.confere("provedor fora do ar nao barra o envio que nao usa o token",
              volta_manual.get("ok") and volta_manual.get("body") == "Bearer escrito-a-mao",
              repr(volta_manual.get("body") or volta_manual.get("error")))
    servidor2.shutdown()

    p.secao("certificado cliente carregado")
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    from datetime import datetime as _dt, timedelta, timezone

    chave_cliente = ec.generate_private_key(ec.SECP256R1())
    nome_cliente = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "cliente de teste")])
    certificado = (
        x509.CertificateBuilder().subject_name(nome_cliente).issuer_name(nome_cliente)
        .public_key(chave_cliente.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(_dt.now(timezone.utc) - timedelta(days=1))
        .not_valid_after(_dt.now(timezone.utc) + timedelta(days=1))
        .sign(chave_cliente, hashes.SHA256())
    )
    pem_bom = Path(tempfile.mkdtemp(prefix="conduit-cert-")) / "cliente.pem"
    pem_bom.write_bytes(
        chave_cliente.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption())
        + certificado.public_bytes(serialization.Encoding.PEM)
    )
    pasta_temp_ok = Path(tempfile.mkdtemp(prefix="conduit-pem-ok-"))
    anterior = tempfile.tempdir
    tempfile.tempdir = str(pasta_temp_ok)
    try:
        _contexto, copia_pem = certs.contexto_ssl(certs.Certificado(host="x", arquivo=str(pem_bom)), "")
        # o envio nao tem teto de leitura: a copia da chave em claro ficava la a espera
        p.confere("chave carregada nao fica em claro na pasta temporaria",
                  not Path(copia_pem).exists() and not list(pasta_temp_ok.glob("conduit-*.pem")),
                  str(list(pasta_temp_ok.glob("*"))))
    except Exception as erro:  # noqa: BLE001
        p.confere("chave carregada nao fica em claro na pasta temporaria", False, f"{type(erro).__name__}: {erro}")
    finally:
        tempfile.tempdir = anterior

    p.secao("codigo gerado com aspas no fim do corpo")
    for corpo in ('linha\n"""', 'linha\n""""', 'linha\n\\"'):
        literal = codegen._py_literal(corpo)
        try:
            p.confere(f"Python aceita corpo terminado em {corpo[6:]!r}", ast.literal_eval(literal) == corpo, literal)
        except (SyntaxError, ValueError) as erro:
            p.confere(f"Python aceita corpo terminado em {corpo[6:]!r}", False, f"{type(erro).__name__}: {erro}")

    p.secao("Bruno e Postman, ida e volta")
    pasta_bruno = Path(tempfile.mkdtemp(prefix="conduit-bruno-")) / "saida"
    importer.exportar(
        {"environments": [{"id": "e", "name": "hml", "values": [
            {"key": "base", "value": "https://hml"}, {"key": "token", "value": "x", "secret": True}]}]},
        [{"id": "c", "type": "collection", "name": "Api", "items": []}], "bruno", pasta_bruno,
    )
    volta_bruno = importer.importar(pasta_bruno, "Bruno")
    valores_bruno = {v["key"]: v for env in volta_bruno.environments for v in env["values"]}
    p.confere("variavel secreta do Bruno volta no import",
              valores_bruno.get("token", {}).get("secret") is True, str(sorted(valores_bruno)))

    ambiente_postman = pasta_io / "numeros.postman_environment.json"
    ambiente_postman.write_text(json.dumps({
        "name": "numeros", "_postman_variable_scope": "environment",
        "values": [{"key": "tentativas", "value": 0}, {"key": "ligado", "value": True}],
    }), encoding="utf-8")
    lido_postman = importer.importar(ambiente_postman)
    valores_postman = {v["key"]: v["value"] for env in lido_postman.environments for v in env["values"]}
    p.confere("zero e booleano do Postman nao somem",
              valores_postman == {"tentativas": "0", "ligado": "true"}, str(valores_postman))

    p.secao("log do historico com linha estranha")
    pasta_estranha = Path(tempfile.mkdtemp(prefix="conduit-hist-estranho-"))
    (pasta_estranha / "history").mkdir()
    (pasta_estranha / "history" / "2026-09-01.jsonl").write_text(
        "[1, 2]\n"
        '{"id": "ts-numero", "ts": 5}\n'
        '{"id": {"nao": "texto"}, "ts": "2026-09-01T10:00:00"}\n'
        '{"id": "grande", "ts": "2026-09-01T10:00:00", "response": {"status": 99999999999999999999}}\n'
        '{"id": "boa", "ts": "2026-09-01T10:00:00", "request": {"method": "GET"}, "response": {"ok": true}}\n',
        encoding="utf-8",
    )
    try:
        estranho = History(pasta_estranha)
        ids = {linha["id"] for linha in estranho.query(Query())}
        p.confere("abre o workspace e indexa o que da", ids == {"ts-numero", "boa"}, str(ids))
        estranho.close()
    except Exception as erro:  # noqa: BLE001
        p.confere("abre o workspace e indexa o que da", False, f"{type(erro).__name__}: {erro}")

    p.secao("duplicar em cima de workspace tirado da lista")
    sobra = ws.create_workspace("Sobra fora da lista")
    arvore_sobra = ws.read_tree(sobra["id"])
    arvore_sobra["collections"] = [{"id": "c-sobra", "type": "collection", "name": "Da sobra", "items": []}]
    ws.write_tree(sobra["id"], arvore_sobra)
    ws.delete_workspace(sobra["id"], apagar_arquivos=False)
    try:
        ws.duplicate_workspace(janela.workspace_id, "Sobra fora da lista")
        p.confere("duplicar nao mistura com a pasta que sobrou", False, "duplicou por cima")
    except ValueError:
        p.confere("duplicar nao mistura com a pasta que sobrou",
                  [c["name"] for c in storage.ler_workspace(Path(sobra["path"]))["collections"]] == ["Da sobra"])

    p.secao("exemplos tirado da lista volta com o que tinha")
    arvore_exemplos = ws.read_tree(mod_seed.EXAMPLES_ID)
    arvore_exemplos["collections"].append(
        {"id": "c-minha", "type": "collection", "name": "Minha dentro dos exemplos", "items": []}
    )
    ws.write_tree(mod_seed.EXAMPLES_ID, arvore_exemplos)
    ws.delete_workspace(mod_seed.EXAMPLES_ID, apagar_arquivos=False)
    mod_seed.ensure_examples()
    p.confere("a collection posta nos exemplos continua la",
              "Minha dentro dos exemplos" in [c["name"] for c in ws.read_tree(mod_seed.EXAMPLES_ID)["collections"]])

    p.secao("metodo fora da lista do seletor")
    colecao_do_metodo = janela.tree_data["collections"][0]
    for bruto, esperado in (("PURGE", "PURGE"), ("post", "POST")):
        estranho = {"id": f"req-metodo-{bruto}", "type": "request", "name": f"Metodo {bruto}",
                    "method": bruto, "url": "https://x/y", "params": [], "headers": [],
                    "body": {"mode": "none", "raw": ""}}
        colecao_do_metodo.setdefault("items", []).append(estranho)
        janela.tree_panel.refresh()
        janela.open_request(estranho)
        aba_metodo = janela.editors[estranho["id"]]
        # o seletor nao tinha o metodo e ficava no que estava antes, e o request virava GET
        p.confere(f"{bruto} abre como {esperado}",
                  aba_metodo.request.get("method") == esperado and aba_metodo.method.currentText() == esperado,
                  f"{aba_metodo.request.get('method')} {aba_metodo.method.currentText()}")
        p.confere(f"abrir {bruto} nao conta como alteracao", not janela._sujo(aba_metodo))
        aba_metodo.request["method"] = "LINK"
        aba_metodo.recarregar_do_modelo()
        p.confere("curl importado com metodo proprio mantem o metodo",
                  aba_metodo.request.get("method") == "LINK", str(aba_metodo.request.get("method")))
        janela.close_tab(janela.tabs.indexOf(aba_metodo))
        colecao_do_metodo["items"].remove(estranho)
    janela.tree_panel.refresh()

    p.secao("settings.yaml escrito na mao")
    pasta_cfg = Path(tempfile.mkdtemp(prefix="conduit-settings-"))
    (pasta_cfg / "settings.yaml").write_text(
        "activeEnv: null\ncertificates: lixo\nsftp:\n- texto solto\n"
        "- id: s1\n  host: 10\n  port: vinte e dois\n  user: 5\n",
        encoding="utf-8",
    )
    try:
        arvore_cfg = storage.ler_workspace(pasta_cfg)
        certs.para_url(arvore_cfg, "https://x/y")
        perfis_cfg = sftp.listar_perfis(arvore_cfg)
        p.confere("servidor com porta invalida abre e diz o que falta",
                  len(perfis_cfg) == 1 and "porta" in perfis_cfg[0].problema(),
                  str([pf.problema() for pf in perfis_cfg]))
    except Exception as erro:  # noqa: BLE001
        p.confere("servidor com porta invalida abre e diz o que falta", False, f"{type(erro).__name__}: {erro}")

    p.secao("request com auth e settings escritos na mao")
    pasta_torta = Path(tempfile.mkdtemp(prefix="conduit-torto-"))
    storage.gravar_workspace(pasta_torta, {"collections": [{
        "id": "c-torta", "type": "collection", "name": "Torta",
        "items": [{"id": "r-torto", "type": "request", "name": "Torto", "method": "GET", "url": "https://x"}],
    }]})
    arquivo_torto = pasta_torta / "collections" / "torta" / "torto.yaml"
    arquivo_torto.write_text(
        arquivo_torto.read_text(encoding="utf-8")
        + "auth: bearer abc\nsettings:\n  timeout: 30s\nexamples:\n- texto solto\n",
        encoding="utf-8",
    )
    try:
        lido_torto = storage.ler_workspace(pasta_torta)["collections"][0]["items"][0]
        from conduit.core import auth as mod_auth

        mod_auth.efetiva(lido_torto, [])
        engine.prepare(lido_torto, {}, rede=False)
        p.confere("abre a aba e prepara o envio sem estourar", not lido_torto.get("examples"))
    except Exception as erro:  # noqa: BLE001
        p.confere("abre a aba e prepara o envio sem estourar", False, f"{type(erro).__name__}: {erro}")

    p.secao("aba de ambiente depois de recarregar do disco")
    import yaml as _yaml

    janela._save_now()
    ambientes = janela.tree_data.get("environments") or []
    if ambientes:
        env_aba = ambientes[0]
        janela.open_environment(env_aba["id"])
        aba_env = janela.env_editors[env_aba["id"]]
        arquivo_env = next(
            a for a in (raiz / "environments").glob("*.yaml")
            if (_yaml.safe_load(a.read_text(encoding="utf-8")) or {}).get("id") == env_aba["id"]
        )
        dados_env = _yaml.safe_load(arquivo_env.read_text(encoding="utf-8"))
        dados_env.setdefault("values", []).append({"key": "veio_de_fora", "value": "1"})
        time.sleep(0.05)
        arquivo_env.write_text(_yaml.safe_dump(dados_env, allow_unicode=True, sort_keys=False), encoding="utf-8")
        janela._checar_disco()
        # a aba seguia no dicionario da arvore antiga: editar nela nao chegava ao disco
        aba_env.tabela.rows.append({"key": "digitada_na_aba", "value": "2", "enabled": True})
        aba_env.tabela.changed.emit()
        janela._save_now()
        no_disco = {v.get("key") for v in _yaml.safe_load(arquivo_env.read_text(encoding="utf-8")).get("values") or []}
        p.confere("edicao na aba de ambiente depois de recarregar vai pro disco",
                  {"veio_de_fora", "digitada_na_aba"} <= no_disco, str(sorted(no_disco)))
        janela.close_tab(janela.tabs.indexOf(aba_env))

    p.secao("dialogo aberto segura o recarregar")
    arvore_antes = janela.tree_data
    globais_arquivo = raiz / "globals.yaml"
    time.sleep(0.05)
    globais_arquivo.write_text(globais_arquivo.read_text(encoding="utf-8") + "# mexido por fora\n", encoding="utf-8")
    modal_original = QApplication.activeModalWidget
    QApplication.activeModalWidget = staticmethod(lambda: janela)
    try:
        janela._checar_disco()
    finally:
        QApplication.activeModalWidget = modal_original
    # o dialogo de variaveis edita a arvore que recebeu ao abrir: trocar por baixo dele
    # jogava fora o que se digitava ali
    p.confere("com dialogo aberto a arvore da memoria fica", janela.tree_data is arvore_antes)
    janela._checar_disco()
    p.confere("fechado o dialogo, o que mudou por fora chega", janela.tree_data is not arvore_antes)

    p.secao("jar de cookie estragado")
    from conduit.core.cookies import CookieJar

    pasta_jar = Path(tempfile.mkdtemp(prefix="conduit-jar-"))
    (pasta_jar / "cookies").mkdir()
    for rotulo, bruto in (
        ("lista no lugar do mapa", b"[1, 2]"),
        ("arquivo fora do UTF-8", b"\xff\xfe{\x00}\x00"),
        ("host com texto no lugar dos cookies", b'{"x.com": "lixo", "y.com": {"a": "1"}}'),
    ):
        (pasta_jar / "cookies" / "jar.json").write_bytes(bruto)
        try:
            achado = CookieJar(pasta_jar).para_url("https://y.com/z")
            p.confere(f"jar com {rotulo} nao barra o envio", isinstance(achado, dict), str(achado))
        except Exception as erro:  # noqa: BLE001
            p.confere(f"jar com {rotulo} nao barra o envio", False, f"{type(erro).__name__}: {erro}")

    p.secao("aba fechada sai da memoria")
    from PySide6.QtCore import QCoreApplication, QEvent

    from conduit.gui.request_editor import RequestEditor

    def editores_vivos() -> int:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        return len(janela.findChildren(RequestEditor))

    vai_e_volta = requests_de(janela.tree_data.get("collections"))[0]
    base_editores = editores_vivos()
    for _ in range(12):
        janela.open_request(vai_e_volta)
        janela.close_tab(janela.tabs.indexOf(janela.editors[vai_e_volta["id"]]))
    # removeTab so escondia a pagina: cada aba aberta e fechada ficava viva ate o fim
    p.confere("abrir e fechar a mesma aba nao acumula editor", editores_vivos() <= base_editores,
              f"{base_editores} antes, {editores_vivos()} depois")

    p.secao("grade com numero vindo de import")
    from conduit.gui.kvtable import KvTable

    grade = KvTable([{"key": "porta", "value": 8080, "enabled": True}], ("Chave", "Valor"))
    # QTableWidgetItem(8080) le o inteiro como tipo do item, e a celula nascia vazia
    p.confere("valor numerico aparece na celula", grade.table.item(0, 2).text() == "8080",
              repr(grade.table.item(0, 2).text()))
    grade.deleteLater()

    QMessageBox.warning = original_aviso
    return p.fechar()


if __name__ == "__main__":
    sys.exit(main())
