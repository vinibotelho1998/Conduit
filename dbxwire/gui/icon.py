"""Icone do Dbx Wire, desenhado em codigo.

Conceito: a linha de pulso. Ela entra reta, dispara num pico, passa do ponto na volta e
se acalma de novo, que e exatamente o desenho de um request: sai, o servidor responde,
o tempo volta ao normal. A silhueta e unica, nao parece nenhum outro app da barra de
tarefas, e sobrevive a 16 pixels porque e um traco so.

Nenhum binario de arte no repo. O .ico multi resolucao e gerado a partir daqui.
"""

from __future__ import annotations

import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

ICO_SIZES = (16, 20, 24, 32, 48, 64, 128, 256)

# Grafite, no mesmo espirito do app: a pastilha e escura e o pulso e claro. Quem separa
# os dois e o contraste, e nao a matiz, entao o icone continua legivel a 16 pixels e
# tambem em tema claro, onde uma pastilha colorida virava mancha na barra de tarefas.
TILE_TOP = "#54545c"
TILE_BOTTOM = "#1b1b1e"
TRACO = "#0b0b0c"
BRILHO = "#fbfbfc"
EDGE = "#7b7b85"

# Pulso em coordenada normalizada. Versao cheia pros tamanhos grandes e versao com
# menos vertices pros pequenos, onde vertice demais vira borrao.
PULSO = [
    (0.130, 0.560), (0.315, 0.560), (0.395, 0.285),
    (0.500, 0.775), (0.590, 0.430), (0.670, 0.560), (0.870, 0.560),
]
PULSO_MIUDO = [
    (0.120, 0.560), (0.330, 0.560), (0.430, 0.255),
    (0.560, 0.790), (0.660, 0.560), (0.880, 0.560),
]


def _caminho_pulso(s: float, pontos) -> QPainterPath:
    caminho = QPainterPath()
    caminho.moveTo(QPointF(pontos[0][0] * s, pontos[0][1] * s))
    for x, y in pontos[1:]:
        caminho.lineTo(QPointF(x * s, y * s))
    return caminho


def render(size: int) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    s = float(size)

    gradiente = QLinearGradient(0, 0, s * 0.35, s)
    gradiente.setColorAt(0.0, QColor(TILE_TOP))
    gradiente.setColorAt(1.0, QColor(TILE_BOTTOM))
    painter.setBrush(gradiente)
    painter.setPen(Qt.PenStyle.NoPen)
    raio = s * 0.225
    painter.drawRoundedRect(QRectF(0, 0, s, s), raio, raio)

    if size >= 32:
        caneta = QPen(QColor(EDGE))
        caneta.setWidthF(max(1.0, s * 0.012))
        painter.setPen(caneta)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        recuo = caneta.widthF() / 2
        painter.drawRoundedRect(
            QRectF(recuo, recuo, s - 2 * recuo, s - 2 * recuo), raio - recuo, raio - recuo
        )

    pontos = PULSO if size >= 32 else PULSO_MIUDO
    espessura = s * (0.135 if size < 32 else 0.105)

    caneta = QPen(QColor(TRACO))
    caneta.setWidthF(espessura)
    caneta.setCapStyle(Qt.PenCapStyle.RoundCap)
    caneta.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(caneta)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(_caminho_pulso(s, pontos))

    # o ponto claro no fim e a resposta que chegou. So a partir de 32, senao gruda
    # no traco e vira mancha.
    if size >= 32:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(BRILHO))
        raio_ponto = espessura * 0.62
        fim_x, fim_y = pontos[-1]
        painter.drawEllipse(
            QPointF(fim_x * s, fim_y * s), raio_ponto, raio_ponto
        )

    painter.end()
    return pix


def build_icon() -> QIcon:
    icon = QIcon()
    for size in ICO_SIZES:
        icon.addPixmap(render(size))
    return icon


def _png_bytes(size: int) -> bytes:
    # o QByteArray precisa de nome proprio, senao o temporario e liberado e o Qt cai
    array = QByteArray()
    buffer = QBuffer(array)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    render(size).save(buffer, "PNG")
    buffer.close()
    return bytes(array)


def write_ico(path: str | Path) -> Path:
    """Monta um .ico multi tamanho na mao, com cada entrada em PNG.

    O Qt so grava um tamanho por arquivo, e atalho do Windows precisa das varias
    resolucoes pra ficar nitido na barra, no Desktop e no Alt+Tab.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    images = [(size, _png_bytes(size)) for size in ICO_SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)

    directory = b""
    payload = b""
    for size, data in images:
        dimension = 0 if size >= 256 else size
        directory += struct.pack(
            "<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(data), offset
        )
        payload += data
        offset += len(data)

    target.write_bytes(header + directory + payload)
    return target
