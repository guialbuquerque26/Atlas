"""Análise de vídeo por amostragem de frames-chave.

Estratégia: em vez de olhar todos os frames (caro e redundante), detectamos
mudanças de cena por diferença de histograma, escolhemos até N frames
representativos, descrevemos cada um com o modelo multimodal e pedimos ao
modelo de texto uma síntese cronológica.
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
from loguru import logger

from atlas.config import settings
from atlas.core.prompts import DESCREVER_FRAME, DESCREVER_FRAMES_LOTE, RESUMIR_VIDEO
from atlas.core.types import Mensagem, ResultadoFerramenta
from atlas.llm import get_llm

FERRAMENTA = "analise_de_video"
LINHA_DESCRITA = re.compile(r"^\s*\[?(\d{1,2}:\d{2})\]?\s*[-–:]?\s*(.+)$")


@dataclass
class Frame:
    indice: int
    segundos: float
    caminho: Path

    @property
    def timestamp(self) -> str:
        m, s = divmod(int(self.segundos), 60)
        return f"{m:02d}:{s:02d}"


def _metadados(cap: cv2.VideoCapture) -> dict:
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    return {
        "fps": round(fps, 2),
        "total_frames": total,
        "duracao_s": round(total / fps, 2) if fps else 0.0,
        "largura": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "altura": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    }


def extrair_frames_chave(
    caminho: Path, max_frames: int | None = None, limiar: float | None = None
) -> tuple[list[Frame], dict]:
    """Retorna frames representativos salvos em disco + metadados do vídeo."""
    max_frames = max_frames or settings.video_max_frames
    limiar = limiar if limiar is not None else settings.video_scene_threshold

    cap = cv2.VideoCapture(str(caminho))
    if not cap.isOpened():
        raise RuntimeError(f"Não foi possível abrir o vídeo: {caminho}")

    meta = _metadados(cap)
    fps = meta["fps"] or 25.0
    # amostra ~4 candidatos por segundo de conteúdo, com piso e teto sensatos
    passo = max(1, meta["total_frames"] // max(1, max_frames * 8))

    destino = Path(tempfile.mkdtemp(prefix="atlas_frames_"))
    candidatos: list[tuple[int, float, Any]] = []
    hist_ant = None
    i = 0

    while True:
        ok, quadro = cap.read()
        if not ok:
            break
        if i % passo == 0:
            hist = cv2.calcHist([cv2.cvtColor(quadro, cv2.COLOR_BGR2GRAY)], [0], None, [64], [0, 256])
            cv2.normalize(hist, hist)
            if hist_ant is None:
                candidatos.append((i, i / fps, quadro))
            else:
                dif = cv2.compareHist(hist_ant, hist, cv2.HISTCMP_CHISQR)
                if dif > limiar:
                    candidatos.append((i, i / fps, quadro))
            hist_ant = hist
        i += 1
    cap.release()

    # garante cobertura mesmo em vídeos estáticos
    if len(candidatos) < 2 and meta["total_frames"] > 0:
        candidatos = _amostra_uniforme(caminho, max_frames, fps)

    escolhidos = _reduzir(candidatos, max_frames)
    frames: list[Frame] = []
    for idx, seg, quadro in escolhidos:
        alvo = destino / f"frame_{idx:07d}.jpg"
        cv2.imwrite(str(alvo), quadro, [cv2.IMWRITE_JPEG_QUALITY, 85])
        frames.append(Frame(idx, seg, alvo))
    return frames, meta


def _amostra_uniforme(caminho: Path, quantidade: int, fps: float) -> list[tuple[int, float, Any]]:
    cap = cv2.VideoCapture(str(caminho))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    marcos = [int(total * k / (quantidade + 1)) for k in range(1, quantidade + 1)]
    saida = []
    for m in marcos:
        cap.set(cv2.CAP_PROP_POS_FRAMES, m)
        ok, quadro = cap.read()
        if ok:
            saida.append((m, m / fps, quadro))
    cap.release()
    return saida


def _reduzir(itens: list, limite: int) -> list:
    if len(itens) <= limite:
        return itens
    passo = len(itens) / limite
    return [itens[int(k * passo)] for k in range(limite)]


def _separar_por_timestamp(resposta: str, lote: list[Frame]) -> list[str]:
    """Divide a resposta do lote em uma descrição por frame.

    O modelo foi instruído a emitir `[mm:ss] descrição` por linha. Quando ele
    foge do formato, devolvemos o texto inteiro atribuído ao primeiro frame —
    perder a granularidade é melhor que perder a descrição.
    """
    por_tempo: dict[str, list[str]] = {}
    ordem: list[str] = []
    for linha in resposta.splitlines():
        casado = LINHA_DESCRITA.match(linha)
        if not casado:
            continue
        tempo, texto = casado.group(1), casado.group(2).strip()
        if not texto:
            continue
        tempo = f"{int(tempo.split(':')[0]):02d}:{tempo.split(':')[1]}"
        if tempo not in por_tempo:
            por_tempo[tempo] = []
            ordem.append(tempo)
        por_tempo[tempo].append(texto)

    esperados = [f.timestamp for f in lote]
    if set(esperados) & set(ordem):
        # Casa pelo timestamp quando o modelo respeitou os tempos informados.
        return [
            f"[{t}] {' '.join(por_tempo[t])}" for t in esperados if t in por_tempo
        ]
    if len(ordem) == len(lote):
        # Formato certo, tempos inventados: confia na ordem cronológica.
        return [f"[{f.timestamp}] {' '.join(por_tempo[t])}" for f, t in zip(lote, ordem, strict=True)]

    limpo = resposta.strip()
    return [f"[{lote[0].timestamp}] {limpo}"] if limpo else []


def _descrever_frames(frames: list[Frame], tamanho_lote: int) -> list[str]:
    """Descreve os frames agrupados em lotes.

    Uma chamada por frame paga o prompt e a latência de ida e volta N vezes.
    Enviando vários frames na mesma mensagem, o modelo multimodal os descreve
    de uma vez — medido em cerca de metade do tempo. Paralelizar as chamadas
    não ajuda: a GPU já está saturada por uma só.
    """
    llm = get_llm()
    descricoes: list[str] = []

    for inicio in range(0, len(frames), tamanho_lote):
        lote = frames[inicio : inicio + tamanho_lote]
        try:
            if len(lote) == 1:
                unico = lote[0]
                texto = llm.ver_imagem(
                    DESCREVER_FRAME.format(timestamp=unico.timestamp), [unico.caminho]
                )
                descricoes.append(f"[{unico.timestamp}] {texto.strip()}")
            else:
                prompt = DESCREVER_FRAMES_LOTE.format(
                    quantidade=len(lote),
                    timestamps=", ".join(f.timestamp for f in lote),
                )
                resposta = llm.ver_imagem(prompt, [f.caminho for f in lote])
                descricoes.extend(_separar_por_timestamp(resposta, lote))
        except Exception as e:
            logger.warning(
                f"Lote {lote[0].timestamp}–{lote[-1].timestamp} falhou: {e}"
            )

    return descricoes


def analisar_video(caminho: str | Path, pergunta: str | None = None) -> ResultadoFerramenta:
    caminho = Path(caminho)
    if not caminho.exists():
        return ResultadoFerramenta(FERRAMENTA, False, "", erro=f"Arquivo não encontrado: {caminho}")

    try:
        frames, meta = extrair_frames_chave(caminho)
    except Exception as e:
        return ResultadoFerramenta(FERRAMENTA, False, "", erro=f"Falha ao ler o vídeo: {e}")

    if not frames:
        return ResultadoFerramenta(FERRAMENTA, False, "", dados=meta, erro="Nenhum frame extraído.")

    descricoes = _descrever_frames(frames, settings.video_lote_frames)

    if not descricoes:
        return ResultadoFerramenta(
            FERRAMENTA, False, "", dados=meta, erro="O modelo de visão não respondeu a nenhum frame."
        )

    linha_do_tempo = "\n".join(descricoes)
    if pergunta:
        alvo = f"{pergunta}\n\nDescrições dos frames:\n{linha_do_tempo}"
    else:
        alvo = RESUMIR_VIDEO.format(descricoes=linha_do_tempo)

    try:
        sintese = get_llm().gerar([Mensagem("user", alvo)])
    except Exception as e:
        sintese = "Síntese indisponível (" + str(e) + "). Descrições por frame abaixo."

    meta.update({"frames_analisados": len(descricoes), "descricoes": descricoes})
    resumo = (
        f"Vídeo `{caminho.name}` — {meta['duracao_s']}s, {meta['largura']}x{meta['altura']}, "
        f"{len(descricoes)} frames-chave analisados.\n\n{sintese}\n\n"
        "Linha do tempo:\n" + linha_do_tempo
    )
    return ResultadoFerramenta(FERRAMENTA, True, resumo, dados=meta)
