"""Folha de frequência oficial (só impressão) e o registro de quem abriu/imprimiu.

O registro nunca aparece para estagiários: só orientador e supervisor do estágio o veem.
"""
from datetime import date

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Max, Q, Sum
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import Configuracao, ImpressaoFrequencia, Usuario
from ..services import estagios_visiveis, linhas_folha
from .base import eh_orientador_do, eh_supervisor_do, pegar_estagio
from .estagio import MESES, _mes_param, _nav_mes


def _ip(request):
    return (request.META.get("HTTP_CF_CONNECTING_IP")
            or request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
            or request.META.get("REMOTE_ADDR")) or None


@login_required
def folha_frequencia(request, pk):
    estagio = pegar_estagio(request, pk)
    ano, mes = _mes_param(request)
    log = ImpressaoFrequencia.objects.create(
        estagio=estagio, usuario=request.user, mes=date(ano, mes, 1), ip=_ip(request),
        navegador=request.META.get("HTTP_USER_AGENT", "")[:255],
    )
    resposta = render(request, "core/folha_frequencia.html", {
        "estagio": estagio, "nav": _nav_mes(ano, mes), "mes_nome": MESES[mes], "ano": ano,
        "linhas": linhas_folha(estagio, ano, mes), "config": Configuracao.atual(), "log": log,
        "agora": timezone.localtime(),
    })
    resposta["Cache-Control"] = "no-store"
    return resposta


@login_required
@require_POST
def marcar_impressao(request):
    """Chamado pelo navegador quando a folha vai para a impressora (inclui “Salvar como PDF”)."""
    codigo = request.POST.get("codigo", "")
    n = ImpressaoFrequencia.objects.filter(codigo=codigo, usuario=request.user).first()
    if not n:
        return HttpResponseBadRequest()
    n.impressoes += 1
    n.ultima_impressao = timezone.now()
    n.save(update_fields=["impressoes", "ultima_impressao"])
    return HttpResponse(status=204)


def resumo_impressoes(estagio, limite=8):
    """Últimas aberturas da folha (para o card do orientador/supervisor)."""
    return estagio.impressoes.select_related("usuario")[:limite]


@login_required
def frequencias_painel(request):
    """Quem já abriu e imprimiu a folha de um mês, e busca pelo código impresso no rodapé."""
    if not (request.user.pode("frequencias") or request.user.is_supervisor):
        raise PermissionDenied
    ano, mes = _mes_param(request)
    inicio_mes = date(ano, mes, 1)
    estagios = list(estagios_visiveis(request.user).filter(ativo=True))
    logs = ImpressaoFrequencia.objects.filter(estagio__in=estagios, mes=inicio_mes)
    por_estagio = {}
    for e in estagios:
        meus = logs.filter(estagio=e)
        do_aluno = meus.filter(usuario=e.estagiario)
        dados = do_aluno.aggregate(impressoes=Sum("impressoes"), ultima=Max("ultima_impressao"))
        e.aberturas_aluno = do_aluno.count()
        e.impressoes_aluno = dados["impressoes"] or 0
        e.ultima_aluno = dados["ultima"]
        e.impressoes_outros = meus.exclude(usuario=e.estagiario).aggregate(s=Sum("impressoes"))["s"] or 0
        e.situacao_folha = ("impressa" if e.impressoes_aluno else "aberta" if e.aberturas_aluno else "nao")
        por_estagio[e.pk] = e
    ordem = {"nao": 0, "aberta": 1, "impressa": 2}
    estagios.sort(key=lambda e: (ordem[e.situacao_folha], str(e.estagiario)))

    busca = request.GET.get("codigo", "").strip().upper()
    encontrado = None
    if busca:
        encontrado = ImpressaoFrequencia.objects.select_related("estagio__estagiario", "usuario").filter(
            codigo=busca).first()
        if encontrado and not (eh_orientador_do(request.user, encontrado.estagio)
                               or eh_supervisor_do(request.user, encontrado.estagio)):
            encontrado = None

    detalhes = (logs.filter(Q(impressoes__gt=0) | Q(usuario__papel=Usuario.Papel.ESTAGIARIO))
                .select_related("estagio__estagiario", "usuario")[:200])
    return render(request, "core/frequencias.html", {
        "estagios": estagios, "nav": _nav_mes(ano, mes), "busca": busca, "encontrado": encontrado,
        "detalhes": detalhes,
        "contagem": {k: sum(1 for e in estagios if e.situacao_folha == k) for k in ordem},
    })
