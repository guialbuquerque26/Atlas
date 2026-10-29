"""Testes da separação das descrições devolvidas em lote.

Rodam sem Ollama: exercitam só o parse da resposta do modelo de visão.
"""

from pathlib import Path

from atlas.vision.video import Frame, _separar_por_timestamp

LOTE = [
    Frame(0, 0.0, Path("f0.jpg")),
    Frame(50, 2.0, Path("f1.jpg")),
    Frame(150, 6.0, Path("f2.jpg")),
]


def teste_formato_esperado_casa_por_timestamp():
    resposta = (
        "[00:00] Fundo vermelho com o texto CENA 1.\n"
        "[00:02] Fundo verde com o texto CENA 2.\n"
        "[00:06] Fundo amarelo com o texto CENA 4.\n"
    )
    saida = _separar_por_timestamp(resposta, LOTE)
    assert len(saida) == 3
    assert saida[0].startswith("[00:00]") and "vermelho" in saida[0]
    assert saida[2].startswith("[00:06]") and "amarelo" in saida[2]


def teste_ordem_da_saida_segue_os_frames_e_nao_a_resposta():
    """Modelo devolveu fora de ordem; a linha do tempo tem que sair cronológica."""
    resposta = "[00:06] terceiro\n[00:00] primeiro\n[00:02] segundo\n"
    saida = _separar_por_timestamp(resposta, LOTE)
    assert [s.split("] ")[1] for s in saida] == ["primeiro", "segundo", "terceiro"]


def teste_tempos_inventados_caem_na_ordem_cronologica():
    """Formato certo, tempos que não batem: confia na ordem e reetiqueta."""
    resposta = "[01:11] alfa\n[02:22] beta\n[03:33] gama\n"
    saida = _separar_por_timestamp(resposta, LOTE)
    assert saida == ["[00:00] alfa", "[00:02] beta", "[00:06] gama"]


def teste_resposta_sem_formato_nao_perde_a_descricao():
    resposta = "O vídeo mostra três telas coloridas em sequência."
    saida = _separar_por_timestamp(resposta, LOTE)
    assert len(saida) == 1
    assert "três telas coloridas" in saida[0]


def teste_resposta_vazia_nao_gera_descricao():
    assert _separar_por_timestamp("   \n  ", LOTE) == []


def teste_frame_faltando_na_resposta_e_ignorado():
    """Modelo descreveu 2 dos 3 frames: devolve os 2, sem inventar o terceiro."""
    resposta = "[00:00] primeiro\n[00:06] terceiro\n"
    saida = _separar_por_timestamp(resposta, LOTE)
    assert len(saida) == 2
    assert saida[0].startswith("[00:00]") and saida[1].startswith("[00:06]")


def teste_variacoes_de_formatacao_do_modelo():
    """Sem colchetes, com hífen, com minutos de um dígito — tudo casa."""
    resposta = "0:00 - primeiro\n[00:02]: segundo\n00:06 – terceiro\n"
    saida = _separar_por_timestamp(resposta, LOTE)
    assert [s.split("] ")[1] for s in saida] == ["primeiro", "segundo", "terceiro"]
