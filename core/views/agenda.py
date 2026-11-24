"""Visitas, conversas e reuniões."""
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_timezone

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.crypto import get_random_string
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..forms import AgendamentoForm, SolicitacaoForm
from ..models import Agendamento, Estagio, Registro, Usuario
from ..services import (
    estagios_do_orientador, estagios_visiveis, limite_calendario, notificar, preparar_lote, resumo_horas, status_periodo,
)


def _sem_agenda(user):
    """Gestores sem a permissão “agenda” (ex.: coordenador de curso) não usam a agenda."""
    return user.is_gestor and not user.pode("agenda")


def _agendamentos_de(user, so_meus=False):
    """`so_meus`: listas e agenda do administrador mostram só as visitas dele (como orientador); abrir uma visita de
    outro orientador pelo link continua valendo no modo administrador."""
    qs = Agendamento.objects.select_related("solicitante", "local", "orientador").prefetch_related("estagios__estagiario")
    if user.is_superuser:
        return qs.filter(Q(orientador=user) | Q(solicitante=user)) if so_meus else qs
    if user.is_orientador:
        return qs.filter(orientador=user)
    return qs.filter(Q(solicitante=user) | Q(estagios__estagiario=user) | Q(estagios__supervisor=user)).distinct()


@login_required
def agendamentos(request):
    if _sem_agenda(request.user):
        raise PermissionDenied
    qs = _agendamentos_de(request.user, so_meus=True)
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
    # agendar visita é do orientador: só os próprios estagiários, também para o administrador
    estagios = estagios_do_orientador(user).filter(ativo=True)
    inicial = {}
    ids = [i for i in request.GET.get("estagios", request.GET.get("estagio", "")).split(",") if i.isdigit()][:30]
    if ids:  # um estagiário (tela do estágio) ou vários da mesma concedente (roteiro de visitas)
        sel = list(estagios.filter(pk__in=ids).select_related("local"))
        if sel:
            inicial = {"estagios": sel, "local": sel[0].local}
    try:  # vindo do calendário do painel ou do roteiro: “Agendar neste dia”
        dia = date.fromisoformat(request.GET.get("data", ""))
        hora = request.GET.get("hora", "")
        h = time.fromisoformat(hora) if len(hora) == 5 else time(8, 0)
        inicial["data_hora"] = datetime.combine(dia, h)
    except ValueError:
        pass
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
            ag.orientador = user
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
    if isinstance(form, AgendamentoForm):
        return render(request, "core/agendamento_form.html", {
            "form": form, "agenda": _agenda_proxima(user),
        })
    return render(request, "core/form_pagina.html", {"form": form, "titulo": "Solicitar visita ou conversa",
                                                     "voltar": "/agenda/", "botao": "Salvar"})


def _agenda_proxima(user):
    """Compromissos já marcados (para avisar de conflito de horário na tela de agendamento)."""
    qs = _agendamentos_de(user).filter(data_hora__gte=timezone.now() - timedelta(hours=3),
                                       data_hora__lte=timezone.now() + timedelta(days=180),
                                       status=Agendamento.Status.AGENDADO)
    if user.is_superuser:
        qs = qs.filter(orientador=user)
    return [{"inicio": timezone.localtime(a.data_hora).strftime("%Y-%m-%dT%H:%M"), "assunto": a.assunto,
             "duracao": a.duracao_min} for a in qs]


def ficha_contexto(estagio, user, hoje=None):
    """Tudo o que o orientador precisa para marcar e fazer a visita a um estagiário."""
    hoje = hoje or timezone.localdate()
    preparar_lote([estagio], hoje - timedelta(days=14))
    horas = resumo_horas(estagio)
    limite = limite_calendario(estagio, horas)
    futuros = [s for s in status_periodo(estagio, hoje, hoje + timedelta(days=90), hoje=hoje, limite=limite)
               if s.codigo in ("hoje", "previsto")]
    recentes = status_periodo(estagio, hoje - timedelta(days=14), hoje - timedelta(days=1), hoje=hoje, limite=limite)
    visitas = estagio.agendamentos.exclude(status=Agendamento.Status.CANCELADO)
    outros = (estagios_visiveis(user).filter(ativo=True, local_id=estagio.local_id).exclude(pk=estagio.pk)
              .select_related("estagiario").order_by("estagiario__nome_completo") if estagio.local_id else [])
    local = estagio.local
    mapa = ""
    if local and (local.endereco or local.cidade):
        from urllib.parse import quote

        mapa = "https://www.google.com/maps/search/?api=1&query=" + quote(
            ", ".join(p for p in [local.endereco, local.numero, local.bairro, local.cidade, local.uf] if p))
    return {
        "e": estagio, "horas": horas, "escala": estagio.escala_em(hoje), "proximos": futuros[:5], "dias": futuros,
        "sem_registro": sum(1 for s in recentes if s.codigo == "sem_registro"),
        "a_validar": estagio.registros.filter(situacao=Registro.Situacao.PRESENTE,
                                              confirmacao=Registro.Confirmacao.PENDENTE, data__lt=hoje).count(),
        "ultima_visita": visitas.filter(status=Agendamento.Status.REALIZADO).order_by("-data_hora").first(),
        "proxima_visita": visitas.filter(status=Agendamento.Status.AGENDADO, data_hora__gte=timezone.now())
                                 .order_by("data_hora").first(),
        "outros": list(outros), "mapa": mapa,
    }


@login_required
def ficha_estagio(request, pk):
    """Ficha do estagiário para a tela de agendamento (JSON com o HTML pronto e os dados para preencher)."""
    user = request.user
    if not (user.is_superuser or (user.is_gestor and user.pode("agenda"))):
        raise PermissionDenied
    estagio = get_object_or_404(estagios_visiveis(user), pk=pk)
    ctx = ficha_contexto(estagio, user)
    esc = ctx["escala"]
    return JsonResponse({
        "id": estagio.pk, "nome": estagio.estagiario.nome_completo, "primeiro_nome": estagio.estagiario.primeiro_nome,
        "local_id": estagio.local_id, "local_nome": str(estagio.local or ""),
        "entrada": esc.horario_entrada.strftime("%H:%M") if esc and esc.horario_entrada else "",
        "dias": [s.data.isoformat() for s in ctx["dias"]],
        "html": render_to_string("core/_ficha_estagio.html", {**ctx, "com_incluir": True}, request=request),
    })


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
    fichas = []
    if e_orientador and ag.status in (Agendamento.Status.SOLICITADO, Agendamento.Status.AGENDADO):
        fichas = [ficha_contexto(e, user) for e in ag.estagios.select_related("estagiario", "local", "supervisor", "curso")]
    return render(request, "core/agendamento_detalhe.html", {"ag": ag, "form": form, "e_orientador": e_orientador,
                                                             "estagios_visita": estagios, "fichas": fichas})


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
    qs = (_agendamentos_de(user, so_meus=True).filter(data_hora__isnull=False, data_hora__gte=desde)
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
        fim = inicio + timedelta(minutes=a.duracao_min)
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
