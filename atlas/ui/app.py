"""Interface do Atlas em Gradio.

Sobe com:  python -m atlas.ui.app
"""

from __future__ import annotations

import time
from pathlib import Path

import gradio as gr

from atlas import __version__
from atlas.config import settings
from atlas.core.orchestrator import FALHAS_DE_INFRA, Atlas, consumir_stream
from atlas.core.types import Anexo
from atlas.llm import get_llm
from atlas.ui.theme import CSS, TEMA

LOG_INICIAL = "<div id='log'>Aguardando a primeira mensagem.</div>"
LOG_GERANDO = "<div id='log'>Gerando a resposta…</div>"
INTERVALO_ATUALIZACAO_S = 0.05

ACEITOS = [
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif",
    ".mp4", ".avi", ".mov", ".mkv", ".webm",
    ".pdf", ".docx", ".txt", ".md", ".csv", ".xlsx", ".json",
]


def _status() -> str:
    llm = get_llm()
    ok = llm.disponivel()
    marca = "conectado" if ok else "offline"
    return (
        f"provedor {llm.nome} · {marca} · texto {settings.text_model} · "
        f"visão {settings.vision_model}"
    )


def _resumo_ferramentas(resposta) -> str:
    if resposta is None:
        return "<div id='log'>Turno encerrado sem resumo.</div>"

    linhas = []
    if resposta.ferramentas_usadas:
        for t in resposta.ferramentas_usadas:
            estado = "concluído" if t.sucesso else f"falhou — {t.erro}"
            linhas.append(f"<b>{t.ferramenta}</b> · {estado}")
        if resposta.fontes:
            linhas.append("<b>fontes</b> · " + " · ".join(resposta.fontes[:5]))
    else:
        linhas.append("Nenhuma ferramenta usada — resposta direta do modelo.")
    linhas.append(f"<b>tempo</b> · {resposta.duracao_s}s")
    return "<div id='log'>" + "<br>".join(linhas) + "</div>"


def construir() -> gr.Blocks:
    # A partir do Gradio 6, tema e CSS são passados no launch(), não no Blocks().
    with gr.Blocks(title="Atlas", fill_height=True) as ui:
        sessao = gr.State(None)

        gr.HTML(
            f"""
            <div id="cabecalho">
              <h1>Atlas<span>.</span></h1>
              <p>IA multimodal local · v{__version__} · {_status()}</p>
            </div>
            """
        )

        with gr.Row():
            with gr.Column(scale=3):
                conversa = gr.Chatbot(
                    label="Conversa",
                    height=520,
                    avatar_images=(None, None),
                )
                entrada = gr.Textbox(
                    label="Mensagem",
                    placeholder="Pergunte, ou anexe uma imagem, vídeo ou documento e peça a análise.",
                    lines=3,
                )
                with gr.Row():
                    enviar = gr.Button("Enviar", variant="primary", scale=3)
                    limpar = gr.Button("Nova conversa", scale=1)

            with gr.Column(scale=1):
                arquivos = gr.File(
                    label="Anexos",
                    file_count="multiple",
                    file_types=ACEITOS,
                    height=180,
                )
                buscar = gr.Checkbox(label="Forçar busca na internet", value=False)
                gr.Markdown("### Log de bordo")
                log = gr.HTML(LOG_INICIAL)

        def responder(mensagem, historico, caminhos, forcar, sessao_id):
            """Gerador: a resposta aparece token a token, em vez de tudo no fim."""
            if not (mensagem or "").strip() and not caminhos:
                yield historico, "", None, LOG_INICIAL, sessao_id
                return

            atlas = Atlas(sessao_id)
            anexos = [Path(a) for a in (caminhos or [])]

            rotulo = mensagem
            if anexos:
                itens = ", ".join(f"{a.name} ({Anexo(a).tipo.value})" for a in anexos)
                rotulo = f"{mensagem}\n\n📎 {itens}" if mensagem else f"📎 {itens}"

            historico = (historico or []) + [{"role": "user", "content": rotulo}]
            historico.append({"role": "assistant", "content": ""})

            trabalho = "analisando o material" if anexos else "pensando"
            yield historico, "", None, f"<div id='log'>Atlas {trabalho}…</div>", atlas.sessao_id

            fluxo = atlas.responder_stream(
                mensagem or "Analise o material anexado.", anexos, forcar
            )
            ultimo_envio = 0.0
            resposta = None
            try:
                for pedaco, final in consumir_stream(fluxo):
                    if final is not None:
                        resposta = final
                        break
                    historico[-1]["content"] += pedaco
                    # Emitir a cada token afoga o Gradio; agrupa por janela de tempo.
                    agora = time.monotonic()
                    if agora - ultimo_envio >= INTERVALO_ATUALIZACAO_S:
                        ultimo_envio = agora
                        yield historico, "", None, LOG_GERANDO, atlas.sessao_id
            except FALHAS_DE_INFRA as e:
                historico[-1]["content"] = f"⚠️ Serviço indisponível no momento.\n\n{e}"
                yield historico, "", None, (
                    "<div id='log'>Modelo indisponível — tente novamente em instantes.</div>"
                ), atlas.sessao_id
                return

            yield historico, "", None, _resumo_ferramentas(resposta), atlas.sessao_id

        saidas = [conversa, entrada, arquivos, log, sessao]
        entradas = [entrada, conversa, arquivos, buscar, sessao]
        enviar.click(responder, entradas, saidas)
        entrada.submit(responder, entradas, saidas)
        limpar.click(
            lambda: ([], "", None, "<div id='log'>Nova sessão iniciada.</div>", None),
            outputs=saidas,
        )

    return ui


def main() -> None:
    construir().launch(
        server_port=settings.ui_port,
        inbrowser=settings.ui_abrir_navegador,
        theme=TEMA,
        css=CSS,
    )


if __name__ == "__main__":
    main()
