"""Proteções de acesso: limite de tentativas, primeiro acesso (código de uso único) e regras de senha."""
import secrets
import unicodedata
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

# Janela de 15 minutos. Por usuário+IP é o limite de quem errou a senha; por usuário (de qualquer lugar) e por IP
# (vários usuários) seguram quem tenta adivinhar senhas em massa, sem travar a escola inteira atrás de um mesmo IP.
JANELA = timedelta(minutes=15)
LIMITE_USUARIO_IP = 5
LIMITE_USUARIO = 20
LIMITE_IP = 40
MENSAGEM_BLOQUEIO = ("Muitas tentativas de entrar: o acesso ficou bloqueado por 15 minutos. Se esqueceu a senha, crie "
                     "outra em “Esqueci minha senha” ou fale com o administrador.")
LIMITE_AVISO_TENTATIVAS = 3  # na 3ª senha errada, a pessoa recebe um e-mail (se tiver e-mail confirmado)


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
    # linhas com “:” são de outras telas (primeiro acesso, esqueci a senha, pedido de ajuda): usuário não tem “:”
    return bool(ip) and recentes.filter(ip=ip).exclude(username__contains=":").count() >= LIMITE_IP


def registrar_falha(username, ip):
    from .models import TentativaLogin

    TentativaLogin.objects.create(username=_normal(username), ip=ip)
    TentativaLogin.objects.filter(criado_em__lt=timezone.now() - timedelta(days=1)).delete()


def limpar(username):
    from .models import TentativaLogin

    TentativaLogin.objects.filter(username=_normal(username)).delete()


def senha_inicial_antiga(user, password):
    """Conta que ainda não fez o primeiro acesso não entra por senha (ACEITAR_SENHA_PADRAO=1 reabre, só em emergência).

    As contas antigas guardam o resumo da senha padrão de quando foram criadas; se a SENHA_PADRAO do servidor mudar,
    a senha antiga continuaria abrindo essas contas. Por isso a regra vale para qualquer senha, não só a atual.
    Exceção: administrador criado pelo terminal (createsuperuser), que nasce com senha própria."""
    if not user.deve_trocar_senha or getattr(settings, "ACEITAR_SENHA_PADRAO", False):
        return False
    return not user.is_superuser or password == settings.SENHA_PADRAO


def usuario_do_identificador(texto):
    """Entrar com o e-mail: vale quando um único cadastro ativo usa aquele e-mail. Senão, o texto segue como usuário."""
    texto = (texto or "").strip()
    if "@" not in texto:
        return texto
    from .models import Usuario

    achados = list(Usuario.objects.filter(email__iexact=texto, is_active=True).values_list("username", flat=True)[:2])
    return achados[0] if len(achados) == 1 else texto


class BackendComLimite(ModelBackend):
    """O login normal do Django, recusando enquanto o usuário/IP estiver com tentativas demais (vale também no /admin/)."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        username = usuario_do_identificador(username)  # usuário ou e-mail contam no mesmo limite
        if username and bloqueado(username, ip_de(request)):
            raise PermissionDenied(MENSAGEM_BLOQUEIO)
        user = super().authenticate(request, username=username, password=password, **kwargs)
        if user is not None and senha_inicial_antiga(user, password):
            return None
        return user


class LoginForm(AuthenticationForm):
    bloqueado = False  # a tela mostra o botão de pedir ajuda ao administrador

    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Usuário ou senha incorretos.",
        "senha_inicial": "A senha inicial deixou de valer. Se é a sua primeira vez, use “Primeiro acesso” logo abaixo.",
    }

    def clean(self):
        if bloqueado(usuario_do_identificador(self.data.get("username")), ip_de(self.request)):
            self.bloqueado = True
            raise ValidationError(MENSAGEM_BLOQUEIO, code="bloqueado")
        try:
            return super().clean()
        except ValidationError as exc:
            if self.data.get("password") == settings.SENHA_PADRAO and not getattr(settings, "ACEITAR_SENHA_PADRAO", False):
                raise ValidationError(self.error_messages["senha_inicial"], code="senha_inicial") from exc
            raise


# ---------------------------------------------------------------- primeiro acesso

# Falhas do primeiro acesso vão para a mesma tabela, com prefixo na “chave” (nome ou usuário digitado).
# A data de nascimento tem poucas combinações possíveis, então o limite por pessoa vale por 24 horas.
PREFIXO_1O_ACESSO = "1o:"
LIMITE_1O_CHAVE_IP = 5          # em 15 minutos
LIMITE_1O_CHAVE_DIA = 10        # em 24 horas, de qualquer lugar
LIMITE_1O_IP = 60               # em 15 minutos (uma turma inteira atrás do mesmo IP da escola)
MENSAGEM_BLOQUEIO_1O = ("Muitas tentativas com esse nome. Por segurança, o primeiro acesso dele fica parado até amanhã. "
                        "Se precisar antes, peça ao orientador um código de acesso.")

ALFABETO_CODIGO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # sem I, L, O, 0 e 1, que se confundem
VALIDADE_CODIGO = timedelta(days=30)


def chave_texto(texto):
    """Minúsculas, sem acentos e com espaços simples — para comparar nomes digitados de jeitos diferentes."""
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.lower().split())


def _chave_1o(texto):
    return (PREFIXO_1O_ACESSO + chave_texto(texto))[:150]


def primeiro_acesso_bloqueado(texto, ip):
    from .models import TentativaLogin

    agora, chave = timezone.now(), _chave_1o(texto)
    if TentativaLogin.objects.filter(username=chave, criado_em__gte=agora - timedelta(days=1)).count() >= LIMITE_1O_CHAVE_DIA:
        return True
    recentes = TentativaLogin.objects.filter(criado_em__gte=agora - JANELA)
    if recentes.filter(username=chave, ip=ip).count() >= LIMITE_1O_CHAVE_IP:
        return True
    return bool(ip) and recentes.filter(ip=ip, username__startswith=PREFIXO_1O_ACESSO).count() >= LIMITE_1O_IP


def registrar_falha_1o(texto, ip):
    registrar_falha(_chave_1o(texto), ip)


def limpar_1o(texto):
    limpar(_chave_1o(texto))


def _resumo_codigo(user, codigo):
    return salted_hmac("core.primeiro_acesso", f"{user.pk}:{codigo}").hexdigest()


def normalizar_codigo(texto):
    return "".join(c for c in (texto or "").upper() if c.isalnum())


def gerar_codigo(user):
    """Cria (e devolve, só desta vez) o código de uso único da pessoa. Um código novo invalida o anterior."""
    codigo = "".join(secrets.choice(ALFABETO_CODIGO) for _ in range(8))
    user.codigo_acesso = _resumo_codigo(user, codigo)
    user.codigo_acesso_validade = timezone.now() + VALIDADE_CODIGO
    user.save(update_fields=["codigo_acesso", "codigo_acesso_validade"])
    return f"{codigo[:4]}-{codigo[4:]}"


def codigo_confere(user, texto):
    codigo = normalizar_codigo(texto)
    if not (user.codigo_acesso and user.codigo_acesso_validade and len(codigo) == 8):
        return False
    if user.codigo_acesso_validade < timezone.now():
        return False
    return constant_time_compare(user.codigo_acesso, _resumo_codigo(user, codigo))


def precisa_de_codigo(user):
    """Estagiário com data de nascimento entra pelo nome + nascimento; o resto precisa de um código."""
    return not (user.is_estagiario and user.data_nascimento)


def liberar_primeiro_acesso(user):
    """A senha atual deixa de valer e a pessoa cria outra pelo primeiro acesso. Devolve um código de uso único
    (estagiários com data de nascimento também podem usar nome + nascimento)."""
    user.set_unusable_password()
    user.deve_trocar_senha = True
    # quem perdeu o celular pede um novo primeiro acesso: a verificação em duas etapas recomeça do zero
    user.totp_segredo, user.totp_ativo_em, user.totp_ultimo_passo, user.codigos_recuperacao = "", None, 0, []
    user.save(update_fields=["password", "deve_trocar_senha", "totp_segredo", "totp_ativo_em", "totp_ultimo_passo",
                             "codigos_recuperacao"])
    from .sessoes import desconectar_todas

    desconectar_todas(user)  # quem estava conectado com a senha antiga sai de todos os aparelhos
    return gerar_codigo(user)


def concluir_primeiro_acesso(user, senha):
    user.set_password(senha)
    user.deve_trocar_senha = False
    user.codigo_acesso, user.codigo_acesso_validade = "", None
    user.save(update_fields=["password", "deve_trocar_senha", "codigo_acesso", "codigo_acesso_validade"])


def ao_falhar(sender, credentials, request=None, **kw):
    ip = ip_de(request)
    username = usuario_do_identificador(credentials.get("username"))
    registrar_falha(username, ip)
    avisar_tentativas(username, ip, request)


def avisar_tentativas(username, ip, request=None):
    """E-mail para o dono da conta na 3ª senha errada e quando o acesso fica bloqueado (só e-mail confirmado)."""
    from django.urls import reverse

    from . import emails
    from .models import TentativaLogin, Usuario

    u = _normal(username)
    if not u or ":" in u:
        return
    user = Usuario.objects.filter(username__iexact=u, is_active=True, email_confirmado_em__isnull=False).exclude(email="").first()
    if not user:
        return
    recentes = TentativaLogin.objects.filter(username=u, criado_em__gte=timezone.now() - JANELA)
    total, deste_ip = recentes.count(), recentes.filter(ip=ip).count()
    dados = {"nome": user.primeiro_nome, "usuario": user.username, "quando": emails.quando(), "ip": ip or "desconhecido"}
    if deste_ip == LIMITE_USUARIO_IP or total == LIMITE_USUARIO:
        emails.enviar("BLOQUEIO", [user.email], minutos=int(JANELA.total_seconds() // 60),
                      link=emails.endereco(request, reverse("esqueci_senha")), **dados)
    elif total == LIMITE_AVISO_TENTATIVAS:
        emails.enviar("TENTATIVAS", [user.email], tentativas=total, **dados)


# ---------------------------------------------------------------- limites das telas públicas

def excedeu(prefixo, chave, ip, por_chave, por_ip, janela=timedelta(hours=1)):
    """Pedidos demais nesta tela (esqueci a senha, pedido de ajuda) para a mesma conta ou do mesmo IP?"""
    from .models import TentativaLogin

    recentes = TentativaLogin.objects.filter(criado_em__gte=timezone.now() - janela, username__startswith=prefixo)
    if chave and recentes.filter(username=(prefixo + chave_texto(chave))[:150]).count() >= por_chave:
        return True
    return bool(ip) and recentes.filter(ip=ip).count() >= por_ip


def registrar_pedido(prefixo, chave, ip):
    registrar_falha((prefixo + chave_texto(chave))[:150], ip)


def ao_entrar(sender, request, user, **kw):
    limpar(user.get_username())


class SenhaDiferenteDaPadrao:
    """A senha nova não pode ser a senha inicial que todo mundo recebe."""

    def validate(self, password, user=None):
        if password and password == settings.SENHA_PADRAO:
            raise ValidationError("Escolha uma senha diferente da senha inicial.", code="senha_padrao")

    def get_help_text(self):
        return "A senha não pode ser a senha inicial."


