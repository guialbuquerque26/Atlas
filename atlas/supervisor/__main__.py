"""Linha de comando do supervisor de serviços.

    python -m atlas.supervisor iniciar            # sobe Ollama + API + interface
    python -m atlas.supervisor iniciar --baixar-modelos
    python -m atlas.supervisor iniciar api        # só um serviço
    python -m atlas.supervisor status
    python -m atlas.supervisor logs api
    python -m atlas.supervisor parar
"""

from __future__ import annotations

import argparse

from atlas.supervisor import gerenciador
from atlas.supervisor.definicoes import SERVICOS

NOMES = [s.nome for s in SERVICOS]


def _cmd_iniciar(args) -> int:
    return gerenciador.iniciar(
        args.servicos or None,
        baixar_ausentes=args.baixar_modelos,
        abrir_navegador=not args.sem_navegador,
    )


def _cmd_parar(args) -> int:
    return gerenciador.parar(args.servicos or None, incluir_externos=args.tudo)


def _cmd_status(_) -> int:
    return gerenciador.status()


def _cmd_reiniciar(args) -> int:
    gerenciador.parar(args.servicos or None)
    return gerenciador.iniciar(args.servicos or None, abrir_navegador=False)


def _cmd_logs(args) -> int:
    caminho = gerenciador.caminho_log(args.servico)
    if not caminho.exists():
        print(f"Sem log ainda para '{args.servico}': {caminho}")
        return 1
    linhas = caminho.read_text(encoding="utf-8", errors="replace").splitlines()
    print("\n".join(linhas[-args.linhas :]))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        prog="atlas.supervisor",
        description="Sobe e derruba todos os serviços do Atlas de uma vez.",
    )
    sub = p.add_subparsers(dest="comando", required=True)

    i = sub.add_parser("iniciar", help="sobe os serviços na ordem correta")
    i.add_argument("servicos", nargs="*", choices=NOMES, help="subconjunto opcional")
    i.add_argument(
        "--baixar-modelos",
        action="store_true",
        help="baixa no Ollama os modelos do .env que estiverem faltando",
    )
    i.add_argument(
        "--sem-navegador",
        action="store_true",
        help="não abre o navegador na interface depois que tudo subir",
    )
    i.set_defaults(fn=_cmd_iniciar)

    s = sub.add_parser("parar", help="derruba os serviços iniciados pelo Atlas")
    s.add_argument("servicos", nargs="*", choices=NOMES)
    s.add_argument(
        "--tudo",
        action="store_true",
        help="derruba também serviços externos adotados (Ollama já em execução)",
    )
    s.set_defaults(fn=_cmd_parar)

    r = sub.add_parser("reiniciar", help="para e sobe novamente")
    r.add_argument("servicos", nargs="*", choices=NOMES)
    r.set_defaults(fn=_cmd_reiniciar)

    sub.add_parser("status", help="mostra o estado de cada serviço").set_defaults(fn=_cmd_status)

    g = sub.add_parser("logs", help="mostra o fim do log de um serviço")
    g.add_argument("servico", choices=NOMES)
    g.add_argument("--linhas", type=int, default=40)
    g.set_defaults(fn=_cmd_logs)

    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
