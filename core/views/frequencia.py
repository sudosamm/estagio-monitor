"""Folha de frequência oficial (só impressão), o registro de quem abriu/imprimiu e as folhas enviadas pelo orientador.

O registro nunca aparece para estagiários: só orientador e supervisor do estágio o veem.
O orientador decide se o estagiário emite a própria folha ou só baixa a que ele enviar (Configuracao).
"""
import mimetypes
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import F, Max, Q, Sum
from django.http import FileResponse, Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..forms import FolhaEnviadaForm
from ..models import Configuracao, FolhaEnviada, ImpressaoFrequencia, Turma, Usuario
from ..services import ano_em_uso, estagios_visiveis, filtrar_ano, linhas_folha, notificar
from .base import eh_orientador_do, eh_supervisor_do, pegar_estagio, permissao
from .estagio import MESES, _mes_param, _nav_mes


def _ip(request):
    return (request.META.get("HTTP_CF_CONNECTING_IP")
            or request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
            or request.META.get("REMOTE_ADDR")) or None


def _folha(request, estagio, ano, mes):
    """Uma folha pronta para imprimir, com o registro de quem abriu (o código sai no rodapé)."""
    log = ImpressaoFrequencia.objects.create(
        estagio=estagio, usuario=request.user, mes=date(ano, mes, 1), ip=_ip(request),
        navegador=request.META.get("HTTP_USER_AGENT", "")[:255],
    )
    return {"estagio": estagio, "linhas": linhas_folha(estagio, ano, mes), "log": log}


def _render_folhas(request, folhas, ano, mes, voltar, titulo):
    params = request.GET.copy()
    params.pop("mes", None)
    resposta = render(request, "core/folha_frequencia.html", {
        "folhas": folhas, "nav": _nav_mes(ano, mes), "mes_nome": MESES[mes], "ano": ano, "config": Configuracao.atual(),
        "agora": timezone.localtime(), "voltar": voltar, "titulo": titulo, "outros_params": params.urlencode(),
    })
    resposta["Cache-Control"] = "no-store"
    return resposta


def estagiario_emite(user, estagio):
    return estagio.estagiario_id != user.pk or Configuracao.atual().estagiarios_emitem_folha


@login_required
def folha_frequencia(request, pk):
    estagio = pegar_estagio(request, pk)
    if not estagiario_emite(request.user, estagio):
        messages.info(request, "Neste período a folha de frequência é enviada pelo orientador: baixe-a aqui.")
        return redirect("minhas_folhas", estagio.pk)
    ano, mes = _mes_param(request)
    return _render_folhas(request, [_folha(request, estagio, ano, mes)], ano, mes, estagio.get_absolute_url(),
                          str(estagio.estagiario))


LIMITE_LOTE = 120


@permissao("folhas")
def folhas_lote(request):
    """O orientador emite de uma vez as folhas de uma turma, de uma concedente ou de todos (uma por página)."""
    ano, mes = _mes_param(request)
    qs = _estagios_painel(request).select_related("turma")
    turma, local = request.GET.get("turma", ""), request.GET.get("local", "")
    if turma.isdigit():
        qs = qs.filter(turma_id=turma)
    if local.isdigit():
        qs = qs.filter(local_id=local)
    ids = [i for i in request.GET.getlist("e") if i.isdigit()]
    if ids:
        qs = qs.filter(pk__in=ids)
    estagios = list(qs.order_by("estagiario__nome_completo")[:LIMITE_LOTE])
    if not estagios:
        messages.error(request, "Nenhum estágio ativo com esses filtros.")
        return redirect(f"{reverse('frequencias')}?mes={ano}-{mes:02d}")
    folhas = [_folha(request, e, ano, mes) for e in estagios]
    return _render_folhas(request, folhas, ano, mes, f"{reverse('frequencias')}?mes={ano}-{mes:02d}",
                          f"{len(folhas)} folha(s)")


@login_required
@require_POST
def marcar_impressao(request):
    """Chamado pelo navegador quando a folha vai para a impressora (inclui “Salvar como PDF”)."""
    codigos = request.POST.getlist("codigo")
    n = ImpressaoFrequencia.objects.filter(codigo__in=codigos, usuario=request.user).update(
        impressoes=F("impressoes") + 1, ultima_impressao=timezone.now())
    return HttpResponse(status=204) if n else HttpResponseBadRequest()


# ------------------------------------------------------------ folhas enviadas pelo orientador


def _pode_baixar(user, folha):
    if user.is_superuser or folha.enviado_por_id == user.pk:
        return None, True
    filtro = Q(folhas_enviadas=folha)
    if folha.turma_id:
        filtro |= Q(turma_id=folha.turma_id)
    estagio = estagios_visiveis(user).filter(filtro).order_by("-ativo", "-data_inicio").first()
    return estagio, estagio is not None


@login_required
def baixar_folha(request, pk):
    folha = get_object_or_404(FolhaEnviada.objects.select_related("turma"), pk=pk)
    estagio, pode = _pode_baixar(request.user, folha)
    if not pode:
        raise PermissionDenied
    if estagio and estagio.estagiario_id == request.user.pk:  # o orientador vê quem já baixou
        ImpressaoFrequencia.objects.create(
            estagio=estagio, usuario=request.user, mes=folha.mes, folha_enviada=folha, ip=_ip(request),
            navegador=request.META.get("HTTP_USER_AGENT", "")[:255],
        )
    try:
        arquivo = folha.arquivo.open("rb")
    except FileNotFoundError as exc:
        raise Http404("Arquivo não encontrado") from exc
    nome = folha.nome_original or folha.arquivo.name.rsplit("/", 1)[-1]
    tipo = mimetypes.guess_type(folha.arquivo.name)[0] or "application/octet-stream"
    resposta = FileResponse(arquivo, as_attachment=False, filename=nome, content_type=tipo)
    resposta["Cache-Control"] = "private, no-store"
    return resposta


@permissao("folhas")
@require_POST
def excluir_folha(request, pk):
    folha = get_object_or_404(FolhaEnviada, pk=pk)
    if not (request.user.is_superuser or folha.enviado_por_id == request.user.pk):
        raise PermissionDenied
    mes = folha.mes
    folha.arquivo.delete(save=False)
    folha.delete()
    messages.success(request, "Folha removida.")
    return redirect(f"{reverse('frequencias')}?mes={mes:%Y-%m}")


@login_required
def minhas_folhas(request, pk):
    """Folhas de frequência do estágio: as que o orientador enviou e, se permitido, a emitida pelo sistema."""
    estagio = pegar_estagio(request, pk)
    ano, mes = _mes_param(request)
    folhas = FolhaEnviada.do_estagio(estagio).select_related("enviado_por")
    return render(request, "core/minhas_folhas.html", {
        "estagio": estagio, "folhas": folhas, "nav": _nav_mes(ano, mes),
        "emite": estagiario_emite(request.user, estagio), "e_estagiario": estagio.estagiario_id == request.user.pk,
    })


def resumo_impressoes(estagio, limite=8):
    """Últimas aberturas da folha (para o card do orientador/supervisor)."""
    return estagio.impressoes.select_related("usuario")[:limite]


def _estagios_painel(request):
    qs = estagios_visiveis(request.user).filter(ativo=True)
    if request.user.is_supervisor:
        return qs
    return filtrar_ano(qs, ano_em_uso(request))


@login_required
def frequencias_painel(request):
    """Quem já abriu e imprimiu a folha de um mês; emissão em lote e envio de folhas pelo orientador."""
    user = request.user
    if not (user.pode("frequencias") or user.pode("folhas") or user.is_supervisor):
        raise PermissionDenied
    from .orientador import contexto_ano, turmas_do_ano

    config = Configuracao.atual()
    ano, mes = _mes_param(request)
    inicio_mes = date(ano, mes, 1)
    ano_lista = None if user.is_supervisor else ano_em_uso(request)
    base = _estagios_painel(request).select_related("turma")
    turmas = Turma.objects.filter(pk__in=base.values("turma")).select_related("curso")
    filtro_turma = request.GET.get("turma", "")
    if filtro_turma.isdigit():
        base = base.filter(turma_id=filtro_turma)
    estagios = list(base)
    pode_folhas = user.pode("folhas")

    envio = None
    if pode_folhas:
        envio = FolhaEnviadaForm(
            request.POST if request.POST.get("acao") == "enviar" else None,
            request.FILES if request.POST.get("acao") == "enviar" else None,
            estagios_qs=_estagios_painel(request).select_related("turma"),
            turmas=turmas_do_ano(user, ano_lista), initial={"mes": f"{ano}-{mes:02d}"},
        )
        if request.method == "POST" and request.POST.get("acao") == "config":
            config.estagiarios_emitem_folha = request.POST.get("estagiarios_emitem_folha") == "1"
            config.save(update_fields=["estagiarios_emitem_folha", "atualizado_em"])
            messages.success(request, "Agora os estagiários emitem a própria folha." if config.estagiarios_emitem_folha
                             else "Agora os estagiários só baixam a folha que você enviar.")
            return redirect(request.get_full_path())
        if request.method == "POST" and request.POST.get("acao") == "enviar" and envio.is_valid():
            d = envio.cleaned_data
            arq = d["arquivo"]
            folha = FolhaEnviada(mes=d["mes"], turma=d["turma"], observacao=d["observacao"], enviado_por=user,
                                 nome_original=arq.name[:255])
            folha.arquivo.save(f"folha.{envio.extensao}", arq, save=False)
            folha.save()
            if d["estagios"]:
                folha.estagios.set(d["estagios"])
            alvo = list(folha.estagios_alvo().filter(ativo=True).select_related("estagiario"))
            notificar([e.estagiario for e in alvo], f"Sua folha de frequência de {MESES[d['mes'].month].lower()} está "
                      "disponível para baixar.", reverse("minhas_folhas", args=[alvo[0].pk]) if len(alvo) == 1 else "/",
                      exceto=user)
            messages.success(request, f"Folha de {MESES[d['mes'].month].lower()}/{d['mes'].year} enviada para "
                             f"{len(alvo)} estagiário(s).")
            return redirect(f"{reverse('frequencias')}?mes={d['mes']:%Y-%m}")

    logs = ImpressaoFrequencia.objects.filter(estagio__in=estagios, mes=inicio_mes)
    for e in estagios:
        meus = logs.filter(estagio=e)
        do_aluno = meus.filter(usuario=e.estagiario)
        dados = do_aluno.aggregate(impressoes=Sum("impressoes"), ultima=Max("ultima_impressao"))
        e.aberturas_aluno = do_aluno.filter(folha_enviada__isnull=True).count()
        e.downloads_aluno = do_aluno.filter(folha_enviada__isnull=False).count()
        e.impressoes_aluno = dados["impressoes"] or 0
        e.ultima_aluno = dados["ultima"]
        e.impressoes_outros = meus.exclude(usuario=e.estagiario).aggregate(s=Sum("impressoes"))["s"] or 0
        e.situacao_folha = ("impressa" if e.impressoes_aluno else "baixada" if e.downloads_aluno
                            else "aberta" if e.aberturas_aluno else "nao")
    ordem = {"nao": 0, "aberta": 1, "baixada": 2, "impressa": 3}
    estagios.sort(key=lambda e: (ordem[e.situacao_folha], str(e.estagiario)))

    busca = request.GET.get("codigo", "").strip().upper()
    encontrado = None
    if busca:
        encontrado = ImpressaoFrequencia.objects.select_related("estagio__estagiario", "usuario").filter(
            codigo=busca).first()
        if encontrado and not (eh_orientador_do(user, encontrado.estagio)
                               or eh_supervisor_do(user, encontrado.estagio)):
            encontrado = None

    enviadas = FolhaEnviada.objects.filter(mes=inicio_mes)
    if not user.is_superuser:
        enviadas = enviadas.filter(Q(enviado_por=user) | Q(estagios__in=estagios) | Q(turma__in=turmas))
    detalhes = (logs.filter(Q(impressoes__gt=0) | Q(usuario__papel=Usuario.Papel.ESTAGIARIO))
                .select_related("estagio__estagiario", "usuario")[:200])
    return render(request, "core/frequencias.html", {
        **(contexto_ano(request, ano_lista) if not user.is_supervisor else {}),
        "estagios": estagios, "nav": _nav_mes(ano, mes), "busca": busca, "encontrado": encontrado,
        "detalhes": detalhes, "config": config, "pode_folhas": pode_folhas, "envio": envio,
        "enviadas": enviadas.distinct().select_related("turma__curso", "enviado_por").prefetch_related("estagios__estagiario"),
        "turmas": turmas, "filtro_turma": filtro_turma, "locais": {e.local for e in estagios if e.local},
        "contagem": {k: sum(1 for e in estagios if e.situacao_folha == k) for k in ordem},
    })
