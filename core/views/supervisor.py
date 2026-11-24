from django.contrib import messages
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..atestados import pendentes_para
from ..models import HistoricoRegistro, Justificativa, Registro, Usuario
from ..services import estagios_visiveis, notificar, preparar_lote, status_hoje
from .base import papel

supervisor_requerido = papel(Usuario.Papel.SUPERVISOR)


@supervisor_requerido
def painel_supervisor(request):
    from ..equipe import estagios_de_apoio

    hoje = timezone.localdate()
    estagios = preparar_lote(estagios_visiveis(request.user).filter(ativo=True), hoje, totais=False)
    apoio = preparar_lote(estagios_de_apoio(request.user), hoje, totais=False)
    for e in apoio:
        e.st = status_hoje(e)
    sem_horario = []
    for e in estagios:
        e.st = status_hoje(e)
        esc = e.escala_em(hoje) or e.escalas.order_by("vigente_desde").first()
        if not esc or not esc.horario_entrada:
            sem_horario.append(e)
    pendentes = Registro.objects.filter(
        estagio__in=estagios + apoio, confirmacao=Registro.Confirmacao.PENDENTE, data__lte=timezone.localdate(),
    ).exclude(justificativa__status=Justificativa.Status.PENDENTE).select_related("estagio__estagiario").order_by("-data")
    return render(request, "core/painel_supervisor.html", {"estagios": estagios, "pendentes": pendentes,
                                                           "apoio": apoio, **_substituicoes(request.user, hoje),
                                                           "sem_horario": sem_horario,
                                                           "atestados": pendentes_para(request.user, estagios),
                                                           "documentos": _documentos_do_supervisor(estagios),
                                                           **_feedback_do_mes(estagios)})


def _substituicoes(user, hoje):
    """Quem me substitui (sou titular), a quem substituo e os colegas para indicar no “Vou me ausentar”."""
    from ..equipe import equipe_de, substituicoes_ativas
    from ..forms import SubstituicaoForm
    from ..models import Substituicao

    minhas = (Substituicao.objects.filter(titular=user, revogada_em__isnull=True, fim__gte=hoje)
              .select_related("substituto", "concedente"))
    locais = list(user.concedentes.all())
    form = None
    if locais and user.estagios_supervisionados.filter(ativo=True).exists():
        form = SubstituicaoForm(prefix="s", equipe=equipe_de(locais[0]), titular_fixo=user,
                                initial={"inicio": hoje})
    return {"me_substituem": minhas, "substituo": substituicoes_ativas(user), "form_ausencia": form,
            "locais_ausencia": locais}


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
    from ..equipe import estagios_de_apoio

    ids = request.POST.getlist("registros")
    regs = Registro.objects.filter(
        Q(estagio__supervisor=request.user) | Q(estagio__in=estagios_de_apoio(request.user)),
        pk__in=ids, confirmacao=Registro.Confirmacao.PENDENTE,
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
