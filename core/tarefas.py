"""Tarefas com hora marcada, escola por escola.

Cada escola ativa roda as suas tarefas com a própria configuração e o próprio fuso horário (resumo semanal, lembretes
de feedback, avaliações e fim de expediente, "Confirmar todas", resumo do mês dos supervisores). As limpezas
(registro de ações e sessões) são da plataforma e rodam uma vez.

Disparo: pelas Scheduled Tasks do Coolify (``python manage.py tarefas_periodicas``, a cada 10 ou 15 minutos) e,
como reserva, pelo próprio movimento do sistema (``ResumoSemanalMiddleware``). As duas formas podem conviver: cada
tarefa "reserva" o envio na configuração da escola, então nada sai duas vezes.
"""
import logging

from django.utils import timezone

log = logging.getLogger("core.tarefas")


def tarefas_da_escola():
    from . import confirmacao, lembretes
    from .acompanhamento import disparar_resumo_se_preciso
    from .avaliacoes import disparar_lembrete as lembrete_avaliacoes
    from .feedback import disparar_lembrete as lembrete_feedback

    return (disparar_resumo_se_preciso, lembrete_feedback, lembrete_avaliacoes,
            lembretes.disparar_lembretes_expediente, confirmacao.disparar_confirmacoes,
            confirmacao.disparar_resumo_mensal)


def tarefas_da_plataforma():
    from . import auditoria, sessoes

    return (auditoria.limpar_antigos, sessoes.limpar_antigas)


def _rodar(tarefa, rotulo):
    try:
        tarefa()
        return True
    except Exception:  # noqa: BLE001 — uma tarefa que falha não impede as outras (o erro chega aos administradores)
        log.exception("Falha na tarefa %s (%s)", tarefa.__name__, rotulo)
        return False


def rodar_tarefas():
    """Roda todas as tarefas de todas as escolas ativas. Devolve {escola: [falhas]}."""
    from escolas.escopo import escola_ativa, todas_as_escolas
    from escolas.models import Escola

    falhas = {}
    with todas_as_escolas():
        escolas = list(Escola.objects.exclude(situacao=Escola.Situacao.INATIVA).select_related("rede"))
    for escola in escolas:
        with escola_ativa(escola), timezone.override(escola.fuso_efetivo):
            falhas[escola.slug] = [t.__name__ for t in tarefas_da_escola() if not _rodar(t, escola.slug)]
    with todas_as_escolas():
        falhas["plataforma"] = [t.__name__ for t in tarefas_da_plataforma() if not _rodar(t, "plataforma")]
    return falhas
