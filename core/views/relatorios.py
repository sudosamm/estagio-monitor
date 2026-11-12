"""Relatório geral da turma: situação de cada estagiário numa página A4 (deitada), pronta para salvar em PDF."""
from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from ..models import Agendamento, Configuracao, Registro, Turma
from ..services import estagios_visiveis, resumo_horas, status_periodo
from .base import orientador_requerido

LIMITE_FALTAS = 3
LIMITE_SEM_REGISTRO = 3


@orientador_requerido
def relatorio_turma(request, pk):
    turma = get_object_or_404(Turma.objects.select_related("curso"), pk=pk)
    if request.user.is_coordenador and not request.user.coordena(turma.curso_id):
        raise PermissionDenied
    hoje = timezone.localdate()
    ontem = hoje - timedelta(days=1)
    estagios = list(
        estagios_visiveis(request.user).filter(turma=turma).prefetch_related("escalas")
        .annotate(
            n_visitas=Count("agendamentos", filter=Q(agendamentos__status=Agendamento.Status.REALIZADO), distinct=True),
            n_pendentes=Count("registros", filter=Q(registros__confirmacao=Registro.Confirmacao.PENDENTE,
                                                     registros__situacao=Registro.Situacao.PRESENTE), distinct=True),
        )
        .order_by("-ativo", "estagiario__nome_completo")
    )
    linhas, atencao = [], []
    tot = {"ativos": 0, "concluidos": 0, "faltas": 0, "sem_registro": 0, "pendentes": 0, "visitas": 0, "atrasados": 0, "pct": 0}
    for e in estagios:
        r = resumo_horas(e)
        sem_registro = 0
        inicio = max(e.data_inicio, e.acompanhamento_desde or e.data_inicio)
        if e.ativo and inicio <= ontem:
            sem_registro = sum(1 for s in status_periodo(e, inicio, ontem, hoje=hoje, limite=r["previsao_termino"])
                               if s.codigo == "sem_registro")
        concluido = r["pct"] >= 100
        if not e.ativo:
            situacao = "Encerrado"
        elif concluido:
            situacao = "Carga cumprida"
        elif r["apos_termo"]:
            situacao = "Termina após o termo"
        else:
            situacao = "Em andamento"
        linhas.append({"e": e, "r": r, "sem_registro": sem_registro, "situacao": situacao})
        if e.ativo:
            tot["ativos"] += 1
            tot["pct"] += r["pct"]
            tot["concluidos"] += concluido
            tot["atrasados"] += bool(r["apos_termo"]) and not concluido
        tot["faltas"] += r["faltas"]
        tot["sem_registro"] += sem_registro
        tot["pendentes"] += e.n_pendentes
        tot["visitas"] += e.n_visitas
        if e.ativo:
            motivos = []
            if not e.local_id:
                motivos.append("sem concedente")
            if not e.supervisor_id:
                motivos.append("sem supervisor")
            if r["apos_termo"] and not concluido:
                motivos.append(f"previsão de término ({r['previsao_termino']:%d/%m/%Y}) depois do fim do termo "
                               f"({e.data_fim:%d/%m/%Y}): renovar o termo ou repor horas")
            if r["faltas"] >= LIMITE_FALTAS:
                motivos.append(f"{r['faltas']} faltas")
            if sem_registro >= LIMITE_SEM_REGISTRO:
                motivos.append(f"{sem_registro} dias sem registro de presença")
            if e.n_pendentes:
                motivos.append(f"{e.n_pendentes} presença{'s' if e.n_pendentes > 1 else ''} aguardando o supervisor")
            if not e.n_visitas:
                motivos.append("nenhuma visita ou conversa realizada")
            if motivos:
                atencao.append((e, motivos))
    tot["pct_medio"] = round(tot["pct"] / tot["ativos"], 1) if tot["ativos"] else 0
    orientadores = sorted({e.orientador.nome_completo for e in estagios})
    return render(request, "core/relatorio_turma.html", {
        "turma": turma, "linhas": linhas, "atencao": atencao, "tot": tot, "hoje": hoje, "agora": timezone.localtime(),
        "orientadores": orientadores, "config": Configuracao.atual(),
        "limite_faltas": LIMITE_FALTAS, "limite_sem_registro": LIMITE_SEM_REGISTRO,
    })
