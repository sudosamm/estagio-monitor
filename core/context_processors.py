from django.conf import settings


def globais(request):
    ctx = {"NOME_SISTEMA": settings.NOME_SISTEMA, "NOME_INSTITUICAO": settings.NOME_INSTITUICAO}
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        ctx["notificacoes_nao_lidas"] = user.notificacoes.filter(lida=False).count()
    return ctx
