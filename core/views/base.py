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


orientador_requerido = papel(Usuario.Papel.ORIENTADOR)


def pegar_estagio(request, pk):
    estagio = get_object_or_404(
        Estagio.objects.select_related("estagiario", "orientador", "supervisor", "local", "curso"), pk=pk
    )
    if not estagio.pode_ver(request.user):
        raise PermissionDenied
    return estagio


def eh_orientador_do(user, estagio):
    return user.is_superuser or estagio.orientador_id == user.pk


def eh_supervisor_do(user, estagio):
    return estagio.supervisor_id == user.pk


def destino_seguro(request, padrao):
    prox = request.POST.get("next") or request.GET.get("next")
    if prox and url_has_allowed_host_and_scheme(prox, allowed_hosts={request.get_host()}):
        return prox
    return padrao
