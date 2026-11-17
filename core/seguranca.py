"""Proteções de acesso: limite de tentativas de login e regras de senha."""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

# Janela de 15 minutos. Por usuário+IP é o limite de quem errou a senha; por usuário (de qualquer lugar) e por IP
# (vários usuários) seguram quem tenta adivinhar senhas em massa, sem travar a escola inteira atrás de um mesmo IP.
JANELA = timedelta(minutes=15)
LIMITE_USUARIO_IP = 5
LIMITE_USUARIO = 20
LIMITE_IP = 40
MENSAGEM_BLOQUEIO = "Muitas tentativas de entrar. Espere 15 minutos e tente de novo, ou peça ao orientador para redefinir a senha."


def ip_de(request):
    if request is None:
        return None
    return (request.META.get("HTTP_CF_CONNECTING_IP")
            or request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
            or request.META.get("REMOTE_ADDR")) or None


def _normal(username):
    return (username or "").strip().lower()[:150]


def bloqueado(username, ip):
    from .models import TentativaLogin

    recentes = TentativaLogin.objects.filter(criado_em__gte=timezone.now() - JANELA)
    u = _normal(username)
    if u and recentes.filter(username=u, ip=ip).count() >= LIMITE_USUARIO_IP:
        return True
    if u and recentes.filter(username=u).count() >= LIMITE_USUARIO:
        return True
    return bool(ip) and recentes.filter(ip=ip).count() >= LIMITE_IP


def registrar_falha(username, ip):
    from .models import TentativaLogin

    TentativaLogin.objects.create(username=_normal(username), ip=ip)
    TentativaLogin.objects.filter(criado_em__lt=timezone.now() - timedelta(days=1)).delete()


def limpar(username):
    from .models import TentativaLogin

    TentativaLogin.objects.filter(username=_normal(username)).delete()


class BackendComLimite(ModelBackend):
    """O login normal do Django, recusando enquanto o usuário/IP estiver com tentativas demais (vale também no /admin/)."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username and bloqueado(username, ip_de(request)):
            raise PermissionDenied(MENSAGEM_BLOQUEIO)
        return super().authenticate(request, username=username, password=password, **kwargs)


class LoginForm(AuthenticationForm):
    error_messages = {**AuthenticationForm.error_messages, "invalid_login": "Usuário ou senha incorretos."}

    def clean(self):
        if bloqueado(self.data.get("username"), ip_de(self.request)):
            raise ValidationError(MENSAGEM_BLOQUEIO, code="bloqueado")
        return super().clean()


def ao_falhar(sender, credentials, request=None, **kw):
    registrar_falha(credentials.get("username"), ip_de(request))


def ao_entrar(sender, request, user, **kw):
    limpar(user.get_username())


class SenhaDiferenteDaPadrao:
    """A senha nova não pode ser a senha inicial que todo mundo recebe."""

    def validate(self, password, user=None):
        if password and password == settings.SENHA_PADRAO:
            raise ValidationError("Escolha uma senha diferente da senha inicial.", code="senha_padrao")

    def get_help_text(self):
        return "A senha não pode ser a senha inicial."


