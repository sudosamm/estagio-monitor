from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.utils.http import url_has_allowed_host_and_scheme

from ..models import Estagio, Usuario


def papel(*papeis):
    """Restringe a view a determinados papéis (superusuário sempre passa)."""

    def deco(view):
        @wraps(view)
        @login_required
        def inner(request, *a, **kw):
            if not (request.user.is_superuser or request.user.papel in papeis):
                raise PermissionDenied
            return view(request, *a, **kw)

        return inner

    return deco


def permissao(nome):
    """Restringe a view a quem tem a permissão (ver PERMISSOES_POR_PAPEL em models.py)."""

    def deco(view):
        @wraps(view)
        @login_required
        def inner(request, *a, **kw):
            if not request.user.pode(nome):
                raise PermissionDenied
            return view(request, *a, **kw)

        return inner

    return deco


# área de gestão (orientador, coordenador de curso e administrador)
orientador_requerido = permissao("painel")


def pegar_estagio(request, pk):
    estagio = get_object_or_404(
        Estagio.objects.select_related("estagiario", "orientador", "supervisor", "local", "curso"), pk=pk
    )
    if not estagio.pode_ver(request.user):
        raise PermissionDenied
    return estagio


def eh_orientador_do(user, estagio):
    """Gestor do estágio: o orientador dele, o coordenador do curso ou o administrador."""
    return user.is_superuser or estagio.orientador_id == user.pk or user.coordena(estagio.curso_id)


def eh_supervisor_do(user, estagio):
    return estagio.supervisor_id == user.pk


def pode_definir_horario(user, estagio):
    """Dias e horários são da concedente: o supervisor define; o orientador pode ajustar se tiver a permissão."""
    return eh_supervisor_do(user, estagio) or (eh_orientador_do(user, estagio) and user.pode("escalas"))


def destino_seguro(request, padrao):
    prox = request.POST.get("next") or request.GET.get("next")
    if prox and url_has_allowed_host_and_scheme(prox, allowed_hosts={request.get_host()}):
        return prox
    return padrao
