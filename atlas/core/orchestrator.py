"""Orquestrador: o cérebro que decide o que rodar antes de responder.

Fluxo de um turno:
    1. Classifica os anexos e roda o analisador de cada tipo.
    2. Decide se precisa buscar na internet (o próprio modelo decide).
    3. Consulta a memória vetorial por contexto relevante de conversas passadas.
    4. Monta o prompt com tudo isso e gera a resposta.
    5. Persiste histórico e indexa o que foi aprendido.
"""

from __future__ import annotations

import atexit
import json
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from loguru import logger

from atlas.config import settings
from atlas.core.admissao import SistemaOcupado
from atlas.core.prompts import DECIDIR_BUSCA, SISTEMA
from atlas.core.roteador import decidir_rapido
from atlas.core.types import Anexo, Mensagem, RespostaAtlas, ResultadoFerramenta, TipoAnexo
from atlas.documents import carregar_documento, dividir_em_trechos
from atlas.llm import get_llm
from atlas.memory import Banco
from atlas.search import buscar_na_web
from atlas.vision import analisar_imagem, analisar_video

ANALISADORES = {
    TipoAnexo.IMAGEM: analisar_imagem,
    TipoAnexo.VIDEO: analisar_video,
    TipoAnexo.DOCUMENTO: carregar_documento,
}


def _falhas_de_infra() -> tuple[type[Exception], ...]:
    """Erros de infraestrutura, não de conteúdo: devem virar 503, não texto.

    Importado tarde porque o provedor de LLM é escolhido em tempo de execução.
    """
    try:
        from atlas.llm.ollama_provider import OllamaIndisponivel

        return (OllamaIndisponivel, SistemaOcupado)
    except Exception:  # provedor alternativo sem essa exceção
        return (SistemaOcupado,)


FALHAS_DE_INFRA = _falhas_de_infra()


# Indexar gera embeddings, e o modelo de embeddings pode até estar descarregado
# (3,4s medidos). Nada disso muda a resposta que o usuário já leu, então sai do
# caminho crítico. Um worker só, para não concorrer no ChromaDB; o atexit
# garante que a fila termine antes do processo morrer.
_INDEXADOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="atlas-indexador")
atexit.register(_INDEXADOR.shutdown, wait=True)


def consumir_stream(
    fluxo: Iterator[str],
) -> Iterator[tuple[str, RespostaAtlas | None]]:
    """Percorre `responder_stream` entregando `(pedaço, None)` até o fim.

    No último passo emite `("", resposta)` com o resumo do turno, que o
    gerador devolve via `StopIteration`. Poupa quem consome de lidar com
    o protocolo do gerador na mão.
    """
    while True:
        try:
            yield next(fluxo), None
        except StopIteration as fim:
            yield "", fim.value
            return


class Atlas:
    def __init__(self, sessao_id: str | None = None, usar_memoria: bool = True) -> None:
        self.llm = get_llm()
        self.banco = Banco()
        self.sessao_id = sessao_id or self.banco.criar_sessao()
        self.usar_memoria = usar_memoria
        self._vetorial = None

    # --------------------------------------------------------------- memória
    @property
    def vetorial(self):
        """Carregado sob demanda: ChromaDB sobe devagar e nem todo turno precisa."""
        if self._vetorial is None and self.usar_memoria:
            try:
                from atlas.memory import MemoriaVetorial

                self._vetorial = MemoriaVetorial()
            except Exception as e:
                logger.warning(f"Memória vetorial desativada: {e}")
                self.usar_memoria = False
        return self._vetorial

    # ------------------------------------------------------------- ferramentas
    def processar_anexos(self, anexos: list[Anexo], pergunta: str) -> list[ResultadoFerramenta]:
        resultados = []
        for anexo in anexos:
            analisador = ANALISADORES.get(anexo.tipo)
            if analisador is None:
                resultados.append(
                    ResultadoFerramenta(
                        "anexo", False, "", erro=f"Tipo não suportado: {anexo.nome}"
                    )
                )
                continue
            logger.info(f"Analisando {anexo.tipo.value}: {anexo.nome}")
            if anexo.tipo is TipoAnexo.DOCUMENTO:
                resultados.append(analisador(anexo.caminho))
            else:
                resultados.append(analisador(anexo.caminho, pergunta or None))
        return resultados

    def precisa_buscar(self, pergunta: str, tem_anexos: bool = False) -> tuple[bool, str]:
        """Decide se vale ir à internet — pelo atalho, e só então pelo modelo."""
        if not settings.search_enabled:
            return False, ""

        # Com anexo, a pergunta é sobre o material entregue: buscar seria uma
        # geração inteira desperdiçada antes mesmo de começar a responder.
        if tem_anexos:
            return False, ""

        atalho = decidir_rapido(pergunta)
        if atalho is not None:
            return atalho, pergunta if atalho else ""

        try:
            bruto = self.llm.gerar(
                [Mensagem("user", DECIDIR_BUSCA.format(pergunta=pergunta))], temperature=0.0
            )
            limpo = bruto.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
            decisao = json.loads(limpo.strip())
            return bool(decisao.get("buscar")), decisao.get("consulta", "") or pergunta
        except FALHAS_DE_INFRA:
            # Modelo fora ou saturado: não adianta seguir para a geração e
            # gastar mais uma rodada de tentativas — o turno inteiro vai falhar.
            raise
        except Exception as e:
            logger.debug(f"Roteador de busca falhou, seguindo sem web: {e}")
            return False, ""

    # ---------------------------------------------------------------- contexto
    def montar_contexto(self, resultados: list[ResultadoFerramenta], pergunta: str) -> str:
        blocos = [r.como_contexto() for r in resultados]

        if self.usar_memoria and self.vetorial:
            lembrancas = self.vetorial.buscar(pergunta, k=settings.memoria_k)
            relevantes = [
                l for l in lembrancas
                if l["similaridade"] > settings.memoria_limiar_similaridade
            ]
            if relevantes:
                blocos.append(
                    "### [memória]\n"
                    + "\n---\n".join(l["texto"][: settings.memoria_max_chars] for l in relevantes)
                )
        return "\n\n".join(blocos)

    def _mensagens_do_turno(self, pergunta: str, contexto: str) -> list[Mensagem]:
        mensagens = [Mensagem("system", SISTEMA)]
        mensagens.extend(self.banco.historico(self.sessao_id, limite=10))
        if contexto:
            conteudo = f"CONTEXTO:\n{contexto}\n\nPERGUNTA: {pergunta}"
        else:
            conteudo = pergunta
        mensagens.append(Mensagem("user", conteudo))
        return mensagens

    # ------------------------------------------------------------------ turno
    def responder(
        self,
        pergunta: str,
        anexos: list[str | Path] | None = None,
        forcar_busca: bool = False,
    ) -> RespostaAtlas:
        inicio = time.perf_counter()
        resultados: list[ResultadoFerramenta] = []

        objetos = [Anexo(Path(a)) for a in (anexos or [])]
        if objetos:
            resultados.extend(self.processar_anexos(objetos, pergunta))

        buscar, consulta = (
            (True, pergunta)
            if forcar_busca
            else self.precisa_buscar(pergunta, tem_anexos=bool(objetos))
        )
        if buscar:
            logger.info(f"Buscando na web: {consulta}")
            resultados.append(buscar_na_web(consulta))

        contexto = self.montar_contexto(resultados, pergunta)
        mensagens = self._mensagens_do_turno(pergunta, contexto)

        try:
            texto = self.llm.gerar(mensagens)
        except FALHAS_DE_INFRA:
            # Indisponibilidade real sobe: quem chama (API) devolve 503. Engolir
            # aqui devolveria 200 com um texto de erro — mentira para o cliente.
            raise
        except Exception as e:
            texto = (
                f"Não consegui gerar a resposta: {e}\n\n"
                "Verifique se o Ollama está em execução (`ollama serve`) e se o modelo "
                f"`{settings.text_model}` foi baixado."
            )

        self._persistir(pergunta, texto, objetos, resultados)

        fontes = [f for r in resultados for f in r.fontes]
        return RespostaAtlas(
            texto=texto,
            ferramentas_usadas=resultados,
            fontes=fontes,
            modelo=settings.text_model,
            duracao_s=round(time.perf_counter() - inicio, 2),
        )

    def responder_stream(
        self, pergunta: str, anexos: list[str | Path] | None = None, forcar_busca: bool = False
    ) -> Iterator[str]:
        """Mesma lógica, emitindo a resposta token a token para a interface.

        Ao terminar, o gerador *retorna* o `RespostaAtlas` do turno — quem
        precisar das ferramentas e do tempo pega em `StopIteration.value`, ou
        pelo utilitário `consumir_stream`. Um `for` simples continua válido.
        """
        inicio = time.perf_counter()
        resultados: list[ResultadoFerramenta] = []
        objetos = [Anexo(Path(a)) for a in (anexos or [])]
        if objetos:
            resultados.extend(self.processar_anexos(objetos, pergunta))

        buscar, consulta = (
            (True, pergunta)
            if forcar_busca
            else self.precisa_buscar(pergunta, tem_anexos=bool(objetos))
        )
        if buscar:
            resultados.append(buscar_na_web(consulta))

        contexto = self.montar_contexto(resultados, pergunta)
        mensagens = self._mensagens_do_turno(pergunta, contexto)

        partes: list[str] = []
        try:
            for pedaco in self.llm.gerar_stream(mensagens):
                partes.append(pedaco)
                yield pedaco
        except FALHAS_DE_INFRA:
            raise  # nada foi emitido ainda: deixa virar 503 em vez de texto
        except Exception as e:
            erro = f"\n\n[Erro de geração: {e}]"
            partes.append(erro)
            yield erro

        texto = "".join(partes)
        self._persistir(pergunta, texto, objetos, resultados)

        return RespostaAtlas(
            texto=texto,
            ferramentas_usadas=resultados,
            fontes=[f for r in resultados for f in r.fontes],
            modelo=settings.text_model,
            duracao_s=round(time.perf_counter() - inicio, 2),
        )

    # -------------------------------------------------------------- persistência
    def _persistir(
        self,
        pergunta: str,
        resposta: str,
        anexos: list[Anexo],
        resultados: list[ResultadoFerramenta],
    ) -> None:
        self.banco.salvar_mensagem(
            self.sessao_id,
            Mensagem("user", pergunta),
            anexos=[a.nome for a in anexos],
            ferramentas=[r.ferramenta for r in resultados],
        )
        self.banco.salvar_mensagem(self.sessao_id, Mensagem("assistant", resposta))

        if not self.usar_memoria or not self.vetorial:
            return
        aproveitaveis = [r for r in resultados if r.sucesso]
        if aproveitaveis:
            _INDEXADOR.submit(self._indexar, aproveitaveis)

    def _indexar(self, resultados: list[ResultadoFerramenta]) -> None:
        """Roda fora do turno. Falhar aqui não pode derrubar a conversa."""
        for r in resultados:
            try:
                texto = r.dados.get("texto_completo") or r.resumo
                trechos = dividir_em_trechos(texto)
                if trechos:
                    self.vetorial.indexar(
                        trechos, {"ferramenta": r.ferramenta, "sessao": self.sessao_id}
                    )
            except Exception as e:
                logger.warning(f"Indexação de {r.ferramenta} falhou: {e}")

    def aguardar_indexacao(self, timeout: float = 30.0) -> None:
        """Bloqueia até a fila de indexação esvaziar. Para testes e scripts."""
        _INDEXADOR.submit(lambda: None).result(timeout=timeout)
