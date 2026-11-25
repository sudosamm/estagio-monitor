"""Mapa dos estágios (gestão): situação do dia em cada concedente."""
from datetime import date, timedelta

from django.shortcuts import render
from django.utils import timezone

from .. import mapa
from ..models import Curso, Turma
from ..seguranca import chave_texto
from ..services import estagios_visiveis
from .base import permissao


def _dia(request):
    try:
        return date.fromisoformat(request.GET.get("data", ""))
    except ValueError:
        return timezone.localdate()


@permissao("painel")
def mapa_estagios(request):
    user = request.user
    dia = _dia(request)
    curso, turma, cidade = request.GET.get("curso", ""), request.GET.get("turma", ""), request.GET.get("cidade", "").strip()
    qs = estagios_visiveis(user).filter(ativo=True, local__isnull=False).select_related("estagiario", "local")
    if curso.isdigit():
        qs = qs.filter(curso_id=curso)
    if turma.isdigit():
        qs = qs.filter(turma_id=turma)
    todos = mapa.situacao(qs, dia)
    cidades = sorted({p["cidade"] for p in todos if p["cidade"]}, key=chave_texto)
    locais = [p for p in todos if chave_texto(p["cidade"]) == chave_texto(cidade)] if cidade else todos
    visiveis = estagios_visiveis(user).filter(ativo=True)
    return render(request, "core/mapa.html", {
        "dia": dia, "hoje": timezone.localdate(), "locais": locais, "resumo": mapa.resumo(locais),
        "com_ponto": [p for p in locais if p["lat"] is not None],
        "sem_ponto": [p for p in locais if p["lat"] is None],
        "anterior": (dia - timedelta(days=1)).isoformat(), "proximo": (dia + timedelta(days=1)).isoformat(),
        "cursos": Curso.objects.filter(pk__in=visiveis.values("curso")),
        "turmas": Turma.objects.filter(pk__in=visiveis.values("turma")).select_related("curso"),
        "curso": curso, "turma": turma, "cidade": cidade, "cidades": cidades,
    })
