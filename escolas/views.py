from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .middleware import SESSAO, escolas_da_conta


@login_required
@require_POST
def trocar_escola(request):
    """Seletor de escola (só para quem tem vínculo com duas ou mais escolas). A escolha fica na sessão."""
    try:
        escolhida = int(request.POST.get("escola", ""))
    except ValueError:
        raise PermissionDenied from None
    if escolhida not in {e.pk for e in escolas_da_conta(request.user)}:
        raise PermissionDenied
    request.session[SESSAO] = escolhida
    from core.auditoria import registrar

    registrar(request, "escola", "Trocou de escola", alvo=str(escolhida))
    destino = request.POST.get("next") or "/"
    if not url_has_allowed_host_and_scheme(destino, {request.get_host()}, request.is_secure()):
        destino = "/"
    return redirect(destino)
