"""Os valores crus da interface: cor, espaco, raio, fonte e tempo.

Por que este arquivo existe. Antes cada cor, cada canto redondo e cada tamanho de fonte
nasciam no ponto onde eram usados. Deu quinze raios de canto diferentes, doze tamanhos de
fonte, quatro azuis de selecao e quatro pretos pra mesma tinta escura. Nada disso era
escolha, era repeticao. Aqui existe uma escala de cada coisa, e o resto do app so escolhe
um degrau dela.

O nome do token diz o papel e nao a cor, entao a mesma folha serve pro tema escuro e pro
claro. `superficie` continua sendo superficie quando ela e branca.

Contraste conferido contra a WCAG 2.1. Todo token que carrega informacao passa de 4.5
contra o fundo em que e usado, conferido por `contraste` aqui mesmo. Os dois que ficam
entre 3 e 4.5 sao `texto_apagado` e nada mais: ele so pinta controle desligado, que a
norma dispensa justamente por nao ser leitura obrigatoria.
"""

from __future__ import annotations

# ----------------------------------------------------------------------------- escalas

# Espaco em passos de 4, com dois degraus finos embaixo pra respiro dentro de controle.
ESPACO = {0: 0, 1: 2, 2: 4, 3: 6, 4: 8, 5: 12, 6: 16, 7: 20, 8: 24, 9: 32}

# Quatro raios e a pilula. Canto redondo demais em caixa pequena vira circulo, e canto
# pequeno em cartao grande parece corte. Um raio por familia de tamanho resolve.
RAIO = {"micro": 4, "pequeno": 6, "medio": 9, "grande": 12, "cartao": 16, "pilula": 999}

# A escala de texto sai de 10pt, que e o corpo. O miudo desce meio ponto por degrau
# porque abaixo de 8 o Segoe UI perde o desenho da letra.
FONTE = {"micro": 8.0, "miudo": 8.5, "corpo": 10.0, "medio": 11.0, "titulo": 13.0}

FAMILIA = "Segoe UI, Inter, system-ui, sans-serif"
FAMILIA_MONO = "Cascadia Code, Cascadia Mono, Consolas, Courier New, monospace"

# Duas densidades. A confortavel e a de hoje. A compacta ganha quase quatro linhas de
# arvore numa tela de notebook, que e onde o app aperta.
DENSIDADE = {
    "compacta": {
        "linha_arvore": 25,
        "linha_grade": 26,
        "linha_tabela": 22,
        "altura_aba": 33,
        "altura_campo": 30,
        "altura_barra": 36,
        "respiro": 4,
    },
    "confortavel": {
        "linha_arvore": 30,
        "linha_grade": 30,
        "linha_tabela": 26,
        "altura_aba": 39,
        "altura_campo": 34,
        "altura_barra": 42,
        "respiro": 6,
    },
}

# Duracao de animacao, em ms. Zerado quando o sistema pede menos movimento.
TEMPO = {"rapido": 90, "medio": 150, "lento": 240}


# ------------------------------------------------------------------------------ paletas

# Preto e cinza na base, com um acento so. A regra que sustenta as duas paletas: tudo
# que e estrutura, ou seja superficie, borda e texto, e cinza neutro de verdade, sem
# matiz nenhuma. Cor aparece em tres lugares e mais nenhum: no acento, que marca o que
# responde ao clique; no metodo e no status, que sao dado; e no realce do corpo.
#
# Sem acento nenhum a tela vira preto e branco e nada puxa o olho, que foi o erro da
# primeira tentativa. Com a marca violeta ela competia com o metodo e o status, que foi
# o erro da anterior. Azul de aco fica no meio: presente, e sem gritar.

ESCURO = {
    "nome": "escuro",
    "claro": False,
    # superficies, da mais funda pra mais alta. Cinza neutro de verdade, sem puxar pro
    # azul nem pro violeta: qualquer matiz aqui tinge a tela inteira.
    "fundo": "#0e0e0f",
    "superficie": "#151516",
    "superficie_alta": "#1c1c1e",
    "elevado": "#26262a",
    "flutuante": "#1e1e21",
    # tracos
    "borda": "#2b2b2f",
    "borda_forte": "#3d3d43",
    # texto
    "texto": "#ededee",
    "texto_medio": "#adadb2",
    "texto_fraco": "#8e8e95",
    "texto_apagado": "#64646b",
    # marca e estados
    "marca": "#5b9fd6",
    "marca_clara": "#7ab6e4",
    "marca_tinta": "#0a1219",
    "marca_fundo": "#1d3143",
    "ok": "#3ecf8e",
    "aviso": "#efa63c",
    "erro": "#ff5f70",
    # 3xx e redirecionamento, nao e sucesso nem falha: cinza claro diz isso melhor que
    # mais um matiz disputando espaco com o verde e o ambar do lado
    "info": "#7ab6e4",
    # selecao e foco
    "selecao": "#232f3a",
    "selecao_texto": "#2f4a60",
    "foco": "#7ab6e4",
    "hover": "#1c1c1e",
    # cromo
    "barra_rolagem": "#37373d",
    "barra_rolagem_sob": "#4a4a52",
    "sombra": "#00000080",
}

CLARO = {
    "nome": "claro",
    "claro": True,
    "fundo": "#f4f4f5",
    "superficie": "#ffffff",
    "superficie_alta": "#fafafa",
    "elevado": "#ebebec",
    "flutuante": "#ffffff",
    "borda": "#e3e3e5",
    "borda_forte": "#c6c6ca",
    "texto": "#171719",
    "texto_medio": "#55555c",
    "texto_fraco": "#68686f",
    "texto_apagado": "#96969d",
    "marca": "#1f6fb8",
    "marca_clara": "#2b84d4",
    "marca_tinta": "#ffffff",
    "marca_fundo": "#dceafd",
    "ok": "#0a6c4a",
    "aviso": "#8a5209",
    "erro": "#c0273a",
    "info": "#1f6fb8",
    "selecao": "#dceafd",
    "selecao_texto": "#c2ddfa",
    "foco": "#1f6fb8",
    "hover": "#f1f1f2",
    "barra_rolagem": "#cfcfd3",
    "barra_rolagem_sob": "#b0b0b6",
    "sombra": "#17171a26",
}

# Sete metodos, sete matizes espacadas no circulo de cor, em duas versoes: a do escuro
# brilha sobre fundo fundo, a do claro e a mesma matiz escurecida ate passar de 4.5
# contra o branco. Sem isso o tema claro entrega pilula amarela ilegivel.
#
# Aqui a cor fica, e de proposito: metodo e o dado que o olho procura primeiro na
# arvore e na aba. Como o cromo do app inteiro e cinza, estas sete pilulas e as de
# status sao praticamente as unicas manchas de cor na tela, e por isso elas saltam.
METODOS_ESCURO = {
    "GET": "#3ecf8e",
    "POST": "#ff9a3c",
    "PUT": "#5aa9e6",
    "PATCH": "#2dd4bf",
    "DELETE": "#ff5f70",
    "HEAD": "#9aa5b5",
    "OPTIONS": "#d9b64a",
}

METODOS_CLARO = {
    "GET": "#0a6c4a",
    "POST": "#a85708",
    "PUT": "#15588f",
    "PATCH": "#0a7269",
    "DELETE": "#c0273a",
    "HEAD": "#4f5967",
    "OPTIONS": "#836000",
}

# Realce de sintaxe, por tema. Antes eram oito literais congelados no import do
# highlight, entao no tema claro o JSON saia em verde neon sobre branco.
#
# Corpo de resposta e leitura longa, entao aqui a cor e contida: a chave sai num cinza
# claro quase branco, que ja e o suficiente pra separar chave de valor, e so o valor
# ganha matiz. Um JSON com quatro cores fortes cansa em meia hora de leitura.
CODIGO_ESCURO = {
    "chave": "#8fc6f0",
    "texto": "#a5e075",
    "numero": "#f2c464",
    "palavra": "#7fd6c4",
    "sinal": "#8b8b92",
    "comentario": "#8d8d94",
    "tag": "#8fc6f0",
    "atributo": "#f2c464",
    # A variavel e marca do app dentro do texto do usuario, entao ela e neutra e
    # negrito. O segredo puxa pro ambar porque ali a cor e aviso, nao decoracao.
    "variavel": "#5b9fd6",
    "variavel_secreta": "#efa63c",
    "variavel_sem_dono": "#ff5f70",
    "achado": "#2f4a60",
}

CODIGO_CLARO = {
    "chave": "#15588f",
    "texto": "#116b32",
    "numero": "#8f5400",
    "palavra": "#0a7269",
    "sinal": "#6c6c73",
    "comentario": "#6f6f76",
    "tag": "#15588f",
    "atributo": "#8f5400",
    "variavel": "#1f6fb8",
    "variavel_secreta": "#8a5209",
    "variavel_sem_dono": "#c0273a",
    "achado": "#cfe3fa",
}

PALETAS = {"escuro": ESCURO, "claro": CLARO}


# ------------------------------------------------------------------------------ helpers


def _hex_para_rgb(cor: str) -> tuple[int, int, int]:
    valor = cor.lstrip("#")
    if len(valor) == 3:
        valor = "".join(c * 2 for c in valor)
    return int(valor[0:2], 16), int(valor[2:4], 16), int(valor[4:6], 16)


def alfa(cor: str, opacidade: float) -> str:
    """Cor com transparencia, no formato que a folha de estilo do Qt entende.

    Existe por causa de um bug que passou muito tempo em pe: o codigo escrevia
    `f"{cor}44"` pra dizer vinte e sete por cento. Sete digitos depois do jogo da velha
    nao e RGBA no Qt, e sim ARGB, entao `#ff607644` era lido como alfa ff, vermelho 60,
    verde 76 e azul 44. A borda da pilula de erro saia marrom. Aqui nao tem como errar.
    """
    r, g, b = _hex_para_rgb(cor)
    return f"rgba({r}, {g}, {b}, {max(0.0, min(1.0, opacidade)):.3f})"


def mistura(frente: str, fundo: str, peso: float) -> str:
    """Mistura duas cores opacas. Serve pra achatar transparencia onde o Qt nao aceita."""
    fr, fg, fb = _hex_para_rgb(frente)
    br, bg, bb = _hex_para_rgb(fundo)
    p = max(0.0, min(1.0, peso))
    return "#%02x%02x%02x" % (
        round(fr * p + br * (1 - p)),
        round(fg * p + bg * (1 - p)),
        round(fb * p + bb * (1 - p)),
    )


def luminancia(cor: str) -> float:
    def canal(c: float) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = _hex_para_rgb(cor)
    return 0.2126 * canal(r) + 0.7152 * canal(g) + 0.0722 * canal(b)


def contraste(a: str, b: str) -> float:
    la, lb = luminancia(a), luminancia(b)
    alto, baixo = max(la, lb), min(la, lb)
    return (alto + 0.05) / (baixo + 0.05)


def tinta_sobre(cor: str) -> str:
    """Preto ou branco, o que ler melhor em cima da cor dada."""
    return "#0a1220" if luminancia(cor) > 0.42 else "#ffffff"
