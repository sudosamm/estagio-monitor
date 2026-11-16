"""Visitas, conversas e reuniões."""
from datetime import timedelta
from datetime import timezone as dt_timezone

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.crypto import get_random_string
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..forms import AgendamentoForm, SolicitacaoForm
from ..models import Agendamento, Usuario
from ..services import estagios_visiveis, notificar


def _sem_agenda(user):
    """Gestores sem a permissão “agenda” (ex.: coordenador de curso) não usam a agenda."""
    return user.is_gestor and not user.pode("agenda")


def _agendamentos_de(user):
    qs = Agendamento.objects.select_related("solicitante", "local", "orientador").prefetch_related("estagios__estagiario")
    if user.is_superuser:
        return qs
    if user.is_orientador:
        return qs.filter(orientador=user)
    return qs.filter(Q(solicitante=user) | Q(estagios__estagiario=user) | Q(estagios__supervisor=user)).distinct()


@login_required
def agendamentos(request):
    if _sem_agenda(request.user):
        raise PermissionDenied
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
    if _sem_agenda(user):
        raise PermissionDenied
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
    if _sem_agenda(request.user):
        raise PermissionDenied
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
    acomp = {a.estagio_id: a for a in ag.acompanhamentos.all()}
    estagios = [(e, acomp.get(e.pk)) for e in ag.estagios.select_related("estagiario")]
    return render(request, "core/agendamento_detalhe.html", {"ag": ag, "form": form, "e_orientador": e_orientador,
                                                             "estagios_visita": estagios})


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


# ---------------------------------------------------------------- calendário (Google Agenda, celular)

DURACAO_PADRAO = {Agendamento.Tipo.VISITA: 90, Agendamento.Tipo.CONVERSA: 30, Agendamento.Tipo.REUNIAO: 60}


@login_required
def assinar_agenda(request):
    """Mostra o link secreto da agenda e permite gerar um novo (o antigo para de funcionar)."""
    user = request.user
    if _sem_agenda(user):
        raise PermissionDenied
    if request.method == "POST":
        user.token_agenda = get_random_string(32)
        user.save(update_fields=["token_agenda"])
        if request.POST.get("acao") == "novo":
            messages.success(request, "Novo link gerado. O link antigo deixou de funcionar: assine de novo no calendário.")
        return redirect("assinar_agenda")
    url = ""
    if user.token_agenda:
        url = request.build_absolute_uri(reverse("agenda_ics", args=[user.token_agenda]))
    return render(request, "core/assinar_agenda.html", {
        "url": url, "webcal": url.replace("https://", "webcal://").replace("http://", "webcal://"),
    })


def _ics_texto(valor):
    texto = str(valor or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return texto.replace("\r\n", "\\n").replace("\n", "\\n")


def _ics_dobrar(linha):
    """Linhas de no máximo 75 bytes (RFC 5545), continuadas com espaço."""
    dados = linha.encode()
    if len(dados) <= 75:
        return linha
    partes, atual = [], b""
    for ch in linha:
        b = ch.encode()
        if len(atual) + len(b) > (75 if not partes else 74):
            partes.append(atual.decode())
            atual = b""
        atual += b
    partes.append(atual.decode())
    return "\r\n ".join(partes)


def agenda_ics(request, token):
    """Calendário .ics das visitas e conversas, sem login: o link secreto identifica a pessoa."""
    user = Usuario.objects.filter(token_agenda=token, is_active=True).first() if len(token) >= 20 else None
    if not user or _sem_agenda(user):
        raise Http404
    desde = timezone.now() - timedelta(days=120)
    qs = (_agendamentos_de(user).filter(data_hora__isnull=False, data_hora__gte=desde)
          .exclude(status=Agendamento.Status.SOLICITADO).order_by("data_hora"))
    host = request.get_host().split(":")[0]
    agora = timezone.now().strftime("%Y%m%dT%H%M%SZ")
    site = settings.SITE_URL or f"{request.scheme}://{request.get_host()}"
    linhas = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//{_ics_texto(settings.NOME_SISTEMA)}//Agenda//PT-BR",
              "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{_ics_texto(settings.NOME_SISTEMA)} — visitas",
              f"X-WR-TIMEZONE:{settings.TIME_ZONE}", "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
              "X-PUBLISHED-TTL:PT1H"]
    for a in qs:
        inicio = a.data_hora.astimezone(dt_timezone.utc)
        fim = inicio + timedelta(minutes=DURACAO_PADRAO.get(a.tipo, 60))
        nomes = ", ".join(e.estagiario.nome_completo for e in a.estagios.all())
        descricao = [f"{a.get_tipo_display()} ({a.get_modalidade_display().lower()})"]
        if nomes:
            descricao.append(f"Estagiários: {nomes}")
        if a.detalhes:
            descricao.append(a.detalhes)
        descricao.append(f"{site}{a.get_absolute_url()}")
        local = ""
        if a.local:
            endereco = ", ".join(p for p in [a.local.endereco, a.local.numero, a.local.bairro, a.local.cidade] if p)
            local = a.local.nome + (f" — {endereco}" if endereco else "")
        elif a.modalidade != Agendamento.Modalidade.PRESENCIAL:
            local = a.get_modalidade_display()
        rotulo = "Visita" if a.tipo == Agendamento.Tipo.VISITA else a.get_tipo_display().split(" /")[0]
        resumo = a.assunto if a.assunto.lower().startswith(rotulo.lower()) else f"{rotulo}: {a.assunto}"
        status = {Agendamento.Status.CANCELADO: "CANCELLED"}.get(a.status, "CONFIRMED")
        if a.status == Agendamento.Status.CANCELADO:
            resumo = f"[Cancelado] {resumo}"
        linhas += ["BEGIN:VEVENT", f"UID:agendamento-{a.pk}@{host}", f"DTSTAMP:{agora}",
                   f"LAST-MODIFIED:{a.atualizado_em.astimezone(dt_timezone.utc):%Y%m%dT%H%M%SZ}",
                   f"DTSTART:{inicio:%Y%m%dT%H%M%SZ}", f"DTEND:{fim:%Y%m%dT%H%M%SZ}",
                   f"SUMMARY:{_ics_texto(resumo)}", f"DESCRIPTION:{_ics_texto(chr(10).join(descricao))}",
                   f"URL:{site}{a.get_absolute_url()}", f"STATUS:{status}"]
        if local:
            linhas.append(f"LOCATION:{_ics_texto(local)}")
        if a.status == Agendamento.Status.AGENDADO:
            linhas += ["BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:Lembrete", "TRIGGER:-PT1H", "END:VALARM"]
        linhas.append("END:VEVENT")
    linhas.append("END:VCALENDAR")
    corpo = "\r\n".join(_ics_dobrar(l) for l in linhas) + "\r\n"
    resp = HttpResponse(corpo, content_type="text/calendar; charset=utf-8")
    resp["Content-Disposition"] = 'inline; filename="agenda.ics"'
    resp["Cache-Control"] = "private, max-age=900"
    return resp
