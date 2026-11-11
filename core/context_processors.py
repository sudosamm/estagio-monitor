from django.conf import settings


def globais(request):
    ctx = {"NOME_SISTEMA": settings.NOME_SISTEMA, "NOME_INSTITUICAO": settings.NOME_INSTITUICAO}
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        from .models import Configuracao

        ctx["notificacoes_nao_lidas"] = user.notificacoes.filter(lida=False).count()
        ctx["CONFIG"] = Configuracao.atual()
        if user.pode("candidaturas"):
            from .models import Candidatura

            pendentes = Candidatura.objects.filter(status=Candidatura.Status.PENDENTE)
            if user.is_coordenador and user.cursos_ids():
                pendentes = pendentes.filter(vagas__curso_id__in=user.cursos_ids()).distinct()
            ctx["candidaturas_pendentes"] = pendentes.count()
    elif request.path in ("/entrar/", "/"):
        from .models import Configuracao

        ctx["CAPTACAO_ABERTA"] = Configuracao.atual().captacao_disponivel
    return ctx
