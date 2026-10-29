"""API HTTP do Atlas (FastAPI).

Sobe com:  python -m atlas.api.server
Docs em:   http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from hmac import compare_digest
from pathlib import Path

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from atlas import __version__
from atlas.api.jobs import criar_job, obter_job
from atlas.config import settings
from atlas.core.admissao import SistemaOcupado
from atlas.core.orchestrator import Atlas
from atlas.llm import get_llm
from atlas.llm.ollama_provider import OllamaIndisponivel
from atlas.memory import Banco
from atlas.tools import registro


app = FastAPI(
    title="Atlas",
    version=__version__,
    description="IA multimodal local",
)

_origens = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origens,  # vazio = nenhuma origem externa (era "*")
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------- falhas previsíveis
@app.exception_handler(SistemaOcupado)
def _ocupado(_: Request, exc: SistemaOcupado) -> JSONResponse:
    """Saturado: recusa rápido em vez de engordar a fila da GPU."""
    return JSONResponse(
        status_code=503,
        content={"erro": str(exc), "tipo": "ocupado"},
        headers={"Retry-After": "5"},
    )


@app.exception_handler(OllamaIndisponivel)
def _sem_modelo(_: Request, exc: OllamaIndisponivel) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"erro": str(exc), "tipo": "modelo_indisponivel"},
        headers={"Retry-After": "15"},
    )


# ---------------------------------------------------------------- autenticação
def exigir_token(request: Request) -> None:
    """Protege as rotas que gastam GPU ou escrevem em disco.

    Sem `ATLAS_API_TOKEN` configurado a checagem some — o modo local segue
    funcionando sem fricção. Em produção, defina o token.
    """
    esperado = settings.api_token
    if not esperado:
        return
    recebido = request.headers.get("x-api-key") or ""
    autorizacao = request.headers.get("authorization") or ""
    if autorizacao.lower().startswith("bearer "):
        recebido = autorizacao[7:].strip()
    if not compare_digest(recebido, esperado):
        raise HTTPException(401, "Token ausente ou inválido.")


# Cache de sessões vivas. O histórico é durável no SQLite, então descartar a
# instância mais antiga é seguro — sem isso o dicionário cresce sem parar.
_sessoes: OrderedDict[str, Atlas] = OrderedDict()


def _atlas(sessao_id: str | None) -> Atlas:
    if sessao_id and sessao_id in _sessoes:
        _sessoes.move_to_end(sessao_id)
        return _sessoes[sessao_id]
    instancia = Atlas(sessao_id)
    _sessoes[instancia.sessao_id] = instancia
    while len(_sessoes) > settings.max_sessoes_memoria:
        _sessoes.popitem(last=False)  # descarta a menos usada
    return instancia


# ------------------------------------------------------------------- modelos
class PedidoChat(BaseModel):
    mensagem: str
    sessao_id: str | None = None
    anexos: list[str] = []
    forcar_busca: bool = False


# --------------------------------------------------------------------- rotas
@app.get("/health")
def health() -> dict:
    """Liveness: o processo está de pé. Sempre 200 se a API responde."""
    return {"status": "ok", "versao": __version__}


@app.get("/ready")
def ready() -> JSONResponse:
    """Readiness: dá para atender de verdade? (Ollama no ar e modelos presentes.)

    Separado do /health de propósito: um orquestrador deve parar de mandar
    tráfego quando o modelo cai, sem reiniciar o processo — que está saudável.
    """
    from atlas.core.admissao import vagas_livres

    llm = get_llm()
    disponivel = llm.disponivel()
    instalados = getattr(llm, "modelos_instalados", lambda: [])() if disponivel else []
    faltando = [
        m
        for m in (settings.text_model, settings.vision_model, settings.embed_model)
        if not any(i.split(":")[0] == m.split(":")[0] for i in instalados)
    ]
    pronto = disponivel and not faltando
    corpo = {
        "pronto": pronto,
        "provedor": llm.nome,
        "llm_disponivel": disponivel,
        "modelos_faltando": faltando,
        "vagas_de_inferencia": vagas_livres(),
        "modelo_texto": settings.text_model,
        "modelo_visao": settings.vision_model,
        "ferramentas": sorted(registro),
    }
    return JSONResponse(status_code=200 if pronto else 503, content=corpo)


@app.post("/upload", dependencies=[Depends(exigir_token)])
async def upload(arquivo: UploadFile = File(...)) -> dict:
    from atlas.core.types import Anexo

    # `Path(...).name` descarta qualquer diretório vindo do cliente (evita
    # escrita fora de uploads/); o uuid impede colisão entre usuários.
    nome = Path(arquivo.filename or "arquivo").name
    if Anexo.classificar(nome).value == "desconhecido":
        raise HTTPException(415, f"Tipo de arquivo não suportado: {nome}")

    destino = settings.uploads_dir / f"{uuid.uuid4().hex[:8]}_{nome}"
    teto = int(settings.upload_max_mb * 1024 * 1024)
    escrito = 0
    try:
        with destino.open("wb") as f:
            while pedaco := await arquivo.read(1024 * 1024):
                escrito += len(pedaco)
                if escrito > teto:
                    raise HTTPException(
                        413, f"Arquivo maior que o limite de {settings.upload_max_mb:.0f} MB"
                    )
                f.write(pedaco)
    except HTTPException:
        destino.unlink(missing_ok=True)  # não deixa lixo pela metade
        raise

    return {"caminho": str(destino), "tipo": Anexo.classificar(destino).value}


@app.post("/chat", dependencies=[Depends(exigir_token)])
def chat(pedido: PedidoChat) -> dict:
    atlas = _atlas(pedido.sessao_id)
    r = atlas.responder(pedido.mensagem, pedido.anexos, pedido.forcar_busca)
    return {
        "sessao_id": atlas.sessao_id,
        "resposta": r.texto,
        "fontes": r.fontes,
        "ferramentas": [
            {"nome": t.ferramenta, "sucesso": t.sucesso, "erro": t.erro}
            for t in r.ferramentas_usadas
        ],
        "modelo": r.modelo,
        "duracao_s": r.duracao_s,
    }


@app.post("/chat/stream", dependencies=[Depends(exigir_token)])
def chat_stream(pedido: PedidoChat) -> StreamingResponse:
    atlas = _atlas(pedido.sessao_id)
    fluxo = atlas.responder_stream(pedido.mensagem, pedido.anexos, pedido.forcar_busca)
    return StreamingResponse(fluxo, media_type="text/plain; charset=utf-8")


def _executar_analise(nome: str, caminho: Path, pergunta: str) -> dict:
    ferramenta = registro[nome]
    r = ferramenta(caminho, pergunta) if nome != "ler_documento" else ferramenta(caminho)
    return {"sucesso": r.sucesso, "resumo": r.resumo, "dados": r.dados, "erro": r.erro}


@app.post("/analisar", dependencies=[Depends(exigir_token)])
async def analisar(
    resposta: Response,
    arquivo: UploadFile = File(...),
    pergunta: str = Form(""),
    assincrono: bool | None = Form(None),
) -> dict:
    """Analisa um arquivo direto, sem passar pelo chat.

    Vídeo vira job por padrão: a análise leva minutos e seguraria a conexão
    até estourar o timeout do proxy. Imagem e documento seguem síncronos.
    """
    salvo = await upload(arquivo)
    caminho = Path(salvo["caminho"])
    ferramentas = {
        "imagem": "analisar_imagem",
        "video": "analisar_video",
        "documento": "ler_documento",
    }
    nome = ferramentas.get(salvo["tipo"])
    if nome is None:
        raise HTTPException(415, f"Tipo não suportado: {salvo['tipo']}")

    em_background = salvo["tipo"] == "video" if assincrono is None else assincrono
    if em_background:
        job = criar_job(_executar_analise, nome, caminho, pergunta)
        resposta.status_code = 202
        return {**job.como_dict(), "acompanhe_em": f"/jobs/{job.id}"}

    return _executar_analise(nome, caminho, pergunta)


@app.get("/jobs/{job_id}", dependencies=[Depends(exigir_token)])
def consultar_job(job_id: str) -> dict:
    job = obter_job(job_id)
    if job is None:
        raise HTTPException(404, f"Job não encontrado: {job_id}")
    return job.como_dict()


@app.get("/sessoes", dependencies=[Depends(exigir_token)])
def sessoes() -> list[dict]:
    return Banco().listar_sessoes()


@app.get("/sessoes/{sessao_id}", dependencies=[Depends(exigir_token)])
def historico(sessao_id: str) -> list[dict]:
    return [
        {"papel": m.papel, "conteudo": m.conteudo}
        for m in Banco().historico(sessao_id, limite=200)
    ]


@app.delete("/sessoes/{sessao_id}", dependencies=[Depends(exigir_token)])
def apagar(sessao_id: str) -> dict:
    Banco().apagar_sessao(sessao_id)
    _sessoes.pop(sessao_id, None)
    return {"apagada": sessao_id}


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    main()
