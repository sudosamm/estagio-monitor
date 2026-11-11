"""Visitas, conversas e reuniões."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..forms import AgendamentoForm, SolicitacaoForm
from ..models import Agendamento
from ..services import estagios_visiveis, notificar


def _agendamentos_de(user):
    qs = Agendamento.objects.select_related("solicitante", "local", "orientador").prefetch_related("estagios__estagiario")
    if user.is_superuser:
        return qs
    if user.is_orientador:
        return qs.filter(orientador=user)
    return qs.filter(Q(solicitante=user) | Q(estagios__estagiario=user) | Q(estagios__supervisor=user)).distinct()


@login_required
def agendamentos(request):
    qs = _agendamentos_de(request.user)
    agora = timezone.now()
    return render(request, "core/agendamentos.html", {
        "solicitados": qs.filter(status=Agendamento.Status.SOLICITADO).order_by("criado_em"),
        "proximos": qs.filter(status=Agendamento.Status.AGENDADO, data_hora__gte=agora).order_by("data_hora"),
        "historico": qs.filter(
            Q(status__in=[Agendamento.Status.REALIZADO, Agendamento.Status.CANCELADO])
            | Q(status=Agendamento.Status.AGENDADO, data_hora__lt=agora)
        ).order_by("-data_hora", "-criado_em")[:50],
    })


@login_required
def novo_agendamento(request):
    user = request.user
    estagios = estagios_visiveis(user).filter(ativo=True)
    inicial = {}
    if request.GET.get("estagio"):
        sel = estagios.filter(pk=request.GET["estagio"]).first()
        if sel:
            inicial = {"estagios": [sel], "local": sel.local}
    if user.is_orientador or user.is_superuser:
        form = AgendamentoForm(request.POST or None, estagios_qs=estagios, initial=inicial)
    else:
        form = SolicitacaoForm(request.POST or None, estagios_qs=estagios, initial=inicial)
    if request.method == "POST" and form.is_valid():
        ag = form.save(commit=False)
        ag.solicitante = user
        selecionados = list(form.cleaned_data["estagios"])
        if not selecionados:
            messages.error(request, "Selecione ao menos um estagiário.")
            return redirect(request.path)
        if user.is_orientador or user.is_superuser:
            ag.orientador = selecionados[0].orientador if user.is_superuser else user
        else:
            ag.orientador = selecionados[0].orientador
            ag.status = Agendamento.Status.SOLICITADO
            ag.local = selecionados[0].local
        ag.save()
        form.save_m2m()
        if ag.status == Agendamento.Status.SOLICITADO:
            texto = f"{user.primeiro_nome} solicitou {ag.get_tipo_display().lower()}: {ag.assunto}"
        else:
            quando = timezone.localtime(ag.data_hora).strftime("%d/%m às %H:%M") if ag.data_hora else ""
            texto = f"{ag.get_tipo_display()} agendada para {quando}: {ag.assunto}"
        notificar(ag.envolvidos(), texto, ag.get_absolute_url(), exceto=user)
        messages.success(request, "Solicitação enviada ao orientador." if ag.status == Agendamento.Status.SOLICITADO
                         else "Agendamento criado e participantes avisados.")
        return redirect(ag)
    titulo = "Agendar visita ou conversa" if user.is_orientador else "Solicitar visita ou conversa"
    return render(request, "core/form_pagina.html", {"form": form, "titulo": titulo, "voltar": "/agenda/",
                                                     "botao": "Salvar"})


@login_required
def agendamento_detalhe(request, pk):
    ag = get_object_or_404(_agendamentos_de(request.user), pk=pk)
    user = request.user
    e_orientador = user.is_superuser or ag.orientador_id == user.pk
    form = None
    if e_orientador:
        estagios = estagios_visiveis(user)
        form = AgendamentoForm(request.POST or None, instance=ag, estagios_qs=estagios)
        if request.method == "POST" and form.is_valid():
            mudou = set(form.changed_data)
            ag = form.save()
            if mudou & {"status", "data_hora"}:
                if ag.status == Agendamento.Status.AGENDADO and ag.data_hora:
                    quando = timezone.localtime(ag.data_hora).strftime("%d/%m às %H:%M")
                    texto = f"{ag.get_tipo_display()} marcada para {quando}: {ag.assunto}"
                else:
                    texto = f"{ag.get_tipo_display()} “{ag.assunto}” agora está {ag.get_status_display().lower()}."
                notificar(ag.envolvidos(), texto, ag.get_absolute_url(), exceto=user)
            messages.success(request, "Agendamento atualizado.")
            return redirect(ag)
    return render(request, "core/agendamento_detalhe.html", {"ag": ag, "form": form, "e_orientador": e_orientador})


@login_required
@require_POST
def cancelar_agendamento(request, pk):
    ag = get_object_or_404(_agendamentos_de(request.user), pk=pk)
    if not (request.user.pk in (ag.solicitante_id, ag.orientador_id) or request.user.is_superuser):
        raise PermissionDenied
    ag.status = Agendamento.Status.CANCELADO
    ag.save(update_fields=["status", "atualizado_em"])
    notificar(ag.envolvidos(), f"{ag.get_tipo_display()} “{ag.assunto}” foi cancelada por {request.user.primeiro_nome}.",
              ag.get_absolute_url(), exceto=request.user)
    messages.success(request, "Agendamento cancelado.")
    return redirect("agendamentos")
