"""Prompts de sistema. Separados do código para poderem ser ajustados sem risco."""

SISTEMA = """Você é o Atlas, um assistente de IA multimodal executado localmente.

Princípios:
- Responda em português do Brasil, com clareza e objetividade.
- Use o CONTEXTO fornecido (análises de imagem, vídeo, documentos e busca na web)
  como fonte primária. Ele foi produzido por ferramentas nesta mesma execução.
- Se o contexto não sustenta a resposta, diga o que falta em vez de inventar.
- Ao usar resultados de busca, cite a fonte pela URL entre parênteses.
- Não descreva seus mecanismos internos a menos que perguntem.
"""

DESCREVER_IMAGEM = """Descreva esta imagem com precisão e em português.
Cubra: cena geral, objetos principais, pessoas (quantidade, ação, vestuário — sem
identificar quem são), texto legível, cores dominantes e qualquer detalhe incomum.
Seja factual: não especule sobre o que não está visível."""

DESCREVER_FRAME = """Este é o frame de um vídeo no tempo {timestamp}.
Descreva em 1-3 frases o que acontece: objetos, pessoas, ação e ambiente."""

DESCREVER_FRAMES_LOTE = """As imagens a seguir são {quantidade} frames do mesmo vídeo,
em ordem cronológica, nos tempos: {timestamps}.

Descreva cada frame em 1-3 frases: objetos, pessoas, ação e ambiente.
Responda uma linha por frame, exatamente neste formato, sem texto adicional:
[mm:ss] descrição do frame

Use os tempos na ordem exata em que foram listados."""

RESUMIR_VIDEO = """Abaixo estão descrições de frames extraídos de um vídeo em ordem cronológica.
Escreva uma síntese em português cobrindo:
1. Do que se trata o vídeo.
2. Sequência de eventos ao longo do tempo.
3. Objetos e pessoas recorrentes.
4. Mudanças de cena relevantes.

DESCRIÇÕES:
{descricoes}"""

DECIDIR_BUSCA = """Decida se responder à pergunta abaixo exige buscar informação
atualizada na internet.

Responda APENAS com JSON, sem markdown e sem comentários:
{{"buscar": true|false, "consulta": "termos de busca ou string vazia"}}

Busque quando envolver: eventos recentes, preços, versões de software, pessoas em
cargos atuais, dados que mudam com o tempo, ou fatos que você não domina.
Não busque para: conversa casual, raciocínio, código, ou análise do material já anexado.

PERGUNTA: {pergunta}"""
