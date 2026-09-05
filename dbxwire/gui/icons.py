"""Icones da arvore, desenhados em codigo e nitidos em tela de alta densidade.

Tudo cabe numa faixa fixa, alinhado a direita, pra collection, pasta e request ficarem
com o texto comecando na mesma coluna. Nada de caractere de fonte: fonte muda de maquina
pra maquina e alguns simbolos nem existem em todas.

Sobre nitidez. O desenho e feito num pixmap ESCALA vezes maior com devicePixelRatio
avisado, entao o Qt reduz na hora de exibir com filtragem e nao serrilha. Duas
armadilhas ja pagas aqui: com devicePixelRatio definido o painter ja trabalha em
coordenada logica, escalar de novo joga tudo pra fora da area; e texto miudo precisa de
hinting desligado, senao o downscale engorda a letra e borra.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap

from . import theme

LARGURA = 52
ALTURA = 18
ESCALA = 4

# Metodo longo em pilula estreita vira borrao. Abreviacao curta le melhor, e o nome
# inteiro continua visivel no seletor e no tooltip.
#
# Nenhuma funcao daqui usa cor do tema como valor padrao de argumento: Python avalia
# esse valor uma vez, no import, entao o padrao ficava preso na paleta de quando o
# modulo carregou e chamada sem argumento devolvia icone do tema errado depois da troca.
# Todas recebem "" e resolvem a cor dentro, antes de montar a chave do cache.
ABREVIACAO = {"OPTIONS": "OPTS", "DELETE": "DEL"}

_cache: dict[str, QIcon] = {}


def limpar_cache() -> None:
    """Esquece todo icone ja desenhado. Chamado quando o tema muda.

    Sem isso a arvore continuava com as pilulas do tema antigo ate o app reabrir, porque
    a chave do cache so tinha metodo e status, nunca o tema.
    """
    _cache.clear()


theme.ao_trocar(limpar_cache)


def _fonte_pilula(tamanho: float) -> QFont:
    fonte = QFont("Segoe UI")
    fonte.setPointSizeF(tamanho)
    fonte.setWeight(QFont.Weight.Bold)
    fonte.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.4)
    fonte.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return fonte


def _tela(largura: int = LARGURA, altura: int = ALTURA) -> tuple[QPixmap, QPainter]:
    pix = QPixmap(largura * ESCALA, altura * ESCALA)
    pix.fill(Qt.GlobalColor.transparent)
    pix.setDevicePixelRatio(ESCALA)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    return pix, painter


def _guardar(chave: str, pix: QPixmap) -> QIcon:
    icone = QIcon(pix)
    _cache[chave] = icone
    return icone


def method_icon(method: str) -> QIcon:
    """Pilula com o metodo, fundo tingido e contorno na cor dele.

    Pilula le melhor que texto solto porque o olho acha o bloco de cor antes da palavra,
    e o alinhamento a direita cria uma coluna limpa na arvore. O contorno fino da
    definicao na borda, que fundo tingido sozinho nao da.
    """
    chave = f"m5:{method}"
    if chave in _cache:
        return _cache[chave]

    cor = QColor(theme.METHOD_COLORS.get(method, theme.DIM))
    texto = ABREVIACAO.get(method, method)

    pix, painter = _tela()
    painter.setFont(_fonte_pilula(7.2 if len(texto) <= 4 else 6.6))

    largura_texto = painter.fontMetrics().horizontalAdvance(texto)
    largura_pilula = min(LARGURA - 2, largura_texto + 11)
    caixa = QRectF(LARGURA - largura_pilula - 1, 2.0, largura_pilula, ALTURA - 4)

    fundo = QColor(cor)
    fundo.setAlpha(40)
    contorno = QColor(cor)
    contorno.setAlpha(105)

    caneta = QPen(contorno)
    caneta.setWidthF(0.9)
    painter.setPen(caneta)
    painter.setBrush(fundo)
    painter.drawRoundedRect(caixa, 4.5, 4.5)

    painter.setPen(QPen(cor))
    painter.drawText(caixa, Qt.AlignmentFlag.AlignCenter, texto)
    painter.end()
    return _guardar(chave, pix)


def collection_icon(cor: str = "") -> QIcon:
    """Tres placas empilhadas, o desenho classico de camadas.

    Placa achatada com folga entre elas le como pilha. Losango cheio, que era o desenho
    anterior, lia como pedra preciosa.
    """
    cor = cor or theme.ACCENT
    chave = f"c5:{cor}"
    if chave in _cache:
        return _cache[chave]

    base = QColor(cor)
    pix, painter = _tela()
    painter.setPen(Qt.PenStyle.NoPen)

    centro_x = LARGURA - 9.5
    meia_largura = 7.2
    meia_altura = 3.1

    def placa(centro_y: float, alpha: int) -> None:
        camada = QColor(base)
        camada.setAlpha(alpha)
        painter.setBrush(camada)
        caminho = QPainterPath()
        caminho.moveTo(QPointF(centro_x, centro_y - meia_altura))
        caminho.lineTo(QPointF(centro_x + meia_largura, centro_y))
        caminho.lineTo(QPointF(centro_x, centro_y + meia_altura))
        caminho.lineTo(QPointF(centro_x - meia_largura, centro_y))
        caminho.closeSubpath()
        painter.drawPath(caminho)

    placa(13.4, 85)
    placa(10.0, 140)
    painter.setBrush(QBrush(base))
    placa(6.2, 255)

    painter.end()
    return _guardar(chave, pix)


def folder_icon(aberta: bool = False, cor: str = "") -> QIcon:
    """Pasta com aba. A aberta muda de cor e inclina a frente, pra ler de relance."""
    cor = cor or theme.DIM
    chave = f"f5:{aberta}:{cor}"
    if chave in _cache:
        return _cache[chave]

    base = QColor(theme.ACCENT).lighter(108) if aberta else QColor(cor)

    pix, painter = _tela()
    esquerda = LARGURA - 17.0
    topo = 4.2
    largura = 14.0
    altura = 10.4

    contorno = QColor(base)
    contorno.setAlpha(150)
    caneta = QPen(contorno)
    caneta.setWidthF(0.8)

    aba = QColor(base)
    aba.setAlpha(140)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(aba)
    painter.drawRoundedRect(QRectF(esquerda, topo - 2.4, largura * 0.46, 3.4), 1.2, 1.2)

    corpo = QColor(base)
    corpo.setAlpha(210)

    if not aberta:
        painter.setPen(caneta)
        painter.setBrush(corpo)
        painter.drawRoundedRect(QRectF(esquerda, topo, largura, altura), 2.2, 2.2)
    else:
        fundo = QColor(base)
        fundo.setAlpha(105)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fundo)
        painter.drawRoundedRect(QRectF(esquerda, topo, largura, altura), 2.2, 2.2)

        frente = QPainterPath()
        frente.moveTo(QPointF(esquerda + 2.6, topo + altura))
        frente.lineTo(QPointF(esquerda + largura + 2.4, topo + altura))
        frente.lineTo(QPointF(esquerda + largura - 1.0, topo + 3.6))
        frente.lineTo(QPointF(esquerda - 1.6, topo + 3.6))
        frente.closeSubpath()
        painter.setPen(caneta)
        painter.setBrush(corpo)
        painter.drawPath(frente)

    painter.end()
    return _guardar(chave, pix)


def status_icon(status, ok: bool = True) -> QIcon:
    """Pilula com o codigo de status, na mesma familia visual da pilula de metodo."""
    chave = f"s5:{status}:{ok}"
    if chave in _cache:
        return _cache[chave]

    if not ok or not status:
        cor = QColor(theme.ERR)
        texto = str(status) if status else "erro"
    else:
        cor = QColor(theme.cor_do_status(int(status), True))
        texto = str(status)

    pix, painter = _tela()
    painter.setFont(_fonte_pilula(7.2))

    largura_texto = painter.fontMetrics().horizontalAdvance(texto)
    largura_pilula = min(LARGURA - 2, largura_texto + 11)
    caixa = QRectF(LARGURA - largura_pilula - 1, 2.0, largura_pilula, ALTURA - 4)

    fundo = QColor(cor)
    fundo.setAlpha(40)
    contorno = QColor(cor)
    contorno.setAlpha(105)

    caneta = QPen(contorno)
    caneta.setWidthF(0.9)
    painter.setPen(caneta)
    painter.setBrush(fundo)
    painter.drawRoundedRect(caixa, 4.5, 4.5)

    painter.setPen(QPen(cor))
    painter.drawText(caixa, Qt.AlignmentFlag.AlignCenter, texto)
    painter.end()
    return _guardar(chave, pix)


def chevron_icon(aberto: bool, cor: str = "") -> QIcon:
    """Seta de expandir, na mesma familia de tracos do resto."""
    cor = cor or theme.FAINT
    chave = f"v5:{aberto}:{cor}"
    if chave in _cache:
        return _cache[chave]

    pix, painter = _tela(12, 12)
    caneta = QPen(QColor(cor))
    caneta.setWidthF(1.5)
    caneta.setCapStyle(Qt.PenCapStyle.RoundCap)
    caneta.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(caneta)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    caminho = QPainterPath()
    if aberto:
        caminho.moveTo(QPointF(3.2, 4.9))
        caminho.lineTo(QPointF(6.0, 7.7))
        caminho.lineTo(QPointF(8.8, 4.9))
    else:
        caminho.moveTo(QPointF(4.9, 3.2))
        caminho.lineTo(QPointF(7.7, 6.0))
        caminho.lineTo(QPointF(4.9, 8.8))
    painter.drawPath(caminho)
    painter.end()
    return _guardar(chave, pix)


def limpar_cache() -> None:
    _cache.clear()


#
# Icone de acao: quadrado de 18, traco de 1.5, mesma linguagem do chevron da arvore.
# Rotulo escrito ficava comprido demais numa barra que tem quatro acoes lado a lado, e
# tres palavras seguidas pareciam menu solto em cima da resposta.

LADO = 18


def _caneta(painter: QPainter, cor: str, largura: float = 1.5) -> QPen:
    caneta = QPen(QColor(cor))
    caneta.setWidthF(largura)
    caneta.setCapStyle(Qt.PenCapStyle.RoundCap)
    caneta.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(caneta)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    return caneta


def icone_copiar(cor: str = "") -> QIcon:
    """Duas folhas sobrepostas."""
    cor = cor or theme.DIM
    chave = f"copiar:{cor}"
    if chave in _cache:
        return _cache[chave]
    pix, painter = _tela(LADO, LADO)
    _caneta(painter, cor)
    painter.drawRoundedRect(QRectF(6.0, 3.0, 9.0, 11.0), 2.0, 2.0)
    painter.drawRoundedRect(QRectF(3.0, 6.0, 9.0, 11.0), 2.0, 2.0)
    painter.end()
    return _guardar(chave, pix)


def icone_baixar(cor: str = "") -> QIcon:
    """Seta pra baixo em cima de uma base: salvar em arquivo."""
    cor = cor or theme.DIM
    chave = f"baixar:{cor}"
    if chave in _cache:
        return _cache[chave]
    pix, painter = _tela(LADO, LADO)
    _caneta(painter, cor)
    painter.drawLine(QPointF(9.0, 3.0), QPointF(9.0, 11.4))
    caminho = QPainterPath()
    caminho.moveTo(QPointF(5.4, 8.0))
    caminho.lineTo(QPointF(9.0, 11.6))
    caminho.lineTo(QPointF(12.6, 8.0))
    painter.drawPath(caminho)
    painter.drawLine(QPointF(3.6, 14.6), QPointF(14.4, 14.6))
    painter.end()
    return _guardar(chave, pix)


def icone_marcador(cor: str = "") -> QIcon:
    """Marcador de pagina: guardar esta resposta como exemplo."""
    cor = cor or theme.DIM
    chave = f"marcador:{cor}"
    if chave in _cache:
        return _cache[chave]
    pix, painter = _tela(LADO, LADO)
    _caneta(painter, cor)
    caminho = QPainterPath()
    caminho.moveTo(QPointF(5.0, 3.2))
    caminho.lineTo(QPointF(13.0, 3.2))
    caminho.lineTo(QPointF(13.0, 15.0))
    caminho.lineTo(QPointF(9.0, 11.4))
    caminho.lineTo(QPointF(5.0, 15.0))
    caminho.closeSubpath()
    painter.drawPath(caminho)
    painter.end()
    return _guardar(chave, pix)


def icone_quebra(cor: str = "") -> QIcon:
    """Seta que volta pra linha de baixo: quebrar linha."""
    cor = cor or theme.DIM
    chave = f"quebra:{cor}"
    if chave in _cache:
        return _cache[chave]
    pix, painter = _tela(LADO, LADO)
    _caneta(painter, cor)
    painter.drawLine(QPointF(3.4, 5.0), QPointF(14.6, 5.0))
    caminho = QPainterPath()
    caminho.moveTo(QPointF(3.4, 9.4))
    caminho.lineTo(QPointF(12.0, 9.4))
    caminho.arcTo(QRectF(9.6, 9.4, 5.0, 5.0), 90.0, -180.0)
    caminho.lineTo(QPointF(6.0, 14.4))
    painter.drawPath(caminho)
    seta = QPainterPath()
    seta.moveTo(QPointF(8.0, 12.4))
    seta.lineTo(QPointF(5.6, 14.4))
    seta.lineTo(QPointF(8.0, 16.4))
    painter.drawPath(seta)
    painter.end()
    return _guardar(chave, pix)


def icone_lupa(cor: str = "") -> QIcon:
    """Lupa: abre a busca dentro do corpo da resposta."""
    cor = cor or theme.DIM
    chave = f"lupa:{cor}"
    if chave in _cache:
        return _cache[chave]
    pix, painter = _tela(LADO, LADO)
    _caneta(painter, cor)
    painter.drawEllipse(QRectF(3.2, 3.2, 9.2, 9.2))
    painter.drawLine(QPointF(11.6, 11.6), QPointF(15.0, 15.0))
    painter.end()
    return _guardar(chave, pix)


def icone_terminal(cor: str = "") -> QIcon:
    """Prompt de terminal: copiar o curl completo, pronto pra colar no console.

    E o sinal de maior com o risco embaixo, que qualquer pessoa que abre terminal
    reconhece. Um icone de copia comum aqui ia se confundir com o de copiar o corpo,
    que fica dois botoes ao lado.
    """
    cor = cor or theme.DIM
    chave = f"terminal:{cor}"
    if chave in _cache:
        return _cache[chave]
    pix, painter = _tela(LADO, LADO)
    _caneta(painter, cor)
    painter.drawPolyline([QPointF(3.4, 4.6), QPointF(7.6, 8.4), QPointF(3.4, 12.2)])
    painter.drawLine(QPointF(9.2, 12.4), QPointF(14.6, 12.4))
    painter.end()
    return _guardar(chave, pix)


def icone_fechar(cor: str = "", lado: int = 14) -> QIcon:
    """X de apagar linha. O caractere multiplicacao mudava de desenho com a fonte."""
    cor = cor or theme.FAINT
    chave = f"fechar:{cor}:{lado}"
    if chave in _cache:
        return _cache[chave]
    pix, painter = _tela(lado, lado)
    _caneta(painter, cor, 1.5)
    recuo = lado * 0.29
    painter.drawLine(QPointF(recuo, recuo), QPointF(lado - recuo, lado - recuo))
    painter.drawLine(QPointF(lado - recuo, recuo), QPointF(recuo, lado - recuo))
    painter.end()
    return _guardar(chave, pix)


def icone_arquivo(cor: str = "") -> QIcon:
    """Folha com o canto dobrado. Par do folder_icon na listagem do SFTP."""
    cor = cor or theme.FAINT
    chave = f"arq:{cor}"
    if chave in _cache:
        return _cache[chave]

    pix, painter = _tela(LADO, LADO)
    dobra = 5.0
    esquerda, topo, direita, base = 3.6, 2.2, 14.4, 15.8

    contorno = QPainterPath()
    contorno.moveTo(QPointF(esquerda, topo))
    contorno.lineTo(QPointF(direita - dobra, topo))
    contorno.lineTo(QPointF(direita, topo + dobra))
    contorno.lineTo(QPointF(direita, base))
    contorno.lineTo(QPointF(esquerda, base))
    contorno.closeSubpath()

    tinta = QColor(cor)
    fundo = QColor(cor)
    fundo.setAlpha(28)
    caneta = QPen(tinta)
    caneta.setWidthF(1.2)
    caneta.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(caneta)
    painter.setBrush(fundo)
    painter.drawPath(contorno)

    # o canto dobrado e o que faz a silhueta ler como papel e nao como retangulo
    canto = QPainterPath()
    canto.moveTo(QPointF(direita - dobra, topo))
    canto.lineTo(QPointF(direita - dobra, topo + dobra))
    canto.lineTo(QPointF(direita, topo + dobra))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(canto)

    painter.end()
    return _guardar(chave, pix)


def icone_link(cor: str = "") -> QIcon:
    """Seta de atalho, pra distinguir link simbolico de arquivo de verdade."""
    cor = cor or theme.ACCENT
    chave = f"link:{cor}"
    if chave in _cache:
        return _cache[chave]

    pix, painter = _tela(LADO, LADO)
    _caneta(painter, cor, 1.4)
    painter.drawLine(QPointF(5.0, 13.0), QPointF(12.6, 5.4))
    ponta = QPainterPath()
    ponta.moveTo(QPointF(8.4, 4.6))
    ponta.lineTo(QPointF(13.4, 4.6))
    ponta.lineTo(QPointF(13.4, 9.6))
    painter.drawPath(ponta)
    painter.end()
    return _guardar(chave, pix)


def icone_subir(cor: str = "") -> QIcon:
    """Seta pra cima com um degrau, o gesto de voltar uma pasta."""
    cor = cor or theme.DIM
    chave = f"subir:{cor}"
    if chave in _cache:
        return _cache[chave]

    pix, painter = _tela(LADO, LADO)
    _caneta(painter, cor, 1.5)
    painter.drawLine(QPointF(9.0, 4.2), QPointF(9.0, 14.0))
    ponta = QPainterPath()
    ponta.moveTo(QPointF(5.0, 8.2))
    ponta.lineTo(QPointF(9.0, 4.2))
    ponta.lineTo(QPointF(13.0, 8.2))
    painter.drawPath(ponta)
    painter.end()
    return _guardar(chave, pix)


def icone_recarregar(cor: str = "") -> QIcon:
    """Arco quase fechado com ponta de seta: reler sem sair do lugar."""
    cor = cor or theme.DIM
    chave = f"recarregar:{cor}"
    if chave in _cache:
        return _cache[chave]

    pix, painter = _tela(LADO, LADO)
    _caneta(painter, cor, 1.5)
    caixa = QRectF(3.4, 3.4, 11.2, 11.2)
    # o vao no arco e o que separa "recarregar" de "carregando": circulo fechado le
    # como espera, arco aberto le como acao
    painter.drawArc(caixa, 60 * 16, 260 * 16)
    ponta = QPainterPath()
    ponta.moveTo(QPointF(9.2, 1.8))
    ponta.lineTo(QPointF(12.8, 4.6))
    ponta.lineTo(QPointF(9.0, 6.6))
    painter.drawPath(ponta)
    painter.end()
    return _guardar(chave, pix)


def icone_oculto(cor: str = "") -> QIcon:
    """Olho, pra ligar e desligar o que comeca com ponto."""
    cor = cor or theme.DIM
    chave = f"oculto:{cor}"
    if chave in _cache:
        return _cache[chave]

    pix, painter = _tela(LADO, LADO)
    _caneta(painter, cor, 1.4)
    olho = QPainterPath()
    olho.moveTo(QPointF(2.2, 9.0))
    olho.quadTo(QPointF(9.0, 2.6), QPointF(15.8, 9.0))
    olho.quadTo(QPointF(9.0, 15.4), QPointF(2.2, 9.0))
    painter.drawPath(olho)
    painter.drawEllipse(QPointF(9.0, 9.0), 2.4, 2.4)
    painter.end()
    return _guardar(chave, pix)


def icone_servidor(cor: str = "") -> QIcon:
    """Duas gavetas empilhadas com a luzinha acesa. O SFTP na lateral."""
    cor = cor or theme.DIM
    chave = f"servidor:{cor}"
    if chave in _cache:
        return _cache[chave]

    pix, painter = _tela(LADO, LADO)
    tinta = QColor(cor)
    fundo = QColor(cor)
    fundo.setAlpha(30)
    caneta = QPen(tinta)
    caneta.setWidthF(1.2)
    painter.setPen(caneta)
    painter.setBrush(fundo)
    painter.drawRoundedRect(QRectF(2.6, 3.2, 12.8, 5.0), 1.6, 1.6)
    painter.drawRoundedRect(QRectF(2.6, 9.8, 12.8, 5.0), 1.6, 1.6)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(tinta)
    painter.drawEllipse(QPointF(5.2, 5.7), 1.0, 1.0)
    painter.drawEllipse(QPointF(5.2, 12.3), 1.0, 1.0)
    painter.end()
    return _guardar(chave, pix)


def ponto_cor(cor: str, lado: int = 14, atual: bool = False) -> QIcon:
    """Circulo cheio na cor pedida. E a identidade visual do workspace.

    Antes essa marca era `border-left: 3px solid` no proprio botao. Borda colorida num
    controle e a linguagem de campo com foco, entao o seletor de workspace parecia uma
    caixa de texto acesa em vez de um seletor.

    Com `atual`, o ponto ganha um anel aberto em volta. E como o menu diz qual workspace
    esta aberto agora. Antes isso era `setChecked` numa acao que tambem tinha icone, e o
    Qt poe as duas coisas na mesma coluna: o visto de escolhido praticamente sumia atras
    do ponto, entao a lista inteira parecia igual.
    """
    chave = f"ponto:{cor}:{lado}:{atual}"
    if chave in _cache:
        return _cache[chave]

    pix, painter = _tela(lado, lado)
    painter.setPen(Qt.PenStyle.NoPen)
    # anel translucido em volta pra cor nao encostar direto no fundo e sumir nos tons
    # que ficam perto da superficie
    halo = QColor(cor)
    halo.setAlpha(60)
    painter.setBrush(halo)
    painter.drawEllipse(QRectF(0.5, 0.5, lado - 1.0, lado - 1.0))
    painter.setBrush(QColor(cor))
    recuo = lado * (0.34 if atual else 0.28)
    painter.drawEllipse(QRectF(recuo, recuo, lado - recuo * 2, lado - recuo * 2))

    if atual:
        # anel aberto e nitido, na cor cheia: e o que separa o aberto dos outros de
        # relance, sem depender de negrito nem de texto extra do lado
        painter.setBrush(Qt.BrushStyle.NoBrush)
        caneta = QPen(QColor(cor))
        caneta.setWidthF(max(1.2, lado * 0.11))
        painter.setPen(caneta)
        borda = lado * 0.10
        painter.drawEllipse(QRectF(borda, borda, lado - borda * 2, lado - borda * 2))
    painter.end()
    return _guardar(chave, pix)
