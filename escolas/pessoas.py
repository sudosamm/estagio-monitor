"""Pessoas da escola atual. As contas são globais (um login por pessoa), então ``Usuario`` não tem gerenciador com
escopo: as listas, buscas e escolhas de pessoas passam por ``na_escola`` (vínculo ativo com a escola em uso)."""
from django.db.models import Q

from .escopo import ESCOLA_ATUAL, TODAS, EscolaDaConsulta


def _vinculados(escola=None, papel=None):
    from .models import VinculoEscola

    qs = VinculoEscola.objects.filter(escola=escola or EscolaDaConsulta(), ativo=True)
    if papel:
        qs = qs.filter(papel=papel)
    return qs.values("usuario_id")


def na_escola(qs, escola=None):
    """Só as contas com vínculo ativo com a escola (a atual, se não for dada). Lido na hora da consulta."""
    if escola is None and ESCOLA_ATUAL.get() is TODAS:
        return qs
    return qs.filter(pk__in=_vinculados(escola))


def administradores(escola=None):
    """Administradores da escola: vínculo ``ADMIN`` ou, com uma escola só no banco, o ``is_superuser`` gravado."""
    from django.contrib.auth import get_user_model

    from .escopo import escola_unica

    Usuario = get_user_model()
    filtro = Q(pk__in=_vinculados(escola, "ADMIN"))
    if escola_unica() is not None:
        filtro |= Q(is_superuser=True)
    return Usuario.objects.filter(filtro, is_active=True)
