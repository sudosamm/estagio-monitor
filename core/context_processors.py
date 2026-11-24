from django.conf import settings
from django.urls import reverse


def _item(rotulo, nome, ativos, url_atual, contador=0):
    return {"rotulo": rotulo, "url": reverse(nome), "ativo": url_atual in ativos, "contador": contador or 0}


def menu_gestor(user, url_atual, config, atestados=0, candidaturas=0, opinioes=0):
    """Barra da área de gestão: dois atalhos soltos e três seções (o que a pessoa não pode usar não aparece)."""
    pode = user.pode
    acompanhamento = [
        _item("Indicadores", "indicadores", {"indicadores"}, url_atual),
        _item("Resumo da semana", "resumo_semanal", {"resumo_semanal"}, url_atual),
        pode("agenda") and _item("Agenda de visitas", "agendamentos",
                                 {"agendamentos", "novo_agendamento", "agendamento_detalhe", "assinar_agenda"}, url_atual),
        _item("Frequências", "frequencias", {"frequencias"}, url_atual),
        _item("Feedback dos supervisores", "feedback_geral", {"feedback_geral"}, url_atual),
        _item("Avaliações (SICE)", "avaliacoes_escola", {"avaliacoes_escola", "ver_avaliacao", "perguntas_avaliacao",
                                                         "pergunta_avaliacao_editar"}, url_atual),
        _item("Atestados", "atestados", {"atestados", "atestado_detalhe", "enviar_atestado"}, url_atual, atestados),
        _item("Pasta de documentos", "pasta_geral", {"pasta_geral", "tipos_documento", "tipo_documento_editar"},
              url_atual),
        pode("escalas") and _item("Alterar dias", "escala_lote", {"escala_lote"}, url_atual),
    ]
    comunicacao = [
        _item("Avisos para a turma", "comunicados", {"comunicados", "comunicado"}, url_atual),
        pode("arquivos") and _item("Arquivos gerais", "documentos_gerais", {"documentos_gerais"}, url_atual),
        user.is_superuser and _item("Opiniões sobre o sistema", "opinioes", {"opinioes"}, url_atual, opinioes),
    ]
    feriados = (_item("Feriados e recessos", "dias_sem_estagio", {"dias_sem_estagio", "importar_feriados", "recessos"},
                      url_atual) if pode("feriados")
                else pode("cadastros") and _item("Recessos", "recessos", {"recessos"}, url_atual))
    cadastros = [
        _item("Contas", "usuarios", {"usuarios", "editar_usuario", "criar_supervisores", "criar_orientador",
                                     "criar_coordenador", "importar_csv", "ativacao_usuario"}, url_atual),
        _item("Concedentes", "locais", {"locais", "local_editar", "local_novo", "ativacao_local"}, url_atual),
        _item("Turmas e cursos", "turmas", {"turmas", "turma_editar", "cursos", "curso_editar"}, url_atual),
        feriados,
        pode("candidaturas") and _item("Captação de concedentes", "captacao", {"captacao", "captacao_detalhe"},
                                       url_atual, candidaturas),
        (config.banco_talentos_habilitado or config.curriculos_habilitados)
        and _item("Banco de talentos", "banco_talentos", {"banco_talentos"}, url_atual),
        pode("encerramento") and _item("Encerramento do ano", "encerramento", {"encerramento"}, url_atual),
    ]
    soltos = [
        _item("Painel", "painel", {"painel"}, url_atual),
        _item("Estagiários", "estagios_lista", {"estagios_lista", "estagio_detalhe", "estagio_dia", "criar_estagiarios",
                                                "editar_estagio", "exportar_estagios"}, url_atual),
    ]
    secoes = []
    for rotulo, itens in (("Acompanhamento", acompanhamento), ("Comunicação", comunicacao), ("Cadastros", cadastros)):
        itens = [i for i in itens if i]
        if itens:
            secoes.append({"rotulo": rotulo, "itens": itens, "ativo": any(i["ativo"] for i in itens),
                           "contador": sum(i["contador"] for i in itens)})
    return {"soltos": soltos, "secoes": secoes}


def preferencia_tema(user, config):
    """auto, claro ou escuro (sempre claro se o administrador desligou o tema escuro)."""
    if not config.tema_escuro:
        return "claro"
    if user and user.is_authenticated:
        return user.tema.lower()
    return "auto"


def globais(request):
    from .models import Configuracao

    ctx = {"NOME_SISTEMA": settings.NOME_SISTEMA, "NOME_INSTITUICAO": settings.NOME_INSTITUICAO}
    user = getattr(request, "user", None)
    config = Configuracao.atual()
    ctx["TEMA"] = preferencia_tema(user, config)
    ctx["TEMA_LIBERADO"] = config.tema_escuro
    if config.tema_escuro:
        from .models import Usuario

        ctx["TEMAS"] = Usuario.Tema.choices
    ctx["EMAIL_ATIVO"] = settings.EMAIL_ATIVO  # também nas telas sem login (esqueci a senha, bloqueio)
    if user and user.is_authenticated:
        from .models import Configuracao

        ctx["notificacoes_nao_lidas"] = user.notificacoes.filter(lida=False).count()
        if not user.deve_trocar_senha and request.resolver_match and request.resolver_match.url_name != "novidades":
            from .novidades import pendentes

            ctx["NOVIDADES"] = pendentes(user)
        ctx["CONFIG"] = Configuracao.atual()
        if user.pode("painel"):
            from .models import Justificativa
            from .services import estagios_visiveis

            ctx["atestados_pendentes"] = Justificativa.objects.filter(
                status=Justificativa.Status.PENDENTE, estagio__in=estagios_visiveis(user)).count()
        if user.pode("candidaturas"):
            from .models import Candidatura

            pendentes = Candidatura.objects.filter(status=Candidatura.Status.PENDENTE)
            if user.is_coordenador and user.cursos_ids():
                pendentes = pendentes.filter(vagas__curso_id__in=user.cursos_ids()).distinct()
            ctx["candidaturas_pendentes"] = pendentes.count()
        if user.is_gestor and not user.deve_trocar_senha:
            url_atual = request.resolver_match.url_name if request.resolver_match else ""
            opinioes = 0
            if user.is_superuser:
                from .models import Sugestao

                opinioes = Sugestao.objects.filter(resolvida=False).count()
            ctx["MENU"] = menu_gestor(user, url_atual, ctx["CONFIG"], ctx.get("atestados_pendentes"),
                                      ctx.get("candidaturas_pendentes"), opinioes)
    elif request.path in ("/entrar/", "/"):
        from .models import Configuracao

        ctx["CAPTACAO_ABERTA"] = Configuracao.atual().captacao_disponivel
    return ctx
