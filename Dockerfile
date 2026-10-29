# Imagem da API do Atlas. O Ollama roda em serviço separado (ver docker-compose),
# porque é ele quem precisa da GPU e tem ciclo de vida próprio.
FROM python:3.11-slim

# opencv precisa dessas libs mesmo na versão headless
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 libgl1 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependências primeiro: essa camada só reconstrói quando o requirements muda.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml .
COPY atlas ./atlas
RUN pip install --no-cache-dir -e . --no-deps

# Estado fica em volume: o container é descartável.
ENV ATLAS_DATA_DIR=/dados \
    ATLAS_API_HOST=0.0.0.0 \
    ATLAS_OLLAMA_HOST=http://ollama:11434 \
    PYTHONUNBUFFERED=1
RUN mkdir -p /dados

EXPOSE 8000

# /health é liveness (o processo responde). A prontidão real é /ready.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# Um worker de propósito: a GPU serializa a inferência, então mais workers não
# somam vazão e ainda quebrariam SQLite/ChromaDB (arquivos, single-writer).
CMD ["uvicorn", "atlas.api.server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
