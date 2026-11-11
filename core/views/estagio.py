"""Tela do estágio (compartilhada por estagiário, supervisor e orientador) e ações do dia a dia."""
from datetime import date, datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..forms import (
    AusenciaForm, DiarioForm, DocumentoForm, EscalaForm, EstagioForm, LancamentoForm, MensagemForm, PlanejarDiaForm,
    horas_str,
)
from ..models import DIAS_ABREV, Agendamento, DiaPlanejado, Documento, Escala, Registro
from ..services import (
    calendario_mes, horas_padrao, limite_calendario, notificar, proximos_dias, resumo_horas,
    status_hoje, status_periodo,
)
from .base import destino_seguro, eh_orientador_do, eh_supervisor_do, orientador_requerido, pegar_estagio, permissao

MESES = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro",
         "Outubro", "Novembro", "Dezembro"]


def _mes_param(request):
    hoje = timezone.localdate()
    try:
        ano, mes = (int(x) for x in request.GET.get("mes", "").split("-"))
        date(ano, mes, 1)
    except (ValueError, TypeError):
        ano, mes = hoje.year, hoje.month
    return ano, mes


def _nav_mes(ano, mes):
    ant = (ano - 1, 12) if mes == 1 else (ano, mes - 1)
    prox = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return {
        "titulo": f"{MESES[mes]} de {ano}",
        "anterior": f"{ant[0]}-{ant[1]:02d}",
        "proximo": f"{prox[0]}-{prox[1]:02d}",
        "atual": f"{ano}-{mes:02d}",
    }


def _mensagens_visiveis(estagio, user):
    qs = estagio.mensagens.select_related("autor")
    if eh_supervisor_do(user, estagio) and not eh_orientador_do(user, estagio):
        qs = qs.filter(privada_orientador=False)
    return qs


def _previsao(estagio):
    return resumo_horas(estagio)["previsao_termino"]


def _avisar_previsao(request, estagio, antes):
    """Mostra ao usuário como a mudança afetou a previsão de término."""
    depois = _previsao(estagio)
    if antes == depois:
        if depois:
            messages.info(request, f"Previsão de término continua em {depois:%d/%m/%Y}.")
        return
    if antes and depois:
        direcao = "adiada" if depois > antes else "antecipada"
        messages.info(request, f"Previsão de término {direcao}: de {antes:%d/%m/%Y} para {depois:%d/%m/%Y}.")
    elif depois:
        messages.info(request, f"Previsão de término: {depois:%d/%m/%Y}.")


def _documentos_visiveis(estagio):
    return Documento.objects.filter(
        Q(estagio=estagio)
        | Q(estagio__isnull=True, orientador_id=estagio.orientador_id, curso__isnull=True)
        | Q(estagio__isnull=True, orientador_id=estagio.orientador_id, curso_id=estagio.curso_id)
    ).select_related("enviado_por")


@login_required
def estagio_detalhe(request, pk):
    estagio = pegar_estagio(request, pk)
    user = request.user
    aba = request.GET.get("aba", "visao")
    ano, mes = _mes_param(request)
    horas = resumo_horas(estagio)
    limite = limite_calendario(estagio, horas)
    ctx = {
        "estagio": estagio,
        "aba": aba,
        "hoje": status_hoje(estagio),
        "horas": horas,
        "escala_atual": estagio.escala_em(timezone.localdate()),
        "e_orientador": eh_orientador_do(user, estagio),
        "e_supervisor": eh_supervisor_do(user, estagio),
        "e_estagiario": estagio.estagiario_id == user.pk,
        "nao_lidas_msg": 0,
        "pode_escalas": eh_orientador_do(user, estagio) and user.pode("escalas"),
        "pode_agenda": not user.is_gestor or user.pode("agenda"),
    }
    if aba == "visao":
        from .frequencia import resumo_impressoes

        semanas = calendario_mes(estagio, ano, mes, limite)
        if ctx["e_orientador"] or ctx["e_supervisor"]:
            ctx["impressoes"] = resumo_impressoes(estagio)
        visitas = Agendamento.objects.filter(
            estagios=estagio, data_hora__year=ano, data_hora__month=mes,
        ).exclude(status=Agendamento.Status.CANCELADO)
        dias_visita = {timezone.localtime(v.data_hora).date() for v in visitas if v.data_hora}
        ctx.update(
            semanas=semanas, dias_visita=dias_visita, nav=_nav_mes(ano, mes), dias_semana=DIAS_ABREV,
            proximos=proximos_dias(estagio, 6, limite), ausencia_form=AusenciaForm(initial={"data": timezone.localdate()}),
            diario_form=DiarioForm(initial={"diario": ctx["hoje"].registro.diario if ctx["hoje"].registro else ""}),
            proximas_visitas=estagio.agendamentos.filter(
                status=Agendamento.Status.AGENDADO, data_hora__gte=timezone.now()
            ).order_by("data_hora")[:3],
        )
    elif aba == "registros":
        ctx["registros"] = estagio.registros.select_related("confirmado_por")[:200]
    elif aba == "mensagens":
        ctx["mensagens"] = _mensagens_visiveis(estagio, user)
        ctx["mensagem_form"] = MensagemForm()
    elif aba == "arquivos":
        ctx["documentos"] = _documentos_visiveis(estagio)
        ctx["documento_form"] = DocumentoForm()
    elif aba == "agenda":
        ctx["agendamentos"] = estagio.agendamentos.select_related("solicitante").order_by("-criado_em")
    elif aba == "escalas":
        ctx["escalas"] = estagio.escalas.select_related("criado_por")
        if ctx["pode_escalas"]:
            atual = ctx["escala_atual"]
            ctx["escala_form"] = EscalaForm(initial={
                "vigente_desde": timezone.localdate(),
                "dias": atual.dias_lista if atual else [0, 1],
                "horario_entrada": atual.horario_entrada if atual else None,
                "saida_intervalo": atual.saida_intervalo if atual else None,
                "volta_intervalo": atual.volta_intervalo if atual else None,
                "horario_saida": atual.horario_saida if atual else None,
                "horas_por_dia": atual.horas_por_dia if atual else estagio.curso.horas_por_dia_padrao,
            })
    else:
        raise Http404
    return render(request, "core/estagio_detalhe.html", ctx)


# ----------------------------------------------------------------- ações do estagiário


@login_required
@require_POST
def marcar_presenca(request, pk):
    estagio = pegar_estagio(request, pk)
    if estagio.estagiario_id != request.user.pk:
        raise PermissionDenied
    hoje = timezone.localdate()
    agora = timezone.localtime().time().replace(second=0, microsecond=0)
    reg, criado = Registro.objects.get_or_create(
        estagio=estagio, data=hoje,
        defaults={"situacao": Registro.Situacao.PRESENTE, "horas": horas_padrao(estagio, hoje),
                  "hora_chegada": agora, "registrado_por": request.user},
    )
    if not criado:
        if reg.confirmacao == Registro.Confirmacao.CONFIRMADA:
            messages.info(request, "O registro de hoje já foi validado pelo supervisor.")
            return redirect(estagio)
        reg.situacao = Registro.Situacao.PRESENTE
        reg.hora_chegada = reg.hora_chegada or agora
        reg.horas = reg.horas or horas_padrao(estagio, hoje)
        reg.confirmacao = Registro.Confirmacao.PENDENTE
        reg.save()
    diario = request.POST.get("diario", "").strip()
    if diario:
        reg.diario = diario
        reg.save(update_fields=["diario"])
    if not status_hoje(estagio).previsto:
        messages.warning(request, "Hoje não estava previsto na sua escala — o supervisor vai validar.")
    messages.success(request, f"Presença marcada às {agora:%H:%M}. Aguardando confirmação do supervisor.")
    notificar(
        [estagio.supervisor], f"{estagio.estagiario.primeiro_nome} marcou presença hoje às {agora:%H:%M}.",
        reverse("painel_supervisor"),
    )
    return redirect(estagio)


PONTOS = {
    "saida_intervalo": "Saída para o intervalo registrada",
    "volta_intervalo": "Volta do intervalo registrada",
    "hora_saida": "Saída registrada",
}


@login_required
@require_POST
def registrar_saida(request, pk):
    """Registra intervalo (saída/volta) ou a saída do dia, no horário atual."""
    estagio = pegar_estagio(request, pk)
    if estagio.estagiario_id != request.user.pk:
        raise PermissionDenied
    ponto = request.POST.get("ponto", "hora_saida")
    if ponto not in PONTOS:
        raise Http404
    reg = get_object_or_404(Registro, estagio=estagio, data=timezone.localdate())
    agora = timezone.localtime().time().replace(second=0, microsecond=0)
    setattr(reg, ponto, agora)
    reg.save(update_fields=[ponto, "atualizado_em"])
    messages.success(request, f"{PONTOS[ponto]} às {agora:%H:%M}.")
    return redirect(estagio)


@login_required
@require_POST
def informar_ausencia(request, pk):
    estagio = pegar_estagio(request, pk)
    if estagio.estagiario_id != request.user.pk:
        raise PermissionDenied
    form = AusenciaForm(request.POST)
    if not form.is_valid():
        for erros in form.errors.values():
            messages.error(request, " ".join(erros))
        return redirect(estagio)
    dia, motivo = form.cleaned_data["data"], form.cleaned_data["motivo"]
    antes = _previsao(estagio)
    reg = Registro.objects.filter(estagio=estagio, data=dia).first()
    if reg and reg.situacao == Registro.Situacao.PRESENTE and reg.confirmacao == Registro.Confirmacao.CONFIRMADA:
        messages.error(request, "Esse dia já tem presença confirmada pelo supervisor.")
        return redirect(estagio)
    reg = reg or Registro(estagio=estagio, data=dia)
    reg.situacao = Registro.Situacao.AUSENCIA
    reg.horas = 0
    reg.motivo = motivo
    reg.confirmacao = Registro.Confirmacao.PENDENTE
    reg.registrado_por = request.user
    reg.save()
    DiaPlanejado.objects.filter(estagio=estagio, data=dia).delete()
    messages.success(request, f"Ausência em {dia:%d/%m} informada ao supervisor e ao orientador.")
    _avisar_previsao(request, estagio, antes)
    notificar(
        [estagio.supervisor, estagio.orientador],
        f"{estagio.estagiario} informou ausência em {dia:%d/%m}: {motivo[:80]}",
        reverse("estagio_dia", args=[estagio.pk, dia.isoformat()]),
    )
    return redirect(destino_seguro(request, estagio.get_absolute_url() + f"?mes={dia:%Y-%m}"))


# ----------------------------------------------------------------- dia


def _data_ou_404(texto):
    try:
        return datetime.strptime(texto, "%Y-%m-%d").date()
    except ValueError as exc:
        raise Http404 from exc


@login_required
def estagio_dia(request, pk, data):
    estagio = pegar_estagio(request, pk)
    dia = _data_ou_404(data)
    user = request.user
    status = status_periodo(estagio, dia, dia)[0]
    reg = status.registro
    pode_lancar = eh_orientador_do(user, estagio) or eh_supervisor_do(user, estagio)
    e_estagiario = estagio.estagiario_id == user.pk
    lancamento_form = diario_form = None

    if pode_lancar:
        inicial = {} if reg else {"situacao": Registro.Situacao.PRESENTE, "horas": horas_padrao(estagio, dia),
                                   "confirmacao": Registro.Confirmacao.CONFIRMADA}
        lancamento_form = LancamentoForm(request.POST or None, instance=reg or Registro(estagio=estagio, data=dia),
                                         initial=inicial, prefix="l")
        if request.method == "POST" and "l-situacao" in request.POST:
            if dia > timezone.localdate():
                messages.error(request, "Não é possível validar um dia futuro.")
                return redirect(request.path)
            if lancamento_form.is_valid():
                novo = lancamento_form.save(commit=False)
                if not novo.pk:
                    novo.registrado_por = user
                if novo.situacao != Registro.Situacao.PRESENTE:
                    novo.horas = 0
                if novo.confirmacao != Registro.Confirmacao.PENDENTE:
                    novo.confirmar(user, novo.confirmacao)
                novo.save()
                messages.success(request, "Registro salvo.")
                notificar(
                    [estagio.estagiario, estagio.supervisor, estagio.orientador],
                    f"{user.primeiro_nome} atualizou o registro de {dia:%d/%m}: {novo.get_situacao_display()} "
                    f"({novo.get_confirmacao_display().lower()}).",
                    request.path, exceto=user,
                )
                return redirect(destino_seguro(request, request.path))

    if e_estagiario and reg:
        diario_form = DiarioForm(request.POST or None, initial={"diario": reg.diario}, prefix="d")
        if request.method == "POST" and "d-diario" in request.POST and diario_form.is_valid():
            reg.diario = diario_form.cleaned_data["diario"]
            reg.save(update_fields=["diario", "atualizado_em"])
            messages.success(request, "Anotação do dia salva.")
            return redirect(request.path)

    # ---- planejamento de dias de hoje em diante (entra na previsão de término)
    hoje = timezone.localdate()
    pode_planejar = (e_estagiario or pode_lancar) and dia >= hoje and dia >= estagio.data_inicio and estagio.ativo
    plano_form = None
    if pode_planejar:
        resposta = _planejar_dia(request, estagio, dia, status, reg)
        if resposta:
            return resposta
        sem_registro_presenca = not reg or reg.situacao != Registro.Situacao.PRESENTE
        if sem_registro_presenca:
            plano_form = PlanejarDiaForm(prefix="p", initial={
                "horas": horas_str(status.plano.horas if status.plano else horas_padrao(estagio, dia)),
                "motivo": status.plano.motivo if status.plano else "",
            })

    return render(request, "core/estagio_dia.html", {
        "estagio": estagio, "dia": dia, "status": status, "registro": reg, "lancamento_form": lancamento_form,
        "diario_form": diario_form, "e_estagiario": e_estagiario, "pode_lancar": pode_lancar,
        "futuro": dia > hoje, "pode_planejar": pode_planejar, "plano_form": plano_form,
        "ausencia_form": AusenciaForm(initial={"data": dia}), "previsao": _previsao(estagio),
    })


def _planejar_dia(request, estagio, dia, status, reg):
    """Trata os botões de planejamento do dia. Devolve um redirect quando algo foi feito."""
    if request.method != "POST":
        return None
    acao = request.POST.get("planejar")
    if not acao:
        return None
    antes = _previsao(estagio)
    quem = request.user.primeiro_nome
    link = reverse("estagio_dia", args=[estagio.pk, dia.isoformat()])
    avisar = [estagio.estagiario, estagio.supervisor, estagio.orientador]

    if acao == "salvar":
        form = PlanejarDiaForm(request.POST, prefix="p")
        if not form.is_valid():
            messages.error(request, "Escolha quantas horas vai estagiar.")
            return redirect(request.path)
        if reg and reg.situacao == Registro.Situacao.PRESENTE:
            messages.error(request, "Este dia já tem presença registrada.")
            return redirect(request.path)
        if reg:  # tinha ausência informada: o estagiário mudou de ideia
            reg.delete()
        horas = form.cleaned_data["horas"]
        regular = status.escala and dia.weekday() in status.escala.dias_lista and not status.motivo_sem_estagio
        if regular and horas == status.escala.horas_por_dia:
            DiaPlanejado.objects.filter(estagio=estagio, data=dia).delete()
            messages.success(request, f"{dia:%d/%m} volta a ser um dia normal da escala.")
        else:
            DiaPlanejado.objects.update_or_create(estagio=estagio, data=dia, defaults={
                "horas": horas, "motivo": form.cleaned_data["motivo"], "criado_por": request.user,
            })
            messages.success(request, f"{dia:%d/%m} planejado: {horas_str(horas)} horas de estágio.")
            notificar(avisar, f"{quem} planejou estágio em {dia:%d/%m} ({horas_str(horas)}h)"
                      + (f": {form.cleaned_data['motivo']}" if form.cleaned_data["motivo"] else "."), link,
                      exceto=request.user)
    elif acao == "remover":
        DiaPlanejado.objects.filter(estagio=estagio, data=dia).delete()
        messages.success(request, f"Planejamento de {dia:%d/%m} removido.")
        notificar(avisar, f"{quem} removeu o estágio planejado para {dia:%d/%m}.", link, exceto=request.user)
    elif acao == "cancelar_ausencia":
        if reg and reg.situacao == Registro.Situacao.AUSENCIA:
            reg.delete()
            messages.success(request, f"Ausência de {dia:%d/%m} cancelada.")
            notificar(avisar, f"{quem} cancelou a ausência informada para {dia:%d/%m}.", link, exceto=request.user)
    else:
        raise Http404
    _avisar_previsao(request, estagio, antes)
    return redirect(request.path)


@login_required
@require_POST
def validar_registro(request, pk):
    """Ação rápida do supervisor/orientador: confirmar ou contestar um registro."""
    reg = get_object_or_404(Registro.objects.select_related("estagio__estagiario"), pk=pk)
    estagio = reg.estagio
    if not (eh_supervisor_do(request.user, estagio) or eh_orientador_do(request.user, estagio)):
        raise PermissionDenied
    acao = request.POST.get("acao")
    status = {"confirmar": Registro.Confirmacao.CONFIRMADA, "contestar": Registro.Confirmacao.CONTESTADA}.get(acao)
    if not status:
        raise Http404
    reg.confirmar(request.user, status, request.POST.get("obs", "").strip())
    reg.save()
    texto = "confirmou" if status == Registro.Confirmacao.CONFIRMADA else "contestou"
    notificar(
        [estagio.estagiario, estagio.orientador],
        f"{request.user.primeiro_nome} {texto} o registro de {reg.data:%d/%m} de {estagio.estagiario.primeiro_nome}.",
        reverse("estagio_dia", args=[estagio.pk, reg.data.isoformat()]), exceto=request.user,
    )
    participio = "confirmado" if status == Registro.Confirmacao.CONFIRMADA else "contestado"
    messages.success(request, f"Registro de {estagio.estagiario.primeiro_nome} em {reg.data:%d/%m} {participio}.")
    return redirect(destino_seguro(request, estagio.get_absolute_url()))


# ----------------------------------------------------------------- mensagens e arquivos


@login_required
@require_POST
def enviar_mensagem(request, pk):
    estagio = pegar_estagio(request, pk)
    form = MensagemForm(request.POST)
    if form.is_valid():
        msg = form.save(commit=False)
        msg.estagio, msg.autor = estagio, request.user
        if eh_supervisor_do(request.user, estagio):
            msg.privada_orientador = False
        msg.save()
        destinatarios = [estagio.estagiario, estagio.orientador]
        if not msg.privada_orientador:
            destinatarios.append(estagio.supervisor)
        notificar(destinatarios, f"Nova mensagem de {request.user.primeiro_nome} no estágio de "
                  f"{estagio.estagiario.primeiro_nome}.", estagio.get_absolute_url() + "?aba=mensagens",
                  exceto=request.user)
    return redirect(estagio.get_absolute_url() + "?aba=mensagens#fim")


@login_required
@require_POST
def enviar_documento(request, pk):
    estagio = pegar_estagio(request, pk)
    form = DocumentoForm(request.POST, request.FILES)
    if form.is_valid():
        doc = form.save(commit=False)
        doc.estagio, doc.orientador, doc.enviado_por = estagio, estagio.orientador, request.user
        doc.nome_original = request.FILES["arquivo"].name[:255]
        doc.save()
        notificar(estagio.participantes(), f"{request.user.primeiro_nome} anexou “{doc.titulo}”.",
                  estagio.get_absolute_url() + "?aba=arquivos", exceto=request.user)
        messages.success(request, "Arquivo enviado.")
    else:
        for erros in form.errors.values():
            messages.error(request, " ".join(erros))
    return redirect(estagio.get_absolute_url() + "?aba=arquivos")


# ----------------------------------------------------------------- orientador: gestão do estágio


@orientador_requerido
def editar_estagio(request, pk):
    estagio = pegar_estagio(request, pk)
    if not eh_orientador_do(request.user, estagio):
        raise PermissionDenied
    form = EstagioForm(request.POST or None, instance=estagio)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Dados do estágio atualizados.")
        return redirect(estagio)
    return render(request, "core/form_pagina.html", {
        "form": form, "titulo": f"Editar estágio — {estagio.estagiario}", "voltar": estagio.get_absolute_url(),
    })


@permissao("escalas")
@require_POST
def nova_escala(request, pk):
    estagio = pegar_estagio(request, pk)
    if not eh_orientador_do(request.user, estagio):
        raise PermissionDenied
    form = EscalaForm(request.POST)
    if form.is_valid():
        esc, _ = Escala.objects.update_or_create(
            estagio=estagio, vigente_desde=form.cleaned_data["vigente_desde"],
            defaults={**form.dados_escala(), "criado_por": request.user},
        )
        notificar([estagio.estagiario, estagio.supervisor],
                  f"Nova escala de estágio a partir de {esc.vigente_desde:%d/%m}: {esc.dias_display}.",
                  estagio.get_absolute_url(), exceto=request.user)
        messages.success(request, f"Escala salva: {esc}.")
    else:
        for erros in form.errors.values():
            messages.error(request, " ".join(erros))
    return redirect(estagio.get_absolute_url() + "?aba=escalas")


@permissao("escalas")
@require_POST
def excluir_escala(request, pk):
    esc = get_object_or_404(Escala.objects.select_related("estagio"), pk=pk)
    if not eh_orientador_do(request.user, esc.estagio):
        raise PermissionDenied
    if esc.estagio.escalas.count() == 1:
        messages.error(request, "O estágio precisa ter ao menos uma escala.")
    else:
        esc.delete()
        messages.success(request, "Escala removida.")
    return redirect(esc.estagio.get_absolute_url() + "?aba=escalas")
