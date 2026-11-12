"""Encerramento do ano letivo (com desfazer) e anonimização dos dados pessoais antigos (LGPD)."""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import (
    Anonimizacao, Configuracao, Documento, Encerramento, Estagio, Feedback, HistoricoRegistro, ImpressaoFrequencia,
    InscricaoPush, Justificativa, Mensagem, Notificacao, Registro, Turma, Usuario,
)
from .services import estagios_visiveis, notificar, resumo_horas

DIAS_PARA_DESFAZER = 30


# ---------------------------------------------------------------- encerramento do ano


def diagnostico(usuario, ano):
    """O que existe nas turmas do ano: quem cumpriu, quem não, pendências e o que seria desativado."""
    from .pasta import pastas

    todos = list(estagios_visiveis(usuario).filter(turma__ano_estagio=ano).select_related("turma__curso")
                 .prefetch_related("escalas").order_by("estagiario__nome_completo"))
    ativos = [e for e in todos if e.ativo]
    concluidos, incompletos = [], []
    for e in ativos:
        r = resumo_horas(e)
        (concluidos if r["pct"] >= 100 else incompletos).append((e, r))
    ids = [e.pk for e in ativos]
    pasta = pastas(ativos)
    docs_faltando = [(e, [i.tipo.nome for i in pasta[e.pk] if i.tipo.obrigatorio and i.codigo != "conferido"])
                     for e in ativos]
    return {
        "ano": ano, "total": len(todos), "ja_encerrados": len(todos) - len(ativos),
        "concluidos": concluidos, "incompletos": incompletos,
        "pendencias": {
            "presencas": Registro.objects.filter(estagio_id__in=ids, confirmacao=Registro.Confirmacao.PENDENTE).count(),
            "atestados": Justificativa.objects.filter(estagio_id__in=ids, status=Justificativa.Status.PENDENTE).count(),
            "documentos": Documento.objects.filter(estagio_id__in=ids, situacao=Documento.Situacao.ENVIADO).count(),
        },
        "docs_faltando": [(e, f) for e, f in docs_faltando if f],
        "turmas": sorted({e.turma for e in todos}, key=lambda t: (t.curso.nome, t.nome)),
    }


@transaction.atomic
def encerrar(usuario, ano, incluir_incompletos=False, desativar_contas=True, desativar_supervisores=False,
             inativar_turmas=True, avancar_ano=True):
    d = diagnostico(usuario, ano)
    fechar = [e for e, _ in d["concluidos"]] + ([e for e, _ in d["incompletos"]] if incluir_incompletos else [])
    ids = [e.pk for e in fechar]
    for e in fechar:  # aviso antes de desativar a conta (chega também por e-mail e no celular)
        notificar([e.estagiario], "Seu estágio foi encerrado pela escola. Obrigado e parabéns pela dedicação!",
                  e.get_absolute_url())
    Estagio.objects.filter(pk__in=ids).update(ativo=False)

    contas = []
    if desativar_contas:
        alunos = {e.estagiario_id for e in fechar}
        com_outro = set(Estagio.objects.filter(estagiario_id__in=alunos, ativo=True).values_list("estagiario_id", flat=True))
        contas = list(Usuario.objects.filter(pk__in=alunos - com_outro, is_active=True).values_list("pk", flat=True))
        Usuario.objects.filter(pk__in=contas).update(is_active=False)

    supervisores = []
    if desativar_supervisores:
        sups = {e.supervisor_id for e in fechar if e.supervisor_id}
        ocupados = set(Estagio.objects.filter(supervisor_id__in=sups, ativo=True).values_list("supervisor_id", flat=True))
        supervisores = list(Usuario.objects.filter(pk__in=sups - ocupados, is_active=True).values_list("pk", flat=True))
        Usuario.objects.filter(pk__in=supervisores).update(is_active=False)

    turmas = []
    if inativar_turmas:
        candidatas = {t.pk for t in d["turmas"]}
        com_ativos = set(Estagio.objects.filter(turma_id__in=candidatas, ativo=True).values_list("turma_id", flat=True))
        turmas = list(Turma.objects.filter(pk__in=candidatas - com_ativos, ativa=True).values_list("pk", flat=True))
        Turma.objects.filter(pk__in=turmas).update(ativa=False)

    cfg = Configuracao.atual()
    antes = cfg.ano_referencia
    if avancar_ano and cfg.ano_referencia_efetivo <= ano:
        cfg.ano_referencia = ano + 1
        cfg.save(update_fields=["ano_referencia"])

    return Encerramento.objects.create(ano=ano, feito_por=usuario, resumo={
        "estagios": ids, "contas": contas, "supervisores": supervisores, "turmas": turmas,
        "ano_referencia_antes": antes, "ano_referencia_depois": cfg.ano_referencia,
        "incompletos": incluir_incompletos,
    })


def pode_desfazer(enc):
    return enc.desfeito_em is None and timezone.now() - enc.feito_em <= timedelta(days=DIAS_PARA_DESFAZER)


@transaction.atomic
def desfazer(enc, usuario):
    """Reativa exatamente o que o encerramento desativou (contas anonimizadas depois disso ficam como estão)."""
    r = enc.resumo
    Estagio.objects.filter(pk__in=r.get("estagios", [])).update(ativo=True)
    Usuario.objects.filter(pk__in=r.get("contas", []) + r.get("supervisores", []), anonimizado_em__isnull=True) \
        .update(is_active=True)
    Turma.objects.filter(pk__in=r.get("turmas", [])).update(ativa=True)
    cfg = Configuracao.atual()
    if cfg.ano_referencia == r.get("ano_referencia_depois"):
        cfg.ano_referencia = r.get("ano_referencia_antes")
        cfg.save(update_fields=["ano_referencia"])
    enc.desfeito_em, enc.desfeito_por = timezone.now(), usuario
    enc.save(update_fields=["desfeito_em", "desfeito_por"])
    return enc


# ---------------------------------------------------------------- anonimização (LGPD)


def ano_limite(hoje=None):
    """Último ano de estágio cujo prazo de guarda já passou."""
    hoje = hoje or timezone.localdate()
    return hoje.year - Configuracao.atual().retencao_anos - 1


def candidatos_anonimizacao(usuario, hoje=None):
    """Estágios encerrados de anos antigos, de estagiários sem estágio ativo e ainda não anonimizados."""
    limite = ano_limite(hoje)
    qs = (estagios_visiveis(usuario).filter(ativo=False, turma__ano_estagio__lte=limite,
                                            estagiario__anonimizado_em__isnull=True)
          .exclude(estagiario__estagios__ativo=True).select_related("turma", "estagiario").distinct())
    return list(qs)


def _apagar_arquivo(campo):
    if campo:
        campo.delete(save=False)
        return 1
    return 0


@transaction.atomic
def anonimizar(estagios, usuario):
    """Apaga dados pessoais e textos livres; mantém datas, horas e situações (para os indicadores e o histórico)."""
    agora = timezone.now()
    ids = [e.pk for e in estagios]
    arquivos = 0
    pessoas = {e.estagiario for e in estagios}
    for u in pessoas:
        arquivos += _apagar_arquivo(u.foto) + _apagar_arquivo(u.curriculo)
        u.username = f"anonimizado-{u.pk}"
        u.nome_completo = f"Estagiário anonimizado nº {u.pk}"
        u.first_name, u.last_name = "Estagiário", f"nº {u.pk}"
        u.email = u.telefone = u.matricula = u.cpf = u.apresentacao = u.habilidades = ""
        u.foto = u.curriculo = ""
        u.perfil_visivel = u.is_active = False
        u.set_unusable_password()
        u.anonimizado_em = agora
        u.save()
    usuarios_ids = [u.pk for u in pessoas]
    Notificacao.objects.filter(usuario_id__in=usuarios_ids).delete()
    InscricaoPush.objects.filter(usuario_id__in=usuarios_ids).delete()

    Estagio.objects.filter(pk__in=ids).update(observacoes_orientador="")
    Registro.objects.filter(estagio_id__in=ids).update(diario="", motivo="", obs_supervisor="", geo_entrada=None,
                                                       geo_saida=None)
    for h in HistoricoRegistro.objects.filter(estagio_id__in=ids):
        h.ip = None
        h.mudancas = [m for m in h.mudancas if m and m[0] not in ("Motivo / justificativa", "Motivo")]
        h.save(update_fields=["ip", "mudancas"])
    ImpressaoFrequencia.objects.filter(estagio_id__in=ids).update(ip=None, navegador="")
    Mensagem.objects.filter(estagio_id__in=ids).delete()
    for j in Justificativa.objects.filter(estagio_id__in=ids):  # atestados são dados de saúde: arquivo e texto saem
        arquivos += _apagar_arquivo(j.arquivo)
    Justificativa.objects.filter(estagio_id__in=ids).update(arquivo="", motivo="", parecer="", nome_original="")
    for d in Documento.objects.filter(estagio_id__in=ids):
        arquivos += _apagar_arquivo(d.arquivo)
    Documento.objects.filter(estagio_id__in=ids).delete()
    Feedback.objects.filter(estagio_id__in=ids).update(pontos_fortes="", melhorar="", reservado="")

    anos = sorted({e.turma.ano_estagio for e in estagios if e.turma})
    Anonimizacao.objects.create(feita_por=usuario, anos=", ".join(map(str, anos)), pessoas=len(pessoas),
                                arquivos=arquivos)
    return {"pessoas": len(pessoas), "arquivos": arquivos}
