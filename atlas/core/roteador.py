"""Decisão rápida sobre buscar na internet, antes de gastar o modelo.

Perguntar ao LLM se vale buscar custa uma geração inteira — medido entre 0,2s e
2,5s por turno, e numa conversa curta isso chegou a ser a maior parte do tempo
de resposta. A maioria das perguntas, porém, é óbvia: "bom dia" nunca precisa da
internet, "cotação do dólar hoje" sempre precisa.

Esta heurística resolve os casos óbvios em microssegundos e devolve `None`
quando está em dúvida — só aí o orquestrador consulta o modelo.
"""

from __future__ import annotations

import re
import unicodedata

# Sinais de que a resposta depende de informação que muda com o tempo.
SINAIS_DE_BUSCA = {
    # tempo
    "hoje", "agora", "atual", "atuais", "atualmente", "recente", "recentes",
    "recentemente", "ultima", "ultimo", "ultimas", "ultimos", "ontem", "amanha",
    "momento", "novidade", "novidades",
    # dinheiro e mercado
    "preco", "precos", "cotacao", "cotacoes", "valor", "dolar", "euro", "bitcoin",
    "acao", "acoes", "bolsa", "juros", "selic", "inflacao", "ipca", "cambio",
    # notícia e eventos
    "noticia", "noticias", "aconteceu", "eleicao", "eleicoes", "campeao",
    "venceu", "ganhou", "placar", "jogo", "resultado",
    # software
    "versao", "lancamento", "lancou", "release", "changelog",
    # clima
    "clima", "previsao", "temperatura",
}

# Sinais de que é conversa, raciocínio ou trabalho sobre o material já dado.
SINAIS_SEM_BUSCA = {
    # conversa
    "ola", "oi", "bom", "boa", "tudo", "obrigado", "obrigada", "valeu", "tchau",
    "desculpa", "por favor",
    # código
    "codigo", "funcao", "script", "python", "javascript", "sql", "regex",
    "classe", "variavel", "algoritmo", "bug", "compilar", "refatorar",
    "implementar", "depurar", "typescript", "html", "css",
    # raciocínio sobre o que já existe
    "resuma", "resumir", "traduza", "traduzir", "reescreva", "reescrever",
    "corrija", "corrigir", "calcule", "calcular", "revise", "revisar",
    # pedidos de explicação — conhecimento estável, o modelo já tem
    "explique", "explicar", "defina", "definir", "ensine", "ensinar",
    "conceito", "exemplo", "exemplos",
}

# Frases inteiras que nunca justificam uma busca.
CONVERSA_PURA = {
    "oi", "ola", "bom dia", "boa tarde", "boa noite", "tudo bem", "e ai",
    "obrigado", "obrigada", "valeu", "tchau", "ate logo", "ok", "certo",
}

_PALAVRA = re.compile(r"[a-z0-9]+")


def normalizar(texto: str) -> str:
    """Minúsculas sem acento — para 'preço' e 'preco' baterem no mesmo sinal."""
    sem_acento = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in sem_acento if not unicodedata.combining(c))


def decidir_rapido(pergunta: str) -> bool | None:
    """`True` busca, `False` não busca, `None` quando só o modelo pode decidir."""
    texto = normalizar(pergunta).strip()
    if not texto:
        return False

    if texto.rstrip("!?.,") in CONVERSA_PURA:
        return False

    palavras = set(_PALAVRA.findall(texto))

    # Sinal temporal ou de mercado vence: o custo de buscar à toa é menor que o
    # de responder com informação vencida.
    if palavras & SINAIS_DE_BUSCA:
        return True

    if palavras & SINAIS_SEM_BUSCA:
        return False

    return None
