"""Linha de comando do Atlas.

    python -m atlas.cli chat
    python -m atlas.cli analisar caminho/arquivo.jpg --pergunta "quantas pessoas?"
    python -m atlas.cli buscar "cotação do dólar hoje"
    python -m atlas.cli buscar-conhecimento "o que vimos naquele vídeo"
    python -m atlas.cli doutor
"""

from __future__ import annotations

import argparse
import sys

from atlas import __version__
from atlas.config import settings
from atlas.core.orchestrator import Atlas
from atlas.core.types import Anexo
from atlas.llm import get_llm
from atlas.search import buscar_na_web
from atlas.tools import registro


def cmd_doutor(_) -> int:
    """Diagnóstico do ambiente antes de perder tempo depurando."""
    llm = get_llm()
    print(f"Atlas {__version__}")
    print(f"  provedor .......... {llm.nome} @ {settings.ollama_host}")
    disponivel = llm.disponivel()
    print(f"  servidor .......... {'ok' if disponivel else 'INDISPONÍVEL'}")
    if not disponivel:
        print("\n  Inicie o Ollama com: ollama serve")
        return 1

    instalados = getattr(llm, "modelos_instalados", lambda: [])()
    for rotulo, modelo in (
        ("texto", settings.text_model),
        ("visão", settings.vision_model),
        ("embeddings", settings.embed_model),
    ):
        presente = any(m.split(":")[0] == modelo.split(":")[0] for m in instalados)
        marca = "ok" if presente else f"AUSENTE — rode: ollama pull {modelo}"
        print(f"  {rotulo:.<18} {modelo} [{marca}]")

    print(f"  ferramentas ....... {', '.join(sorted(registro))}")
    print(f"  dados ............. {settings.data_dir}")

    # Conhecimento é opcional: o Atlas funciona sem nada indexado.
    try:
        from atlas.memory import MemoriaVetorial

        trechos = MemoriaVetorial().total()
    except Exception:
        trechos = 0
    print(f"  conhecimento ...... {trechos} trecho(s) na memória")
    return 0


def cmd_chat(args) -> int:
    from atlas.core.orchestrator import FALHAS_DE_INFRA

    atlas = Atlas()
    print(f"Atlas {__version__} — sessão {atlas.sessao_id}. Ctrl+C para sair.\n")
    while True:
        try:
            pergunta = input("você › ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAté logo.")
            return 0
        if not pergunta:
            continue
        if pergunta in {"/sair", "/exit"}:
            return 0
        print("\natlas › ", end="", flush=True)
        try:
            for pedaco in atlas.responder_stream(pergunta, forcar_busca=args.buscar):
                print(pedaco, end="", flush=True)
        except FALHAS_DE_INFRA as e:
            print(f"[indisponível] {e}")
        print("\n")


def cmd_analisar(args) -> int:
    tipo = Anexo.classificar(args.caminho)
    ferramenta = {
        "imagem": "analisar_imagem",
        "video": "analisar_video",
        "documento": "ler_documento",
    }.get(tipo.value)
    if ferramenta is None:
        print(f"Tipo não suportado: {args.caminho}", file=sys.stderr)
        return 1

    fn = registro[ferramenta]
    r = fn(args.caminho) if ferramenta == "ler_documento" else fn(args.caminho, args.pergunta)
    print(r.resumo if r.sucesso else f"Falhou: {r.erro}", file=sys.stdout if r.sucesso else sys.stderr)
    return 0 if r.sucesso else 1


def cmd_buscar(args) -> int:
    r = buscar_na_web(args.consulta)
    print(r.resumo if r.sucesso else f"Falhou: {r.erro}")
    return 0 if r.sucesso else 1


def cmd_buscar_conhecimento(args) -> int:
    """Busca semântica na base de conhecimento indexada."""
    from atlas.documents import buscar_conhecimento

    r = buscar_conhecimento(args.consulta, fonte=args.fonte, k=args.k)
    print(r.resumo if r.sucesso else f"Falhou: {r.erro}")
    return 0 if r.sucesso else 1


def _saida_utf8() -> None:
    """No Windows o console vem em cp1252 e quebra em acento/símbolo. Força UTF-8."""
    for fluxo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(fluxo, "reconfigure", None)
        if reconfigurar:
            try:
                reconfigurar(encoding="utf-8")
            except Exception:
                pass


def main() -> int:
    _saida_utf8()
    p = argparse.ArgumentParser(prog="atlas", description="Atlas — IA multimodal local")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="comando", required=True)

    c = sub.add_parser("chat", help="conversa no terminal")
    c.add_argument("--buscar", action="store_true", help="forçar busca na internet")
    c.set_defaults(fn=cmd_chat)

    a = sub.add_parser("analisar", help="analisa imagem, vídeo ou documento")
    a.add_argument("caminho")
    a.add_argument("--pergunta", default=None)
    a.set_defaults(fn=cmd_analisar)

    b = sub.add_parser("buscar", help="pesquisa na internet")
    b.add_argument("consulta")
    b.set_defaults(fn=cmd_buscar)

    bc = sub.add_parser("buscar-conhecimento", help="busca na base de conhecimento indexada")
    bc.add_argument("consulta")
    bc.add_argument("--fonte", default=None, help="restringe a uma origem (metadado \"fonte\")")
    bc.add_argument("--k", type=int, default=5, help="número de trechos a devolver")
    bc.set_defaults(fn=cmd_buscar_conhecimento)

    d = sub.add_parser("doutor", help="diagnóstico do ambiente")
    d.set_defaults(fn=cmd_doutor)

    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
