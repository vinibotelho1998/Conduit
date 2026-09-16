"""Sobe a janela de verdade e confere o que so aparece com ela montada.

O foco e a classe de defeito que ja mordeu este app mais de uma vez: cor resolvida cedo
demais e presa pra sempre. Trocar de tema e checar que nada ficou na paleta anterior e
o unico jeito honesto de garantir isso, porque no olho a diferenca so aparece no tema
que voce nao estava usando na hora de programar.
"""

from __future__ import annotations

import colorsys
import inspect
import sys
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

    return p.fechar()


if __name__ == "__main__":
    sys.exit(main())
