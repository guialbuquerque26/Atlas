# Atlas

Sistema próprio de IA multimodal, executado localmente sobre modelos abertos.
Lê imagens, vídeos, documentos e a internet, e responde em linguagem natural
com o que aprendeu no caminho.

Nada de chave de API. Nada de nuvem. Os pesos rodam na sua máquina.

---

## O que já está de pé

| Capacidade | Módulo | Como funciona |
|---|---|---|
| Análise de imagens | `atlas/vision/image.py` | Metadados objetivos (dimensão, paleta) + leitura semântica pelo modelo multimodal |
| Análise de vídeos | `atlas/vision/video.py` | Detecção de cena por histograma → frames-chave → descrição de cada um → síntese cronológica |
| Chat em linguagem natural | `atlas/core/orchestrator.py` | Histórico, contexto de ferramentas e streaming token a token |
| Documentos | `atlas/documents/loader.py` | PDF, DOCX, XLSX, CSV, HTML, JSON, TXT, Markdown |
| Busca na internet | `atlas/search/web.py` | DuckDuckGo + extração do texto limpo das páginas |
| Memória | `atlas/memory/` | SQLite para histórico, ChromaDB para busca semântica |
| Interface | `atlas/ui/app.py` | Gradio, com anexos e log de ferramentas |
| API | `atlas/api/server.py` | FastAPI, com `/chat`, `/analisar`, `/upload` |
| Terminal | `atlas/cli.py` | `chat`, `analisar`, `buscar`, `buscar-conhecimento`, `doutor` |
| Supervisor | `atlas/supervisor/` | Sobe Ollama, API e interface de uma vez, na ordem certa |

---

## Estrutura

```
Atlas/
├── atlas/                  pacote principal
│   ├── api/                API REST (FastAPI)
│   ├── core/               orquestrador, tipos e prompts
│   ├── documents/          leitura de PDF, DOCX, XLSX, CSV, HTML…
│   ├── llm/                provedores (Ollama, HuggingFace)
│   ├── memory/             SQLite (histórico) e ChromaDB (semântica)
│   ├── search/             busca na internet
│   ├── supervisor/         sobe e derruba os processos de uma vez
│   ├── tools/              registro de ferramentas
│   ├── ui/                 interface Gradio
│   ├── vision/             imagem e vídeo
│   ├── cli.py              linha de comando
│   └── config.py           configuração central (lê o .env)
├── app.py                  ponto de entrada: sobe e supervisiona tudo
├── data/                   estado em disco (ignorado pelo git)
│   ├── db/                 SQLite + ChromaDB
│   ├── logs/               um log por serviço
│   ├── run/                PIDs dos processos em execução
│   └── uploads/            arquivos enviados pela API e pela interface
├── scripts/                instalar, iniciar, parar, status, testar
├── testes/                 testes de fundação (sem Ollama, sem internet)
├── .env                    configuração local (criada a partir do exemplo)
├── pyproject.toml          empacotamento e configuração do pytest
└── requirements.txt
```

---

## Instalação

Pré-requisitos: **Python 3.11+** e **[Ollama](https://ollama.com/download)**.

```powershell
git clone https://github.com/guialbuquerque26/Atlas.git
cd Atlas
powershell -ExecutionPolicy Bypass -File scripts\instalar.ps1
```

O script cria o `.venv`, instala as dependências, gera o `.env`, baixa os três
modelos e roda os testes. Se preferir na mão:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e . --no-deps          # torna "atlas" importável de qualquer pasta
copy .env.example .env

ollama pull qwen2.5:7b-instruct   # raciocínio e texto
ollama pull qwen2.5vl:7b          # visão (imagens e frames)
ollama pull nomic-embed-text      # embeddings para a memória
```

Os modelos somam cerca de 11 GB. Sem eles os serviços sobem normalmente, mas o
Atlas não consegue responder — `.\scripts\status.ps1` acusa quais faltam.

---

## Subir tudo de uma vez

`app.py` é o ponto de entrada da aplicação. Ele levanta o conjunto inteiro —
servidor de modelos, API e interface — na ordem certa, esperando cada um
responder antes de seguir para o próximo, e **continua supervisionando**:

```powershell
python app.py
```

Como controller, ele fica em primeiro plano vigiando a saúde de cada serviço.
Se algum cair, recoloca de pé (até 3 tentativas, depois avisa e para de
insistir). No `Ctrl+C`, derruba na ordem inversa o que ele mesmo subiu — um
Ollama que já rodava antes é preservado.

| Comando | O que faz |
|---|---|
| `python app.py` | Sobe tudo e supervisiona |
| `python app.py --baixar-modelos` | Idem, baixando antes os modelos que faltarem |
| `python app.py --sem-navegador` | Idem, sem abrir o navegador |
| `python app.py status` | Estado de cada serviço, portas, PIDs e modelos |
| `python app.py parar` | Derruba o que o Atlas subiu |
| `python app.py logs api --linhas 60` | Fim do log de um serviço |

Alternativa em PowerShell (sobe e sai, sem supervisão):

```powershell
.\scripts\iniciar.ps1
```

```
Atlas — subindo 3 serviço(s)
------------------------------------------------------------
  [ok]      ollama     http://127.0.0.1:11434 (pid 21840)
  [ok]      api        http://127.0.0.1:8000 (pid 9312)
  [ok]      interface  http://127.0.0.1:7860 (pid 15104)
------------------------------------------------------------
  Interface .... http://127.0.0.1:7860
  API docs ..... http://127.0.0.1:8000/docs
```

| Comando | O que faz |
|---|---|
| `.\scripts\iniciar.ps1` | Sobe Ollama, API e interface |
| `.\scripts\iniciar.ps1 -BaixarModelos` | Idem, baixando antes os modelos do `.env` que faltarem |
| `.\scripts\status.ps1` | Estado de cada serviço, portas, PIDs e modelos |
| `.\scripts\parar.ps1` | Derruba o que o Atlas subiu |
| `.\scripts\parar.ps1 -Tudo` | Derruba também o Ollama que já rodava antes |

Direto pelo Python, com controle fino:

```powershell
python -m atlas.supervisor iniciar            # tudo
python -m atlas.supervisor iniciar api        # só um serviço
python -m atlas.supervisor reiniciar interface
python -m atlas.supervisor logs api --linhas 60
python -m atlas.supervisor status
python -m atlas.supervisor parar
```

Três decisões que evitam dor de cabeça:

- **Ordem com healthcheck** — API e interface só sobem depois que o Ollama
  responde. Nada de erro silencioso porque o servidor de modelos ainda subia.
- **Adoção** — se o Ollama já estava rodando (serviço do Windows, outro
  terminal), ele é reaproveitado e o `parar` não o derruba.
- **Rastreio** — cada processo grava o PID em `data/run/` e o log em
  `data/logs/`, então `status` e `parar` funcionam de qualquer terminal novo.

---

## Uso

```powershell
.\scripts\status.ps1                                # diagnóstico do ambiente
python -m atlas.cli chat                            # chat no terminal
python -m atlas.cli analisar foto.jpg --pergunta "quantas pessoas aparecem?"
python -m atlas.cli analisar reuniao.mp4
python -m atlas.cli buscar "preço do minério de ferro hoje"
python -m atlas.cli buscar-conhecimento "o que apareceu no vídeo da reunião"
```

Tudo o que o Atlas analisa (imagens, vídeos, documentos e buscas) é indexado na
memória vetorial em segundo plano, e volta como contexto em conversas futuras.

Para rodar um serviço isolado em primeiro plano (útil ao depurar):

```powershell
.\scripts\ui.ps1                                    # interface web  → :7860
.\scripts\api.ps1                                   # API REST       → :8000/docs
```

Em Python:

```python
from atlas.core.orchestrator import Atlas

atlas = Atlas()
r = atlas.responder("O que está acontecendo neste vídeo?", anexos=["clipe.mp4"])
print(r.texto, r.fontes, r.duracao_s)
```

---

## Escolha do modelo

O `.env` define tudo. A família Qwen2.5 é o padrão porque cobre texto e visão
com a mesma licença aberta e roda bem em GPU de consumo, mas trocar é uma linha:

| VRAM | Texto | Visão |
|---|---|---|
| 6–8 GB | `qwen2.5:3b-instruct` | `qwen2.5vl:3b` |
| 10–12 GB | `qwen2.5:7b-instruct` | `qwen2.5vl:7b` |
| 24 GB+ | `qwen2.5:14b-instruct` | `qwen2.5vl:32b` |
| Só CPU | `llama3.2:3b` | `moondream` |

Mistral e Llama funcionam sem alteração de código — mude `ATLAS_TEXT_MODEL`.

---

## Arquitetura

```
      Supervisor (atlas/supervisor)  ── sobe e derruba tudo, na ordem certa
            │
Interface (Gradio · FastAPI · CLI)
            │
      Orquestrador  ── decide o que rodar, monta o contexto, responde
            │
   ┌────────┼────────┬──────────┬─────────┐
 Visão  Documentos  Busca    Memória   Provedor LLM
 imagem   PDF/DOCX  DuckDuck  SQLite    Ollama
 vídeo    XLSX/CSV  trafila.  Chroma    HuggingFace
```

Quatro costuras deliberadas, para que o sistema cresça sem reescrita:

1. **`ProvedorLLM`** (`atlas/llm/base.py`) — quatro métodos. Implemente-os e
   você trocou Ollama por vLLM, llama.cpp ou Transformers sem tocar em mais nada.
2. **`ResultadoFerramenta`** (`atlas/core/types.py`) — o formato único de saída
   de qualquer analisador. Um módulo novo de áudio só precisa devolver isso.
3. **`@registrar`** (`atlas/tools/registry.py`) — decore uma função e ela vira
   ferramenta para o orquestrador, para a API e para function calling.
4. **`Servico`** (`atlas/supervisor/definicoes.py`) — declare nome, comando, porta
   e healthcheck, e o supervisor passa a subir, monitorar e derrubar o processo
   novo junto com os demais. Nenhuma linha do gerenciador precisa mudar.

---

## Próximos passos naturais

- **Áudio**: `faster-whisper` para transcrição; o vídeo passa a ter trilha, não só imagem.
- **Detecção de objetos**: `ultralytics` (YOLO) para contagem e rastreamento por frame,
  complementando a descrição semântica com números.
- **OCR**: `paddleocr` ou `tesseract` para PDFs digitalizados.
- **Function calling real**: o registro já emite o schema; falta o laço de
  chamada no orquestrador para o modelo escolher a ferramenta sozinho.
- **RAG completo**: reranking dos trechos recuperados antes de montar o prompt.

---

## Modelos e licenças

Os modelos têm licenças próprias — Qwen2.5 (Apache 2.0),
Llama 3.x (Llama Community License), Mistral (Apache 2.0). Verifique antes de
uso comercial.
