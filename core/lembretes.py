"""Lembrete de fim de expediente: quem esqueceu de marcar a presença (ou a saída) recebe um aviso no celular e no
sino algum tempo depois do horário de saída da escala. No máximo um por estágio por dia, entre 7h e 22h.

Dispara sozinho com o movimento do sistema (ResumoSemanalMiddleware), sem precisar de agendador.
"""
from datetime import datetime, timedelta

from django.urls import reverse
from django.utils import timezone

HORA_INICIO, HORA_FIM = 7, 22


def saida_prevista(status):
    """Horário de saída do dia (pela escala). Sem saída na escala: entrada + horas do dia (+ intervalo)."""
    esc = status.escala
    if not esc:
        return None
    if esc.horario_saida:
        return esc.horario_saida
    if not esc.horario_entrada:
        return None
    minutos = int(esc.horas_por_dia * 60)
    if esc.saida_intervalo and esc.volta_intervalo:
        minutos += (esc.volta_intervalo.hour * 60 + esc.volta_intervalo.minute) - (
            esc.saida_intervalo.hour * 60 + esc.saida_intervalo.minute)
    base = datetime.combine(status.data, esc.horario_entrada) + timedelta(minutes=minutos)
    return base.time() if base.date() == status.data else None


def texto_do_lembrete(status):
    """O que falta no dia, ou "" se nada falta."""
    r = status.registro
    if status.codigo == "hoje":
        return "Você ainda não marcou a presença de hoje. Se foi ao estágio, marque agora; se não foi, informe a ausência."
    if r and r.situacao == r.Situacao.PRESENTE and r.hora_chegada and not r.hora_saida:
        return "Faltou marcar a saída de hoje no estágio. Toque para completar os horários."
    return ""


def _concluiu(estagio):
    from decimal import Decimal

    t = getattr(estagio, "_lote_totais", None) or {}
    feitas = (t.get("confirmadas") or Decimal(0)) + (t.get("pendentes") or Decimal(0)) + estagio.horas_anteriores
    return feitas >= estagio.carga_horaria_total


def disparar_lembretes_expediente(agora=None):
    from .models import Configuracao, Estagio
    from .services import notificar, preparar_lote, status_periodo

    config = Configuracao.atual()
    agora = timezone.localtime(agora or timezone.now())
    if not config.lembrete_expediente or not (HORA_INICIO <= agora.hour < HORA_FIM):
        return 0
    hoje = agora.date()
    qs = (Estagio.objects.filter(ativo=True, estagiario__is_active=True, estagiario__lembrete_expediente=True,
                                 data_inicio__lte=hoje)
          .exclude(lembrete_em=hoje).select_related("estagiario", "local", "curso"))
    estagios = preparar_lote(list(qs), hoje)
    limite = timedelta(minutes=config.lembrete_minutos)
    avisados = []
    for e in estagios:
        if _concluiu(e):
            continue
        st = status_periodo(e, hoje, hoje, hoje)[0]
        texto = texto_do_lembrete(st)
        saida = saida_prevista(st) if texto else None
        if not saida or agora.replace(tzinfo=None) < datetime.combine(hoje, saida) + limite:
            continue
        notificar([e.estagiario], texto, reverse("estagio_detalhe", args=[e.pk]), email=False)
        avisados.append(e.pk)
    if avisados:
        Estagio.objects.filter(pk__in=avisados).update(lembrete_em=hoje)
    return len(avisados)
