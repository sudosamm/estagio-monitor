from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import Registro, Usuario
from ..services import estagios_visiveis, notificar, status_hoje
from .base import papel

supervisor_requerido = papel(Usuario.Papel.SUPERVISOR)


@supervisor_requerido
def painel_supervisor(request):
    estagios = list(estagios_visiveis(request.user).filter(ativo=True).prefetch_related("escalas"))
    for e in estagios:
        e.st = status_hoje(e)
    pendentes = Registro.objects.filter(
        estagio__in=estagios, confirmacao=Registro.Confirmacao.PENDENTE, data__lte=timezone.localdate(),
    ).select_related("estagio__estagiario").order_by("-data")
    return render(request, "core/painel_supervisor.html", {"estagios": estagios, "pendentes": pendentes})


@supervisor_requerido
@require_POST
def confirmar_lote(request):
    ids = request.POST.getlist("registros")
    regs = Registro.objects.filter(
        pk__in=ids, estagio__supervisor=request.user, confirmacao=Registro.Confirmacao.PENDENTE
    ).select_related("estagio__estagiario", "estagio__orientador")
    n = 0
    for reg in regs:
        reg.confirmar(request.user, Registro.Confirmacao.CONFIRMADA)
        reg.save()
        n += 1
        notificar([reg.estagio.estagiario], f"Seu registro de {reg.data:%d/%m} foi confirmado pelo supervisor.",
                  reverse("estagio_dia", args=[reg.estagio_id, reg.data.isoformat()]))
    messages.success(request, f"{n} registro(s) confirmado(s).")
    return redirect("painel_supervisor")
