"""Feedback mensal do supervisor: meses abertos, quem está pendente e o lembrete do dia 20."""
import calendar
from datetime import date

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from .models import Configuracao, Estagio, Feedback
from .services import notificar

DIA_LEMBRETE = 20
DIAS_PARA_O_MES_ANTERIOR = 10  # até o dia 10, ainda dá para dar o feedback do mês passado
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro"]


def inicio_mes(d):
    return date(d.year, d.month, 1)


def mes_anterior(m):
    return date(m.year - 1, 12, 1) if m.month == 1 else date(m.year, m.month - 1, 1)


def nome_mes(m):
    return f"{MESES[m.month - 1]} de {m.year}"


def meses_abertos(hoje=None):
    """Meses em que o supervisor ainda pode registrar ou editar o feedback (o atual e, no começo do mês, o anterior)."""
    hoje = hoje or timezone.localdate()
    atual = inicio_mes(hoje)
    return [atual, mes_anterior(atual)] if hoje.day <= DIAS_PARA_O_MES_ANTERIOR else [atual]


def estagios_no_mes(qs, mes):
    """Estágios ativos que já tinham começado no mês."""
    fim = date(mes.year, mes.month, calendar.monthrange(mes.year, mes.month)[1])
    return qs.filter(ativo=True, data_inicio__lte=fim)


def pendentes(estagios, mes):
    feitos = set(Feedback.objects.filter(estagio__in=estagios, mes=mes).values_list("estagio_id", flat=True))
    return [e for e in estagios if e.pk not in feitos]


def pendentes_do_supervisor(usuario, hoje=None):
    mes = inicio_mes(hoje or timezone.localdate())
    estagios = list(estagios_no_mes(Estagio.objects.filter(supervisor=usuario), mes).select_related("estagiario"))
    return pendentes(estagios, mes)


def ultimos(estagios):
    """{estagio_id: feedback mais recente}."""
    resultado = {}
    for f in Feedback.objects.filter(estagio__in=estagios).order_by("estagio_id", "-mes"):
        resultado.setdefault(f.estagio_id, f)
    return resultado


def disparar_lembrete(agora=None):
    """A partir do dia 20, uma vez por mês: avisa cada supervisor dos estagiários ainda sem feedback."""
    agora = timezone.localtime(agora)
    cfg = Configuracao.atual()
    if not cfg.feedback_mensal or agora.day < DIA_LEMBRETE:
        return 0
    mes = inicio_mes(agora.date())
    marco = timezone.make_aware(timezone.datetime(mes.year, mes.month, DIA_LEMBRETE))
    reservado = Configuracao.objects.filter(pk=cfg.pk).filter(
        Q(lembrete_feedback_em__isnull=True) | Q(lembrete_feedback_em__lt=marco)).update(lembrete_feedback_em=agora)
    if not reservado:
        return 0
    estagios = list(estagios_no_mes(Estagio.objects.exclude(supervisor=None), mes).select_related("estagiario", "supervisor"))
    por_supervisor = {}
    for e in pendentes(estagios, mes):
        por_supervisor.setdefault(e.supervisor, []).append(e.estagiario.primeiro_nome)
    for sup, nomes in por_supervisor.items():
        if not sup.is_active:
            continue
        lista = ", ".join(nomes[:6]) + (f" e mais {len(nomes) - 6}" if len(nomes) > 6 else "")
        notificar([sup], f"Falta o feedback de {MESES[mes.month - 1]} sobre {lista}. Leva 2 minutos.",
                  reverse("painel_supervisor") + "#feedback")
    return len(por_supervisor)
