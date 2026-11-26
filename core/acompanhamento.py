"""Situação de cada estágio (horas, faltas, dias sem registro, pontos de atenção).

Usado pelo relatório da turma (PDF), pela exportação em planilha e pelo resumo semanal por e-mail,
para que os três mostrem sempre os mesmos números.
"""
import logging
from datetime import datetime, time, timedelta

from django.conf import settings
from .threads import iniciar_thread
from django.db.models import Count, Q
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import Agendamento, Configuracao, Registro, Usuario
from .services import (
    ano_referencia, email_ativo, estagios_visiveis, filtrar_ano, preparar_lote, resumo_horas, status_periodo,
)

LIMITE_FALTAS = 3
LIMITE_SEM_REGISTRO = 3
PERTO_DE_CONCLUIR = 90  # % da carga
TERMO_VENCENDO_DIAS = 30

log = logging.getLogger("core.resumo")


def com_contagens(qs):
    """Acrescenta n_visitas (realizadas) e n_pendentes (presenças aguardando o supervisor)."""
    return qs.annotate(
        n_visitas=Count("agendamentos", filter=Q(agendamentos__status=Agendamento.Status.REALIZADO), distinct=True),
        n_pendentes=Count("registros", filter=Q(registros__confirmacao=Registro.Confirmacao.PENDENTE,
                                                 registros__situacao=Registro.Situacao.PRESENTE), distinct=True),
    )


def situacao_estagio(e, hoje=None, pasta=None, feedback=None):
    """Linha do relatório: {e, r (resumo_horas), sem_registro, situacao, motivos}. Precisa de com_contagens()."""
    hoje = hoje or timezone.localdate()
    if pasta is None:
        from .pasta import pasta_do_estagio

        pasta = pasta_do_estagio(e, hoje)
    docs_atrasados = [i.tipo.nome for i in pasta if i.tipo.obrigatorio and i.codigo in ("atrasado", "recusado")]
    ontem = hoje - timedelta(days=1)
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
    motivos = []
    if e.ativo:
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
    if docs_atrasados:
        motivos.append("documentos da pasta atrasados: " + ", ".join(docs_atrasados))
    if e.ativo and feedback and feedback.media and feedback.media < 3:
        motivos.append(f"último feedback do supervisor abaixo de “bom” ({str(feedback.media).replace('.', ',')} em "
                       f"{feedback.mes:%m/%Y})")
    return {"e": e, "r": r, "sem_registro": sem_registro, "situacao": situacao, "concluido": concluido,
            "motivos": motivos, "docs_atrasados": docs_atrasados, "pasta": pasta, "feedback": feedback}


def consolidar(estagios, hoje=None):
    """(linhas, atencao, totais) de uma lista de estágios já anotada com com_contagens()."""
    hoje = hoje or timezone.localdate()
    linhas, atencao = [], []
    tot = {"ativos": 0, "concluidos": 0, "faltas": 0, "sem_registro": 0, "pendentes": 0, "visitas": 0, "atrasados": 0,
           "pct": 0}
    from .pasta import pastas

    from .feedback import ultimos

    todas = pastas(estagios, hoje)
    feedbacks = ultimos(estagios)
    if estagios:
        preparar_lote(estagios, min(min(max(e.data_inicio, e.acompanhamento_desde or e.data_inicio) for e in estagios),
                                    hoje))
    for e in estagios:
        linha = situacao_estagio(e, hoje, todas[e.pk], feedbacks.get(e.pk))
        r = linha["r"]
        linhas.append(linha)
        if e.ativo:
            tot["ativos"] += 1
            tot["pct"] += r["pct"]
            tot["concluidos"] += linha["concluido"]
            tot["atrasados"] += bool(r["apos_termo"]) and not linha["concluido"]
            if linha["motivos"]:
                atencao.append((e, linha["motivos"]))
        tot["faltas"] += r["faltas"]
        tot["sem_registro"] += linha["sem_registro"]
        tot["pendentes"] += e.n_pendentes
        tot["visitas"] += e.n_visitas
    tot["pct_medio"] = round(tot["pct"] / tot["ativos"], 1) if tot["ativos"] else 0
    return linhas, atencao, tot


# ---------------------------------------------------------------- resumo semanal


def destinatarios_resumo():
    """Orientadores e coordenadores ativos, com e-mail, que não desligaram o resumo nem os avisos por e-mail."""
    return (Usuario.objects.filter(is_active=True, resumo_semanal=True, avisos_email=True)
            .filter(Q(papel__in=[Usuario.Papel.ORIENTADOR, Usuario.Papel.COORDENADOR]) | Q(is_superuser=True))
            .exclude(email=""))


def resumo_semanal(usuario, hoje=None):
    """Pontos de atenção da semana dos estagiários que a pessoa acompanha (turmas do ano de referência)."""
    hoje = hoje or timezone.localdate()
    semana = hoje - timedelta(days=7)
    ontem = hoje - timedelta(days=1)
    qs = filtrar_ano(estagios_visiveis(usuario).filter(ativo=True), ano_referencia())
    estagios = preparar_lote(com_contagens(qs.select_related("turma")).order_by("estagiario__nome_completo"), semana)
    s = {"sem_registro": [], "faltas": [], "a_validar": [], "termo_vencendo": [], "apos_termo": [], "quase": [],
         "concluidos": []}
    faltas = {}
    for reg in Registro.objects.filter(estagio__in=estagios, situacao=Registro.Situacao.FALTA,
                                       data__gte=semana, data__lte=ontem).order_by("data"):
        faltas.setdefault(reg.estagio_id, []).append(reg.data)
    a_validar = dict(
        Registro.objects.filter(estagio__in=estagios, situacao=Registro.Situacao.PRESENTE,
                                confirmacao=Registro.Confirmacao.PENDENTE, data__lt=hoje - timedelta(days=2))
        .exclude(justificativa__status="PENDENTE").values_list("estagio").annotate(n=Count("pk"))
    )
    for e in estagios:
        r = resumo_horas(e)
        inicio = max(semana, e.data_inicio, e.acompanhamento_desde or e.data_inicio)
        if inicio <= ontem:
            dias = [d.data for d in status_periodo(e, inicio, ontem, hoje=hoje, limite=r["previsao_termino"])
                    if d.codigo == "sem_registro"]
            if dias:
                s["sem_registro"].append((e, dias))
        if e.pk in faltas:
            s["faltas"].append((e, faltas[e.pk]))
        if a_validar.get(e.pk):
            s["a_validar"].append((e, a_validar[e.pk]))
        concluido = r["pct"] >= 100
        if concluido:
            s["concluidos"].append((e, r))
        elif r["pct"] >= PERTO_DE_CONCLUIR:
            s["quase"].append((e, r))
        if not concluido and e.data_fim and hoje <= e.data_fim <= hoje + timedelta(days=TERMO_VENCENDO_DIAS):
            s["termo_vencendo"].append((e, r))
        elif not concluido and r["apos_termo"]:
            s["apos_termo"].append((e, r))

    agenda = Agendamento.objects.select_related("local").prefetch_related("estagios__estagiario")
    if not usuario.is_superuser:
        agenda = agenda.filter(orientador=usuario)
    agora = timezone.now()
    s["visitas"] = list(agenda.filter(status=Agendamento.Status.AGENDADO, data_hora__gte=agora,
                                      data_hora__lt=agora + timedelta(days=7)).order_by("data_hora"))
    s["solicitacoes"] = list(agenda.filter(status=Agendamento.Status.SOLICITADO).order_by("criado_em"))
    from .atestados import pendentes_para

    s["atestados"] = pendentes_para(usuario, estagios)
    from .pasta import pastas

    s["docs_conferir"], s["docs_atrasados"] = [], []
    todas = pastas(estagios, hoje)
    for e in estagios:
        for i in todas[e.pk]:
            if i.codigo == "enviado":
                s["docs_conferir"].append((e, i))
            elif i.tipo.obrigatorio and i.codigo in ("atrasado", "recusado"):
                s["docs_atrasados"].append((e, i))
    tem_algo = any(s[k] for k in s)
    return {"secoes": s, "total": len(estagios), "hoje": hoje, "desde": semana, "ate": ontem, "tem_algo": tem_algo}


def mensagem_resumo(usuario, dados):
    """(assunto, corpo, remetente, [destinatário]) no formato de send_mass_mail."""
    corpo = render_to_string("emails/resumo_semanal.txt", {
        "u": usuario, "d": dados, "s": dados["secoes"], "site": settings.SITE_URL,
        "NOME_SISTEMA": settings.NOME_SISTEMA, "link_resumo": reverse("resumo_semanal"),
    })
    corpo = "\n".join(linha.rstrip() for linha in corpo.splitlines())
    while "\n\n\n" in corpo:
        corpo = corpo.replace("\n\n\n", "\n\n")
    assunto = f"[{settings.NOME_SISTEMA}] Resumo da semana — {dados['hoje']:%d/%m}"
    return (assunto, corpo.strip() + "\n", settings.DEFAULT_FROM_EMAIL, [usuario.email])


def enviar_resumos(hoje=None, usuarios=None):
    """Monta e envia o resumo de cada destinatário. Quem não tem nada a relatar não recebe. Devolve quantos foram."""
    usuarios = destinatarios_resumo() if usuarios is None else usuarios
    mensagens = []
    for u in usuarios:
        dados = resumo_semanal(u, hoje)
        if dados["tem_algo"]:
            mensagens.append(mensagem_resumo(u, dados))
    if mensagens:
        from django.core.mail import send_mass_mail

        send_mass_mail(mensagens, fail_silently=False)
    return len(mensagens)


def inicio_da_semana(agora=None):
    """Segunda-feira, 6h (horário local), da semana em curso."""
    agora = timezone.localtime(agora)
    segunda = agora.date() - timedelta(days=agora.weekday())
    return timezone.make_aware(datetime.combine(segunda, time(6)))


def resumo_pendente(agora=None):
    agora = timezone.localtime(agora)
    marco = inicio_da_semana(agora)
    if agora < marco:
        marco -= timedelta(days=7)
    cfg = Configuracao.atual()
    return cfg.resumo_semanal and email_ativo() and (cfg.resumo_enviado_em is None or cfg.resumo_enviado_em < marco), marco


def disparar_resumo_se_preciso(agora=None):
    """Envia o resumo da semana uma única vez, no primeiro acesso ao sistema depois de segunda, 6h.

    Funciona sem agendador (cron). Com vários processos do servidor, só um consegue “reservar” o envio.
    """
    pendente, marco = resumo_pendente(agora)
    if not pendente:
        return False
    reservado = Configuracao.objects.filter(pk=1).filter(
        Q(resumo_enviado_em__isnull=True) | Q(resumo_enviado_em__lt=marco)
    ).update(resumo_enviado_em=timezone.now())
    if not reservado:
        return False

    def enviar():
        try:
            n = enviar_resumos()
            log.info("Resumo semanal enviado para %d pessoa(s)", n)
        except Exception:  # noqa: BLE001 — falha no e-mail não pode derrubar o sistema; tenta de novo na próxima semana
            log.exception("Falha ao enviar o resumo semanal")

    if settings.EMAIL_ASSINCRONO:
        iniciar_thread(enviar)
    else:
        enviar()
    return True

