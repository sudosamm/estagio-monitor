from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..atestados import pendentes_para
from ..models import HistoricoRegistro, Justificativa, Registro, Usuario
from ..services import estagios_visiveis, notificar, status_hoje
from .base import papel

supervisor_requerido = papel(Usuario.Papel.SUPERVISOR)


@supervisor_requerido
def painel_supervisor(request):
    estagios = list(estagios_visiveis(request.user).filter(ativo=True).prefetch_related("escalas"))
    hoje = timezone.localdate()
    sem_horario = []
    for e in estagios:
        e.st = status_hoje(e)
        esc = e.escala_em(hoje) or e.escalas.order_by("vigente_desde").first()
        if not esc or not esc.horario_entrada:
            sem_horario.append(e)
    pendentes = Registro.objects.filter(
        estagio__in=estagios, confirmacao=Registro.Confirmacao.PENDENTE, data__lte=timezone.localdate(),
    ).exclude(justificativa__status=Justificativa.Status.PENDENTE).select_related("estagio__estagiario").order_by("-data")
    return render(request, "core/painel_supervisor.html", {"estagios": estagios, "pendentes": pendentes,
                                                           "sem_horario": sem_horario,
                                                           "atestados": pendentes_para(request.user, estagios),
                                                           "documentos": _documentos_do_supervisor(estagios),
                                                           **_feedback_do_mes(estagios)})


def _feedback_do_mes(estagios):
    from ..feedback import inicio_mes, meses_abertos, nome_mes
    from ..models import Configuracao, Feedback

    if not Configuracao.atual().feedback_mensal:
        return {}
    mes = inicio_mes(timezone.localdate())
    feitos = {f.estagio_id: f for f in Feedback.objects.filter(estagio__in=estagios, mes=mes)}
    anterior = meses_abertos()[1:]
    faltam_anterior = set()
    if anterior:
        com = set(Feedback.objects.filter(estagio__in=estagios, mes=anterior[0]).values_list("estagio_id", flat=True))
        faltam_anterior = {e.pk for e in estagios if e.pk not in com and e.data_inicio < mes}
    return {"feedback_mes": nome_mes(mes), "feedback_itens": [(e, feitos.get(e.pk)) for e in estagios],
            "feedback_faltam": sum(1 for e in estagios if e.pk not in feitos),
            "feedback_anterior": anterior[0] if faltam_anterior else None, "faltam_anterior": faltam_anterior}


def _documentos_do_supervisor(estagios):
    from ..pasta import pastas

    todas = pastas(estagios)
    return [(e, i) for e in estagios for i in todas[e.pk]
            if i.tipo.quem_envia == "SUPERVISOR" and i.codigo in ("pendente", "atrasado", "recusado")]


@supervisor_requerido
@require_POST
def confirmar_lote(request):
    ids = request.POST.getlist("registros")
    regs = Registro.objects.filter(
        pk__in=ids, estagio__supervisor=request.user, confirmacao=Registro.Confirmacao.PENDENTE
    ).exclude(justificativa__status=Justificativa.Status.PENDENTE).select_related("estagio__estagiario", "estagio__orientador")
    n = 0
    for reg in regs:
        reg.confirmar(request.user, Registro.Confirmacao.CONFIRMADA)
        reg.anotar(request.user, HistoricoRegistro.Acao.VALIDACAO, request).save()
        n += 1
        notificar([reg.estagio.estagiario], f"Seu registro de {reg.data:%d/%m} foi confirmado pelo supervisor.",
                  reverse("estagio_dia", args=[reg.estagio_id, reg.data.isoformat()]))
    messages.success(request, f"{n} registro(s) confirmado(s).")
    return redirect("painel_supervisor")
