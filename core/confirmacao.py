"""Supervisor confirma as presenças sem entrar no sistema (link de uso único por e-mail ou WhatsApp) e recebe o
resumo do mês.

O link só mostra a lista; a confirmação acontece num botão (POST), para que os antivírus de e-mail, que abrem os
links sozinhos, não confirmem nada. Vale 7 dias e uma vez só, e só confirma o que ainda estiver pendente e ainda
for daquele supervisor. Contestar um dia continua exigindo entrar no sistema.
"""
import hashlib
import re
import secrets
from datetime import datetime, time, timedelta
from urllib.parse import quote

from django.urls import reverse
from django.utils import timezone

from escolas.pessoas import na_escola

VALIDADE = timedelta(days=7)
HORA_SEMANAL = 14     # e-mail da semana a partir das 14h do dia escolhido
HORA_MENSAL = 7       # resumo do mês a partir das 7h do dia 1º
DIAS_ABREV = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
MESES = ["", "janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro"]


def _resumo(codigo):
    return hashlib.sha256(codigo.encode()).hexdigest()


def pendentes_do_supervisor(supervisor):
    from .models import Justificativa, Registro

    return (Registro.objects.filter(estagio__supervisor=supervisor, estagio__ativo=True,
                                    confirmacao=Registro.Confirmacao.PENDENTE, data__lte=timezone.localdate())
            .exclude(justificativa__status=Justificativa.Status.PENDENTE)
            .select_related("estagio__estagiario").order_by("estagio__estagiario__nome_completo", "data"))


def criar_link(supervisor, registros, canal="EMAIL", criado_por=None):
    """Devolve o código do link (só existe aqui: no banco fica o resumo SHA-256)."""
    from .models import LinkConfirmacao

    codigo = secrets.token_urlsafe(24)
    LinkConfirmacao.objects.create(resumo=_resumo(codigo), supervisor=supervisor, registros=[r.pk for r in registros],
                                   canal=canal, criado_por=criado_por, expira_em=timezone.now() + VALIDADE)
    return codigo


def link_do_codigo(codigo):
    from .models import LinkConfirmacao

    if not codigo or len(codigo) > 64:
        return None
    # link público (sem login): procurado em todas as escolas; a tela trabalha na escola do link
    return (LinkConfirmacao.objects.todas_as_escolas().select_related("supervisor", "escola")
            .filter(resumo=_resumo(codigo)).first())


def situacao(link):
    """'ok', 'usado', 'vencido' ou 'invalido'."""
    if link is None or not link.supervisor.is_active:
        return "invalido"
    if link.usado_em:
        return "usado"
    if link.expira_em < timezone.now():
        return "vencido"
    return "ok"


def registros_do_link(link):
    """O que o link ainda pode confirmar: pendente, sem atestado em análise e ainda do mesmo supervisor."""
    from .models import Justificativa, Registro

    return (Registro.objects.filter(pk__in=link.registros, estagio__supervisor=link.supervisor,
                                    confirmacao=Registro.Confirmacao.PENDENTE)
            .exclude(justificativa__status=Justificativa.Status.PENDENTE)
            .select_related("estagio__estagiario").order_by("estagio__estagiario__nome_completo", "data"))


def confirmar_pelo_link(link, request=None):
    from django.db import transaction

    from . import auditoria
    from .models import HistoricoRegistro, Registro
    from .services import notificar

    sup = link.supervisor
    with transaction.atomic():
        regs = list(registros_do_link(link))
        por_estagiario = {}
        for reg in regs:
            reg.confirmar(sup, Registro.Confirmacao.CONFIRMADA)
            reg.anotar(sup, HistoricoRegistro.Acao.LINK, request).save()
            por_estagiario.setdefault(reg.estagio, []).append(reg.data)
        link.usado_em, link.confirmados = timezone.now(), len(regs)
        link.save(update_fields=["usado_em", "confirmados"])
    for estagio, dias in por_estagiario.items():
        texto = (f"Seu registro de {dias[0]:%d/%m} foi confirmado pelo supervisor." if len(dias) == 1 else
                 f"{len(dias)} registros seus ({dias[0]:%d/%m} a {dias[-1]:%d/%m}) foram confirmados pelo supervisor.")
        notificar([estagio.estagiario], texto, estagio.get_absolute_url())
    auditoria.registrar(request, "CONFIRMACAO", f"Confirmou {len(regs)} presença(s) pelo link "
                        f"({link.get_canal_display()})", usuario=sup)
    return len(regs)


def linha(reg):
    dia = f"{DIAS_ABREV[reg.data.weekday()]} {reg.data:%d/%m}"
    if reg.situacao == reg.Situacao.PRESENTE:
        detalhe = (reg.horario_display + " " if reg.horario_display else "") + f"({_horas(reg.horas)})"
    else:
        detalhe = reg.get_situacao_display().lower()
    return f"• {reg.estagio.estagiario.nome_completo} — {dia}, {detalhe}"


def _horas(valor):
    v = float(valor or 0)
    return f"{int(v)}h" if v == int(v) else f"{v:.1f}h".replace(".", ",")


def lista_texto(registros, maximo=40):
    linhas = [linha(r) for r in registros[:maximo]]
    if len(registros) > maximo:
        linhas.append(f"… e mais {len(registros) - maximo}.")
    return "\n".join(linhas)


def endereco(codigo, request=None):
    from . import emails

    return emails.endereco(request, reverse("confirmar_por_link", args=[codigo]))


def enviar_email(supervisor, request=None, criado_por=None):
    """Manda o e-mail com a lista e o link. Devolve quantas presenças foram no link (0 = nada enviado)."""
    from . import emails

    regs = list(pendentes_do_supervisor(supervisor))
    if not regs or not supervisor.email or not supervisor.is_active:
        return 0
    codigo = criar_link(supervisor, regs, "EMAIL", criado_por)
    ok = emails.enviar("CONFIRMAR_PRESENCAS", [supervisor.email], nome=supervisor.primeiro_nome, quantidade=len(regs),
                       lista=lista_texto(regs), link=endereco(codigo, request), validade="7 dias")
    return len(regs) if ok else 0


def telefone_whatsapp(telefone):
    """Número no formato do wa.me (55 + DDD + número) ou "" se não parecer um celular brasileiro."""
    digitos = re.sub(r"\D", "", telefone or "")
    if digitos.startswith("0"):
        digitos = digitos.lstrip("0")
    if len(digitos) in (10, 11):
        digitos = "55" + digitos
    return digitos if len(digitos) in (12, 13) and digitos.startswith("55") else ""


def endereco_whatsapp(supervisor, request=None, criado_por=None):
    """wa.me com a mensagem pronta e um link novo (a escola só toca em Enviar no WhatsApp)."""
    regs = list(pendentes_do_supervisor(supervisor))
    numero = telefone_whatsapp(supervisor.telefone)
    if not regs or not numero:
        return ""
    codigo = criar_link(supervisor, regs, "WHATSAPP", criado_por)
    nomes = sorted({r.estagio.estagiario.primeiro_nome for r in regs})
    texto = (f"Olá, {supervisor.primeiro_nome}! Aqui é da escola, sobre o estágio de {', '.join(nomes)}. "
             f"Há {len(regs)} presença(s) esperando a sua confirmação. Para conferir e confirmar todas de uma vez, "
             f"sem senha, abra: {endereco(codigo, request)} (vale 7 dias, uma vez só).")
    return f"https://wa.me/{numero}?text={quote(texto)}"


# ---------------------------------------------------------------- disparos automáticos


def _momento_semanal(agora, dia_semana):
    """Último momento de envio já passado (dia escolhido, 14h) e se ainda está na janela (até o dia seguinte)."""
    hoje = agora.date()
    dias_atras = (hoje.weekday() - dia_semana) % 7
    alvo = timezone.make_aware(datetime.combine(hoje - timedelta(days=dias_atras), time(HORA_SEMANAL)))
    if alvo > agora:
        alvo -= timedelta(days=7)
    return alvo, agora < alvo + timedelta(hours=34)


def disparar_confirmacoes(agora=None):
    """Toda semana, no dia escolhido (a partir das 14h): e-mail “Confirmar todas” para cada supervisor com pendências."""
    from django.conf import settings

    from .models import Configuracao, Usuario

    config = Configuracao.atual()
    if not (settings.EMAIL_ATIVO and config.confirmacao_por_email):
        return 0
    agora = timezone.localtime(agora or timezone.now())
    alvo, na_janela = _momento_semanal(agora, config.dia_confirmacao)
    if not na_janela or (config.confirmacao_enviada_em and config.confirmacao_enviada_em >= alvo):
        return 0
    Configuracao.objects.filter(pk=config.pk).update(confirmacao_enviada_em=agora)  # uma vez só, mesmo com vários processos
    config.confirmacao_enviada_em = agora
    n = 0
    for sup in na_escola(Usuario.objects.filter(papel=Usuario.Papel.SUPERVISOR, is_active=True,
                                                avisos_email=True).exclude(email="")):
        n += 1 if enviar_email(sup) else 0
    return n


def mes_anterior(hoje):
    fim = hoje.replace(day=1) - timedelta(days=1)
    return fim.replace(day=1), fim


def resumo_do_mes(supervisor, inicio, fim):
    """Uma linha por estagiário: presenças, faltas, ausências, horas do mês, total e previsão."""
    from django.db.models import Count, Q, Sum

    from .models import Estagio, Registro
    from .services import preparar_lote, resumo_horas

    estagios = preparar_lote(Estagio.objects.filter(supervisor=supervisor, ativo=True, data_inicio__lte=fim)
                             .select_related("estagiario", "curso"), timezone.localdate())
    if not estagios:
        return []
    P, C = Registro.Situacao, Registro.Confirmacao
    mes = {t.pop("estagio_id"): t for t in Registro.objects.filter(estagio__in=estagios, data__range=(inicio, fim))
           .values("estagio_id").annotate(
               presencas=Count("pk", filter=Q(situacao=P.PRESENTE)), faltas=Count("pk", filter=Q(situacao=P.FALTA)),
               ausencias=Count("pk", filter=Q(situacao=P.AUSENCIA)),
               horas=Sum("horas", filter=Q(situacao=P.PRESENTE) & ~Q(confirmacao=C.CONTESTADA)),
               pendentes=Count("pk", filter=Q(confirmacao=C.PENDENTE)))}
    linhas = []
    for e in estagios:
        m = mes.get(e.pk, {})
        r = resumo_horas(e)
        partes = [f"{m.get('presencas', 0)} presença(s)", f"{_horas(m.get('horas'))} no mês"]
        if m.get("faltas"):
            partes.append(f"{m['faltas']} falta(s)")
        if m.get("ausencias"):
            partes.append(f"{m['ausencias']} ausência(s) informada(s)")
        if m.get("pendentes"):
            partes.append(f"{m['pendentes']} para você confirmar")
        total = f"total {_horas(r['cumpridas'])} de {_horas(r['total'])}"
        prev = (f", previsão de término {r['previsao_termino']:%d/%m/%Y}" if r["previsao_termino"]
                else ", carga horária concluída" if r["faltam"] <= 0 else "")
        linhas.append(f"• {e.estagiario.nome_completo}: {', '.join(partes)} · {total}{prev}")
    return linhas


def disparar_resumo_mensal(agora=None):
    """No dia 1º (a partir das 7h, até o dia 3): resumo do mês anterior para cada supervisor."""
    from django.conf import settings

    from . import emails
    from .models import Configuracao, Usuario

    config = Configuracao.atual()
    if not (settings.EMAIL_ATIVO and config.resumo_mensal_supervisor):
        return 0
    agora = timezone.localtime(agora or timezone.now())
    alvo = timezone.make_aware(datetime.combine(agora.date().replace(day=1), time(HORA_MENSAL)))
    if agora < alvo or agora.day > 3 or (config.resumo_mensal_enviado_em and config.resumo_mensal_enviado_em >= alvo):
        return 0
    Configuracao.objects.filter(pk=config.pk).update(resumo_mensal_enviado_em=agora)
    config.resumo_mensal_enviado_em = agora
    inicio, fim = mes_anterior(agora.date())
    link = f"{settings.SITE_URL}{reverse('painel_supervisor')}"
    n = 0
    for sup in na_escola(Usuario.objects.filter(papel=Usuario.Papel.SUPERVISOR, is_active=True,
                                                avisos_email=True).exclude(email="")):
        linhas = resumo_do_mes(sup, inicio, fim)
        if linhas and emails.enviar("RESUMO_MENSAL_SUPERVISOR", [sup.email], nome=sup.primeiro_nome,
                                    mes=f"{MESES[inicio.month]} de {inicio.year}", lista="\n".join(linhas), link=link):
            n += 1
    return n


def pendencias_por_supervisor(estagios):
    """Para o painel da escola: supervisores com presenças esperando, quantas e desde quando."""
    from django.db.models import Count, Min

    from .models import Justificativa, Registro, Usuario

    linhas = (Registro.objects.filter(estagio__in=estagios, confirmacao=Registro.Confirmacao.PENDENTE,
                                      data__lte=timezone.localdate(), estagio__supervisor__isnull=False)
              .exclude(justificativa__status=Justificativa.Status.PENDENTE)
              .values("estagio__supervisor").annotate(n=Count("pk"), desde=Min("data")).order_by("-n"))
    sups = Usuario.objects.in_bulk([l["estagio__supervisor"] for l in linhas])
    return [{"supervisor": sups[l["estagio__supervisor"]], "n": l["n"], "desde": l["desde"],
             "whatsapp": bool(telefone_whatsapp(sups[l["estagio__supervisor"]].telefone)),
             "email": bool(sups[l["estagio__supervisor"]].email)}
            for l in linhas if l["estagio__supervisor"] in sups]

