"""Equipe da concedente: o responsável cadastra supervisores e funcionários e dá permissões temporárias
(substituições) para alguém confirmar presenças quando o supervisor não estiver.

Quem “apoia” um estágio (responsável pela concedente ou substituto no período) pode ver o estágio e confirmar,
contestar ou lançar dias. Não vê mensagens, arquivos, atestados nem feedback, e não muda dias e horários: isso
continua com o supervisor titular e a escola.
"""
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

MAX_DIAS_SUBSTITUICAO = 92


def substituicoes_ativas(user, dia=None):
    from .models import Substituicao

    if not (user.is_authenticated and user.is_supervisor):
        return []
    dia = dia or timezone.localdate()
    chave = f"_subs_{dia.isoformat()}"
    if not hasattr(user, chave):
        setattr(user, chave, list(Substituicao.objects.filter(substituto=user, revogada_em__isnull=True,
                                                              inicio__lte=dia, fim__gte=dia)))
    return getattr(user, chave)


def eh_apoio_do(user, estagio):
    """Responsável pela concedente do estágio ou substituto do supervisor dele hoje (e não o próprio supervisor)."""
    if not (user.is_authenticated and user.is_supervisor and estagio.local_id) or estagio.supervisor_id == user.pk:
        return False
    return estagio.local_id in user.ids_geridas() or any(s.cobre(estagio) for s in substituicoes_ativas(user))


def estagios_de_apoio(user):
    """Estágios ativos que a pessoa acompanha sem ser a supervisora titular."""
    from .models import Estagio

    if not (user.is_authenticated and user.is_supervisor):
        return Estagio.objects.none()
    filtro = Q(local_id__in=user.ids_geridas()) if user.ids_geridas() else Q(pk__in=[])
    for s in substituicoes_ativas(user):
        filtro |= Q(local_id=s.concedente_id, **({"supervisor_id": s.titular_id} if s.titular_id else {}))
    return (Estagio.objects.filter(filtro, ativo=True).exclude(supervisor=user)
            .select_related("estagiario", "supervisor", "orientador", "local", "curso"))


def pode_confirmar(user, estagio):
    from .views.base import eh_orientador_do, eh_supervisor_do

    return eh_supervisor_do(user, estagio) or eh_orientador_do(user, estagio) or eh_apoio_do(user, estagio)


# ---------------------------------------------------------------- quem gerencia a equipe


def pode_gerir(user, local):
    """Responsável pela concedente, ou a escola (quem cuida das contas)."""
    return user.is_authenticated and (local.pk in user.ids_geridas() or user.pode("contas"))


def equipe_de(local):
    from .models import Usuario

    return (Usuario.objects.filter(papel=Usuario.Papel.SUPERVISOR, concedentes=local, anonimizado_em__isnull=True)
            .prefetch_related("concedentes_geridas").order_by("-is_active", "nome_completo"))


def pode_mexer_na_conta(user, alvo, local):
    """O responsável só gerencia contas de supervisor que são só daquela(s) concedente(s) que ele gere."""
    if user.pode("contas"):
        return alvo.is_supervisor
    if not alvo.is_supervisor or alvo.pk == user.pk or alvo.is_superuser:
        return False
    ids = set(alvo.concedentes.values_list("pk", flat=True))
    return local.pk in ids and ids <= user.ids_geridas()


def validar_substituicao(local, substituto, titular, inicio, fim, hoje=None):
    """Lista de erros (vazia = pode criar)."""
    hoje = hoje or timezone.localdate()
    erros = []
    membros = set(equipe_de(local).filter(is_active=True).values_list("pk", flat=True))
    if substituto.pk not in membros:
        erros.append("Quem vai confirmar precisa ser da equipe desta concedente e estar com a conta ativa.")
    if titular and titular.pk not in membros:
        erros.append("O supervisor substituído precisa ser desta concedente.")
    if titular and titular.pk == substituto.pk:
        erros.append("A pessoa não pode substituir a si mesma.")
    if fim < inicio:
        erros.append("A data final vem antes da inicial.")
    elif fim - inicio > timedelta(days=MAX_DIAS_SUBSTITUICAO):
        erros.append(f"Uma substituição dura no máximo {MAX_DIAS_SUBSTITUICAO} dias. Para mais tempo, peça à escola "
                     "para trocar o supervisor dos estagiários.")
    if fim < hoje:
        erros.append("O período já passou.")
    return erros


def criar_substituicao(local, substituto, titular, inicio, fim, motivo, por, request=None):
    from django.urls import reverse

    from . import auditoria
    from .models import Estagio, Substituicao
    from .services import notificar

    s = Substituicao.objects.create(concedente=local, substituto=substituto, titular=titular, inicio=inicio, fim=fim,
                                    motivo=motivo[:150], criada_por=por)
    quem = titular.nome_completo if titular else f"todos os supervisores de {local}"
    periodo = f"de {inicio:%d/%m} a {fim:%d/%m}" if inicio != fim else f"em {inicio:%d/%m}"
    notificar([substituto], f"Você pode confirmar as presenças dos estagiários de {quem} {periodo}.",
              reverse("painel_supervisor"), exceto=por)
    if titular:
        notificar([titular], f"{substituto.nome_completo} vai confirmar as presenças dos seus estagiários {periodo}.",
                  reverse("painel_supervisor"), exceto=por)
    alvo = Estagio.objects.filter(local=local, ativo=True, **({"supervisor": titular} if titular else {}))
    orientadores = {e.orientador for e in alvo.select_related("orientador")}
    notificar(list(orientadores), f"{local}: {substituto.nome_completo} confirma as presenças no lugar de {quem} "
              f"{periodo}.", reverse("equipe_concedente", args=[local.pk]), exceto=por)
    auditoria.registrar(request, "EQUIPE", f"Deu permissão temporária a {substituto.nome_completo} ({periodo})",
                        alvo=local)
    return s


def revogar(s, por, request=None):
    from . import auditoria
    from .services import notificar

    s.revogada_em, s.revogada_por = timezone.now(), por
    s.save(update_fields=["revogada_em", "revogada_por"])
    from django.urls import reverse

    notificar([s.substituto], f"A permissão para confirmar presenças em {s.concedente} foi encerrada.",
              reverse("painel_supervisor"), exceto=por)
    auditoria.registrar(request, "EQUIPE", f"Encerrou a permissão temporária de {s.substituto.nome_completo}",
                        alvo=s.concedente)
