"""Pasta do estágio: envio dos documentos exigidos, conferência pela escola e visão geral do que falta."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..forms import EntregaForm, TipoDocumentoForm
from ..models import Documento, TipoDocumento
from ..pasta import conferir, pastas, pode_enviar, registrar_entrega, resumo_pasta, tipos_ativos
from ..services import ano_em_uso
from .base import destino_seguro, eh_orientador_do, orientador_requerido, pegar_estagio, permissao
from .orientador import contexto_ano, filtrar_lista, turmas_do_ano


@login_required
@require_POST
def enviar_para_pasta(request, pk, tipo_pk):
    estagio = pegar_estagio(request, pk)
    tipo = get_object_or_404(TipoDocumento, pk=tipo_pk)
    if not (pode_enviar(request.user, estagio) and tipo.vale_para(estagio)):
        raise PermissionDenied
    form = EntregaForm(request.POST, request.FILES)
    if form.is_valid():
        doc = registrar_entrega(estagio, tipo, request.user, form.cleaned_data["arquivo"],
                                form.cleaned_data["observacao"].strip())
        messages.success(request, f"“{tipo.nome}” enviado." + ("" if doc.situacao == Documento.Situacao.APROVADO
                                                                 else " A escola vai conferir."))
    else:
        for erros in form.errors.values():
            messages.error(request, " ".join(erros))
    return redirect(estagio.get_absolute_url() + "?aba=arquivos#pasta")


@orientador_requerido
@require_POST
def entregue_em_papel(request, pk, tipo_pk):
    """A escola já tem o documento em papel: marca como conferido, sem arquivo."""
    estagio = pegar_estagio(request, pk)
    tipo = get_object_or_404(TipoDocumento, pk=tipo_pk)
    if not (eh_orientador_do(request.user, estagio) and tipo.vale_para(estagio)):
        raise PermissionDenied
    registrar_entrega(estagio, tipo, request.user, None, request.POST.get("observacao", "").strip()[:300])
    messages.success(request, f"“{tipo.nome}” marcado como entregue em papel.")
    return redirect(destino_seguro(request, estagio.get_absolute_url() + "?aba=arquivos#pasta"))


@orientador_requerido
@require_POST
def entregue_em_papel_lote(request):
    """Marca um documento como entregue em papel para vários estagiários de uma vez (ex.: TCEs arquivados)."""
    tipo = get_object_or_404(TipoDocumento, pk=request.POST.get("tipo"))
    from ..services import estagios_visiveis

    estagios = estagios_visiveis(request.user).filter(pk__in=request.POST.getlist("estagios"))
    todas = pastas(list(estagios))
    n = 0
    for e in estagios:
        item = next((i for i in todas[e.pk] if i.tipo.pk == tipo.pk), None)
        if item and item.codigo != "conferido" and eh_orientador_do(request.user, e):
            registrar_entrega(e, tipo, request.user, None, avisar=False)
            n += 1
    messages.success(request, f"“{tipo.nome}” marcado como entregue em papel para {n} estagiário(s).")
    return redirect(destino_seguro(request, "/documentos/pasta/"))


@login_required
@require_POST
def conferir_documento(request, pk):
    doc = get_object_or_404(Documento.objects.select_related("estagio__estagiario", "estagio__curso", "tipo"), pk=pk,
                            estagio__isnull=False)
    if not eh_orientador_do(request.user, doc.estagio):
        raise PermissionDenied
    acao, parecer = request.POST.get("acao"), request.POST.get("parecer", "").strip()[:500]
    if acao not in ("aprovar", "recusar"):
        raise Http404
    if acao == "recusar" and not parecer:
        messages.error(request, "Para recusar, escreva o que precisa ser corrigido.")
    else:
        conferir(doc, request.user, acao == "aprovar", parecer)
        messages.success(request, "Documento conferido." if acao == "aprovar" else "Documento recusado. O estagiário foi avisado.")
    return redirect(destino_seguro(request, doc.estagio.get_absolute_url() + "?aba=arquivos#pasta"))


@login_required
def baixar_modelo(request, pk):
    tipo = get_object_or_404(TipoDocumento, pk=pk)
    if not tipo.modelo:
        raise Http404
    nome = tipo.modelo.name.rsplit("/", 1)[-1]
    return FileResponse(tipo.modelo.open("rb"), as_attachment=True, filename=nome)


@orientador_requerido
def pasta_geral(request):
    """Quadro: um estagiário por linha, um documento por coluna, com o que falta."""
    ano = ano_em_uso(request)
    qs, f = filtrar_lista(request, ano)
    estagios = list(qs.order_by("estagiario__nome_completo"))
    todas = pastas(estagios)
    tipos = [t for t in tipos_ativos() if any(t.vale_para(e) for e in estagios)]
    linhas, conferir_lista = [], []
    tot = {"atrasados": 0, "enviados": 0, "completos": 0}
    for e in estagios:
        itens = {i.tipo.pk: i for i in todas[e.pk]}
        r = resumo_pasta(todas[e.pk])
        tot["atrasados"] += len(r["atrasados"])
        tot["enviados"] += r["enviados"]
        tot["completos"] += r["total"] > 0 and r["conferidos"] == r["total"]
        conferir_lista += [(e, i) for i in todas[e.pk] if i.codigo == "enviado"]
        if request.GET.get("so") == "pendencias" and not (r["atrasados"] or r["enviados"]):
            continue
        linhas.append({"e": e, "celulas": [itens.get(t.pk) for t in tipos], "r": r})
    return render(request, "core/pasta_geral.html", {
        **contexto_ano(request, ano), "f": f, "tipos": tipos, "linhas": linhas, "tot": tot, "total": len(estagios),
        "conferir": conferir_lista, "turmas": turmas_do_ano(request.user, ano), "so": request.GET.get("so", ""),
    })


@permissao("arquivos")
def tipos_documento(request, pk=None):
    editando = get_object_or_404(TipoDocumento, pk=pk) if pk else None
    form = TipoDocumentoForm(request.POST or None, request.FILES or None, instance=editando)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Documento da pasta salvo.")
        return redirect("tipos_documento")
    from django.db.models import Count

    itens = TipoDocumento.objects.select_related("curso").annotate(n=Count("entregas"))
    return render(request, "core/tipos_documento.html", {"form": form, "editando": editando, "itens": itens})
