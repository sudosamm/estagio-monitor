"""Textos e marca que vêm da escola ou da rede (nada de SEDUC, SICE, CEPAE ou Ceará fixo no código).

Com a escola atual cadastrada na rede SEDUC/CE (migration 0048), tudo continua aparecendo igual a antes."""
from django.conf import settings

from .escopo import TODAS, escola_corrente

BRASAO_PADRAO = "img/brasao-ceara-seduc.png"


def _escola():
    escola = escola_corrente(obrigatoria=False)
    return None if escola is None or escola is TODAS else escola


def sistema_oficial():
    """Nome do sistema oficial da rede da escola (ex.: "SICE"); sem rede, "sistema oficial"."""
    escola = _escola()
    return escola.sistema_oficial if escola else "sistema oficial"


def nome_instituicao():
    escola = _escola()
    return escola.nome_instituicao if escola else settings.NOME_INSTITUICAO


def brasao_estatico():
    """Brasão padrão da rede (arquivo em static/), usado quando a escola não enviou o dela. Vazio = nenhum."""
    escola = _escola()
    if escola is None:
        return ""
    if escola.rede_id:
        return escola.rede.brasao_estatico
    return ""


def cabecalho_padrao():
    escola = _escola()
    if escola is None:
        return ""
    return escola.cabecalho_folha or (escola.rede.cabecalho_folha if escola.rede_id else "")
