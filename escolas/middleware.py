"""Define a escola atual de cada requisição e o papel da pessoa nela.

Ordem no settings: depois do ``AuthenticationMiddleware`` e antes do ``ModoAdministradorMiddleware``.

Como a escola é escolhida (um domínio só em 2027; a escola vem da conta e do caminho):
1. página pública com a escola no caminho (``/seja-concedente/<slug>/``): essa escola;
2. conta com vínculos ativos: a escolhida no seletor (guardada na sessão), senão a primeira por nome;
3. sem vínculo: a escola única do banco (a instalação de hoje), senão nenhuma — e as consultas a dados de escola
   falham fechado (``EscopoAusente`` vira 403).

Com a escola definida, a conta passa a valer nesta requisição com o papel **nesta escola**:
- ``user.papel``: o papel do vínculo (o ``Usuario.papel`` gravado é o papel principal e não é alterado);
- ``user.is_superuser``: administrador **desta escola** (vínculo ``ADMIN``). O administrador da plataforma é o
  ``is_superuser`` gravado (``user.administrador_plataforma``) e não ganha poderes de escola sem vínculo.
O ``Usuario.save`` grava sempre os valores originais (ver ``Usuario._salvar``).
"""
import re

from django.core.exceptions import PermissionDenied

from .escopo import ESCOLA_ATUAL, TODAS, EscopoAusente, escola_unica

SESSAO = "escola_id"
PRIORIDADE = ["ORIENTADOR", "COORDENADOR", "SUPERVISOR", "RESPONSAVEL", "ESTAGIARIO", "CONTATO"]


def vinculos_ativos(user):
    from .models import VinculoEscola

    if not hasattr(user, "_vinculos_ativos"):
        user._vinculos_ativos = list(
            VinculoEscola.objects.filter(usuario=user, ativo=True).exclude(escola__situacao="INATIVA")
            .select_related("escola", "escola__rede").order_by("escola__nome", "papel"))
    return user._vinculos_ativos


def escolas_da_conta(user):
    vistas, saida = set(), []
    for v in vinculos_ativos(user):
        if v.escola_id not in vistas:
            vistas.add(v.escola_id)
            saida.append(v.escola)
    return saida


def papel_na_escola(user, escola, papel_principal):
    """O papel da pessoa nesta escola: o principal, se ela o tem aqui; senão o primeiro pela prioridade."""
    papeis = {v.papel for v in vinculos_ativos(user) if v.escola_id == escola.pk}
    if papel_principal in papeis:
        return papel_principal
    for p in PRIORIDADE:
        if p in papeis:
            return p
    return None


def aplicar_escola(user, escola):
    """Ajusta papel e administrador da conta para a escola (só nesta requisição).

    Com uma escola só no banco (a instalação de 2027), a conta vale exatamente como hoje: o papel gravado e o
    administrador gravado (``is_superuser``), mais quem tiver o vínculo ``ADMIN`` (administrador só da escola, sem
    acesso à plataforma). Com várias escolas, valem os vínculos desta escola.
    """
    if not hasattr(user, "_papel_bd"):
        user._papel_bd = user.papel
        user._superuser_bd = user.is_superuser
    vinculos = [v for v in vinculos_ativos(user) if v.escola_id == escola.pk]
    admin_da_escola = any(v.papel == "ADMIN" for v in vinculos)
    if escola_unica() is not None:
        user.is_superuser = user._superuser_bd or admin_da_escola
        return
    papel = papel_na_escola(user, escola, user._papel_bd)
    if papel and papel != "CONTATO":
        user.papel = papel
    user.is_superuser = admin_da_escola


CAMINHO_COM_ESCOLA = re.compile(r"^/seja-concedente/(?P<slug>[-a-zA-Z0-9_]+)/")


def resolver_escola(request):
    from .models import Escola

    achado = CAMINHO_COM_ESCOLA.match(request.path_info or "")
    slug = achado.group("slug") if achado else None
    if slug:
        return Escola.objects.filter(slug=slug).exclude(situacao="INATIVA").select_related("rede").first()
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        escolas = escolas_da_conta(user)
        if user.is_superuser and not escolas:  # administrador da plataforma sem vínculo
            escolas = list(Escola.objects.select_related("rede").exclude(situacao="INATIVA"))
        escolhida = request.session.get(SESSAO)
        for e in escolas:
            if e.pk == escolhida:
                return e
        if escolas:
            return escolas[0]
    return escola_unica()


class EscolaAtualMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if request.path_info.startswith("/admin/") and user is not None and user.is_authenticated and user.is_superuser:
            request.escola = None  # /admin/: só a plataforma, que vê todas as escolas (escolas/admin.py)
            token = ESCOLA_ATUAL.set(TODAS)
            try:
                return self.get_response(request)
            finally:
                ESCOLA_ATUAL.reset(token)
        escola = resolver_escola(request)
        request.escola = escola
        token = ESCOLA_ATUAL.set(escola)
        try:
            user = getattr(request, "user", None)
            if escola is not None and user is not None and user.is_authenticated:
                aplicar_escola(user, escola)
            return self.get_response(request)
        finally:
            ESCOLA_ATUAL.reset(token)

    def process_exception(self, request, exception):
        if isinstance(exception, EscopoAusente):
            raise PermissionDenied("Escolha uma escola para continuar.") from exception
        return None
