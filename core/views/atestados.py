"""Atestados e comprovantes de falta: envio pelo estagiário, análise pelo supervisor ou pela escola."""
import mimetypes

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..atestados import ArquivoInvalido, decidir, pendentes_para, preparar_arquivo, registrar_justificativa
from ..forms import DecisaoJustificativaForm, JustificativaForm
from ..models import Configuracao, Justificativa
from ..services import estagios_visiveis
from .base import eh_orientador_do, orientador_requerido, pegar_estagio


def _pegar(request, pk):
    j = get_object_or_404(Justificativa.objects.select_related(
        "estagio__estagiario", "estagio__supervisor", "estagio__orientador", "estagio__curso", "enviado_por",
        "decidido_por"), pk=pk)
    if not j.pode_ver(request.user):
        raise PermissionDenied
    return j


@login_required
def enviar_atestado(request, pk):
    estagio = pegar_estagio(request, pk)
    e_estagiario = estagio.estagiario_id == request.user.pk
    if not (e_estagiario or eh_orientador_do(request.user, estagio)):
        raise PermissionDenied
    form = JustificativaForm(request.POST or None, request.FILES or None,
                             initial={"data_inicio": request.GET.get("data")})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            arquivo = preparar_arquivo(d["arquivo"])
            j = registrar_justificativa(estagio, request.user, d["tipo"], d["data_inicio"], d["data_fim"],
                                        d["motivo"].strip(), arquivo, d["arquivo"].name, request)
        except ArquivoInvalido as exc:
            form.add_error("arquivo" if "arquivo" in str(exc).lower() or "formato" in str(exc).lower() else None, str(exc))
        else:
            n = len(j.dias)
            if j.pendente:
                messages.success(request, f"Documento enviado. {n} dia{'s' if n > 1 else ''} aguardando análise.")
            else:
                messages.success(request, f"Documento registrado: {n} dia{'s' if n > 1 else ''} justificado{'s' if n > 1 else ''}.")
            return redirect(j)
    cfg = Configuracao.atual()
    quem = "o supervisor ou a escola" if cfg.atestados_supervisor and estagio.supervisor else "a escola (orientador)"
    ajuda = (f"Os dias de estágio do período ficam como ausência aguardando análise. Se {quem} aceitar, viram ausência "
             "justificada e não contam como falta. Se recusar, os dias que já passaram ficam como falta.")
    if not e_estagiario:
        ajuda = ("Documento entregue à escola: ao salvar, os dias já ficam como ausência justificada. "
                 "O estagiário e o supervisor são avisados.")
    return render(request, "core/form_pagina.html", {
        "form": form, "titulo": f"Enviar atestado ou comprovante{'' if e_estagiario else ' — ' + estagio.estagiario.nome_completo}",
        "voltar": estagio.get_absolute_url(), "ajuda": ajuda, "botao": "Enviar documento",
        "extra_template": "core/_atestados_lista.html", "atestados": estagio.justificativas.all()[:10],
    })


@login_required
def atestado_detalhe(request, pk):
    j = _pegar(request, pk)
    return render(request, "core/atestado.html", {
        "j": j, "e": j.estagio, "pode_decidir": j.pode_decidir(request.user) and j.pendente,
        "form": DecisaoJustificativaForm(), "registros": j.registros.order_by("data"),
    })


@login_required
def atestado_arquivo(request, pk):
    j = _pegar(request, pk)
    try:
        arquivo = j.arquivo.open("rb")
    except FileNotFoundError as exc:
        raise Http404("Arquivo não encontrado") from exc
    nome = j.arquivo.name.rsplit("/", 1)[-1]
    tipo = mimetypes.guess_type(nome)[0] or "application/octet-stream"
    resp = FileResponse(arquivo, as_attachment=False, filename=f"atestado-{j.pk}.{nome.rsplit('.', 1)[-1]}",
                        content_type=tipo)
    resp["Cache-Control"] = "private, no-store"
    resp["X-Content-Type-Options"] = "nosniff"
    return resp


@login_required
@require_POST
def decidir_atestado(request, pk):
    j = _pegar(request, pk)
    if not j.pode_decidir(request.user):
        raise PermissionDenied
    if not j.pendente:
        messages.info(request, "Este documento já foi analisado.")
        return redirect(j)
    form = DecisaoJustificativaForm(request.POST)
    form.is_valid()
    parecer = form.cleaned_data.get("parecer", "").strip()
    acao = request.POST.get("acao")
    if acao not in ("aceitar", "recusar"):
        raise Http404
    if acao == "recusar" and not parecer:
        messages.error(request, "Para recusar, escreva o motivo no parecer. O estagiário vai ver.")
        return redirect(j)
    decidir(j, request.user, aceitar=acao == "aceitar", parecer=parecer, request=request)
    n = len(j.dias)
    if acao == "aceitar":
        messages.success(request, f"Aceito: {n} dia{'s' if n > 1 else ''} de {j.estagio.estagiario.primeiro_nome} como "
                                  f"ausência justificada.")
    else:
        messages.success(request, "Recusado. Os dias que já passaram ficaram como falta.")
    return redirect(j)


@orientador_requerido
def atestados(request):
    estagios = estagios_visiveis(request.user)
    filtro = request.GET.get("status", "")
    decididos = (Justificativa.objects.filter(estagio__in=estagios).exclude(status=Justificativa.Status.PENDENTE)
                 .select_related("estagio__estagiario", "decidido_por").order_by("-decidido_em"))
    if filtro in (Justificativa.Status.ACEITA, Justificativa.Status.RECUSADA):
        decididos = decididos.filter(status=filtro)
    return render(request, "core/atestados.html", {
        "pendentes": pendentes_para(request.user, estagios), "decididos": decididos[:60], "filtro": filtro,
    })
