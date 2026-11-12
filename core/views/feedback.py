"""Feedback mensal do supervisor sobre o estagiário."""
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from ..feedback import inicio_mes, mes_anterior, meses_abertos, nome_mes
from ..forms import FeedbackForm
from ..models import Feedback
from ..services import ano_em_uso, notificar
from .base import eh_supervisor_do, orientador_requerido, pegar_estagio
from .orientador import contexto_ano, filtrar_lista, turmas_do_ano


def _mes_param(request, abertos):
    texto = request.GET.get("mes", "")
    try:
        mes = date.fromisoformat(texto + "-01") if len(texto) == 7 else abertos[0]
    except ValueError:
        mes = abertos[0]
    return mes if mes in abertos else abertos[0]


@login_required
def dar_feedback(request, pk):
    estagio = pegar_estagio(request, pk)
    if not eh_supervisor_do(request.user, estagio):
        raise PermissionDenied
    abertos = meses_abertos()
    mes = _mes_param(request, abertos)
    atual = Feedback.objects.filter(estagio=estagio, mes=mes).first()
    form = FeedbackForm(request.POST if request.method == "POST" else None,
                        instance=atual or Feedback(estagio=estagio, mes=mes))
    if request.method == "POST" and form.is_valid():
        f = form.save(commit=False)
        f.autor = request.user
        f.save()
        e = estagio.estagiario
        media = f"média {str(f.media).replace('.', ',')}" if f.media else "só comentários"
        link = reverse("estagio_detalhe", args=[estagio.pk]) + "?aba=feedback"
        if f.visivel_estagiario:
            notificar([e], f"{request.user.primeiro_nome} deu o feedback de {nome_mes(mes).split(' de ')[0]} sobre o seu estágio.",
                      link)
        alerta = " Atenção: abaixo de “bom”." if f.media and f.media < 3 else ""
        notificar([estagio.orientador], f"{request.user.primeiro_nome} deu o feedback de {nome_mes(mes).split(' de ')[0]} sobre "
                  f"{e.primeiro_nome} ({media}).{alerta}", link)
        messages.success(request, f"Feedback de {e.primeiro_nome} ({nome_mes(mes)}) {'atualizado' if atual else 'enviado'}. Obrigado!")
        return redirect(reverse("painel_supervisor") + "#feedback")
    criterios = [c for c, _ in Feedback.CRITERIOS]
    return render(request, "core/feedback_form.html", {
        "e": estagio, "form": form, "mes": mes, "nome_mes": nome_mes(mes), "abertos": abertos, "atual": atual,
        "campos_notas": [form[c] for c in criterios],
        "anteriores": estagio.feedbacks.exclude(mes=mes)[:3],
    })


@orientador_requerido
def feedback_geral(request):
    """Quadro: últimos meses de feedback de cada estagiário, com quem ainda não recebeu o deste mês."""
    ano = ano_em_uso(request)
    qs, f = filtrar_lista(request, ano)
    estagios = list(qs.order_by("estagiario__nome_completo"))
    atual = inicio_mes(timezone.localdate())
    meses = [atual]
    for _ in range(3):
        meses.insert(0, mes_anterior(meses[0]))
    por = {}
    for fb in Feedback.objects.filter(estagio__in=estagios, mes__in=meses):
        por[(fb.estagio_id, fb.mes)] = fb
    linhas, sem_feedback, baixos = [], 0, 0
    for e in estagios:
        celulas = [por.get((e.pk, m)) for m in meses]
        if e.ativo and e.supervisor_id and not celulas[-1]:
            sem_feedback += 1
        ultimo = next((c for c in reversed(celulas) if c), None)
        if ultimo and ultimo.media and ultimo.media < 3:
            baixos += 1
        linhas.append({"e": e, "celulas": celulas, "ultimo": ultimo})
    return render(request, "core/feedback_geral.html", {
        **contexto_ano(request, ano), "f": f, "linhas": linhas, "meses": meses, "nomes_meses": [nome_mes(m) for m in meses],
        "sem_feedback": sem_feedback, "baixos": baixos, "turmas": turmas_do_ano(request.user, ano),
    })
