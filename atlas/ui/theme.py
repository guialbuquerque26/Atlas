"""Identidade visual do Atlas.

Direção: instrumento de navegação. Fundo de carta náutica noturna, retícula
de meridianos em hairline, latão para o acento e patina para o estado ativo.
A tipografia separa três papéis: Space Grotesk para títulos, Inter para
leitura, JetBrains Mono para coordenadas e metadados de ferramenta.
"""

import gradio as gr

TINTA = "#0B1420"       # fundo — azul de carta noturna
CASCO = "#131F2C"       # superfícies elevadas
MERIDIANO = "#22374B"   # linhas e bordas
BRUMA = "#7C93A8"       # texto secundário
LUZ = "#DCE7F0"         # texto primário
LATAO = "#D9A441"       # acento — bússola de latão
PATINA = "#4FB3A3"      # estado ativo / sucesso

CSS = f"""
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500&family=JetBrains+Mono:wght@400;500&display=swap');

:root {{
  --tinta: {TINTA}; --casco: {CASCO}; --meridiano: {MERIDIANO};
  --bruma: {BRUMA}; --luz: {LUZ}; --latao: {LATAO}; --patina: {PATINA};
}}

.gradio-container {{
  background: var(--tinta) !important;
  font-family: 'Inter', system-ui, sans-serif !important;
  max-width: 1180px !important;
}}

/* Retícula de meridianos: a assinatura da interface */
.gradio-container::before {{
  content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 0;
  background-image:
    linear-gradient(var(--meridiano) 1px, transparent 1px),
    linear-gradient(90deg, var(--meridiano) 1px, transparent 1px);
  background-size: 88px 88px;
  opacity: .16;
  mask-image: radial-gradient(ellipse at 50% 0%, #000 20%, transparent 78%);
}}
.gradio-container > * {{ position: relative; z-index: 1; }}

#cabecalho {{ border-bottom: 1px solid var(--meridiano); padding: 22px 4px 18px; }}
#cabecalho h1 {{
  font-family: 'Space Grotesk', sans-serif; font-weight: 700;
  font-size: 2.1rem; letter-spacing: -.02em; color: var(--luz);
  margin: 0 0 6px;
}}
#cabecalho h1 span {{ color: var(--latao); }}
#cabecalho p {{
  font-family: 'JetBrains Mono', monospace; font-size: .74rem;
  letter-spacing: .13em; text-transform: uppercase; color: var(--bruma); margin: 0;
}}

.prose, label, .gr-box, span, p {{ color: var(--luz) !important; }}
.gr-panel, .block, .form {{
  background: var(--casco) !important; border-color: var(--meridiano) !important;
}}

button.primary, .gr-button-primary {{
  background: var(--latao) !important; color: var(--tinta) !important;
  border: none !important; font-weight: 600 !important; letter-spacing: .01em;
}}
button.primary:hover {{ filter: brightness(1.08); }}

/* Log de bordo: onde as ferramentas relatam o que fizeram */
#log {{
  font-family: 'JetBrains Mono', monospace; font-size: .78rem;
  line-height: 1.65; color: var(--bruma);
  border-left: 2px solid var(--patina); padding-left: 14px;
}}
#log b {{ color: var(--patina); font-weight: 500; }}

footer, .footer {{ display: none !important; }}
"""

TEMA = gr.themes.Base(
    primary_hue=gr.themes.colors.amber,
    neutral_hue=gr.themes.colors.slate,
    font=[gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"],
    font_mono=[gr.themes.GoogleFont("JetBrains Mono"), "monospace"],
).set(
    body_background_fill=TINTA,
    body_text_color=LUZ,
    block_background_fill=CASCO,
    block_border_color=MERIDIANO,
    block_label_text_color=BRUMA,
    input_background_fill=TINTA,
    border_color_primary=MERIDIANO,
    button_primary_background_fill=LATAO,
    button_primary_text_color=TINTA,
)
