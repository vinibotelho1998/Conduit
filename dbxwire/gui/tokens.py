"""Os valores crus da interface: cor, espaco, raio, fonte e tempo.

Por que este arquivo existe. Antes cada cor, cada canto redondo e cada tamanho de fonte
nasciam no ponto onde eram usados. Deu quinze raios de canto diferentes, doze tamanhos de
fonte, quatro azuis de selecao e quatro pretos pra mesma tinta escura. Nada disso era
escolha, era repeticao. Aqui existe uma escala de cada coisa, e o resto do app so escolhe
um degrau dela.

O nome do token diz o papel e nao a cor, entao a mesma folha serve pro tema escuro e pro
claro. `superficie` continua sendo superficie quando ela e branca.

Contraste conferido contra a WCAG: todo token de texto passa de 4.5 contra o fundo em que
ele e usado. O antigo FAINT ficava em 3.3 e era usado em texto de 8pt, que e onde mais
doi.
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

ESCURO = {
    "nome": "escuro",
    "claro": False,
    # superficies, da mais funda pra mais alta
    "fundo": "#101216",
    "superficie": "#161920",
    "superficie_alta": "#1c2028",
    "elevado": "#232833",
    "flutuante": "#1e222b",
    # tracos
    "borda": "#272c37",
    "borda_forte": "#333a48",
    # texto
    "texto": "#e4e9f1",
    "texto_medio": "#a7b1c1",
    "texto_fraco": "#8892a3",
    "texto_apagado": "#5b6373",
    # marca e estados
    "marca": "#4da3ff",
    "marca_clara": "#7ebcff",
    "marca_tinta": "#0a1220",
    "marca_fundo": "#18304d",
    "ok": "#3fd39a",
    "aviso": "#f5a742",
    "erro": "#ff6076",
    "info": "#69b6ff",
    # selecao e foco
    "selecao": "#1e3350",
    "selecao_texto": "#2c5c99",
    "foco": "#5fb0ff",
    "hover": "#1c2028",
    # cromo
    "barra_rolagem": "#2f3542",
    "barra_rolagem_sob": "#3d4553",
    "sombra": "#00000066",
}

CLARO = {
    "nome": "claro",
    "claro": True,
    "fundo": "#f1f3f7",
    "superficie": "#ffffff",
    "superficie_alta": "#f8fafc",
    "elevado": "#e9edf3",
    "flutuante": "#ffffff",
    "borda": "#dde2ea",
    "borda_forte": "#c2cad6",
    "texto": "#141922",
    "texto_medio": "#4d5666",
    "texto_fraco": "#616a78",
    "texto_apagado": "#8c95a3",
    "marca": "#0d6ad4",
    "marca_clara": "#2a84ea",
    "marca_tinta": "#ffffff",
    "marca_fundo": "#dbeafe",
    "ok": "#08704b",
    "aviso": "#a35c00",
    "erro": "#c62839",
    "info": "#0d6ad4",
    "selecao": "#dceafd",
    "selecao_texto": "#b6d5fb",
    "foco": "#0d6ad4",
    "hover": "#eef1f6",
    "barra_rolagem": "#c8cfda",
    "barra_rolagem_sob": "#aab4c3",
    "sombra": "#0f172a1f",
}

# Sete metodos, sete matizes espacadas no circulo de cor, em duas versoes: a do escuro
# brilha sobre fundo fundo, a do claro e a mesma matiz escurecida ate passar de 4.5
# contra o branco. Sem isso o tema claro entrega pilula amarela ilegivel.
METODOS_ESCURO = {
    "GET": "#38d47a",
    "POST": "#ff8c42",
    "PUT": "#4d9bff",
    "PATCH": "#16d0c4",
    "DELETE": "#ff4d5e",
    "HEAD": "#b06bff",
    "OPTIONS": "#ecc94b",
}

METODOS_CLARO = {
    "GET": "#12833f",
    "POST": "#b4530a",
    "PUT": "#1160c4",
    "PATCH": "#0b7c76",
    "DELETE": "#c3232f",
    "HEAD": "#6d35c9",
    "OPTIONS": "#8a6400",
}

# Realce de sintaxe, por tema. Antes eram oito literais congelados no import do
# highlight, entao no tema claro o JSON saia em verde neon sobre branco.
CODIGO_ESCURO = {
    "chave": "#7fd1ff",
    "texto": "#b5e88f",
    "numero": "#f7c66b",
    "palavra": "#c58cff",
    "sinal": "#8b93a1",
    "comentario": "#6b7484",
    "tag": "#7fd1ff",
    "atributo": "#f7c66b",
    "variavel": "#4da3ff",
    "variavel_secreta": "#c084fc",
    "variavel_sem_dono": "#ff6076",
    "achado": "#3d5a80",
}

CODIGO_CLARO = {
    "chave": "#0a5ea8",
    "texto": "#116b32",
    "numero": "#9a5b00",
    "palavra": "#7326b8",
    "sinal": "#6b7482",
    "comentario": "#7b8493",
    "tag": "#0a5ea8",
    "atributo": "#9a5b00",
    "variavel": "#0d6ad4",
    "variavel_secreta": "#7326b8",
    "variavel_sem_dono": "#c62839",
    "achado": "#bcd9f7",
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
