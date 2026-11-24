"""Verificação em duas etapas: senha + código de 6 dígitos de um app autenticador (TOTP, RFC 6238).

Funciona com Google Authenticator, Microsoft Authenticator, Authy, 2FAS, o app Senhas do iPhone etc.
Quem perde o celular entra com um dos códigos de recuperação (uso único) ou pede um novo primeiro acesso à
gestão, que zera a verificação.
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from django.conf import settings
from django.core import signing
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

PASSO = 30  # segundos de cada código
QTD_RECUPERACAO = 8
COOKIE_APARELHO = "aparelho_confiavel"
DIAS_APARELHO = 30
SAL_APARELHO = "core.dois_fatores.aparelho"
PREFIXO_2FA = "2fa:"  # falhas na tabela de tentativas
LIMITE_FALHAS = 5      # em 15 minutos
ALFABETO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def novo_segredo():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _codigo(segredo, passo):
    chave = base64.b32decode(segredo + "=" * (-len(segredo) % 8))
    h = hmac.new(chave, struct.pack(">Q", passo), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return f"{(struct.unpack('>I', h[o:o + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


def passo_que_confere(segredo, codigo, ultimo=0, agora=None):
    """Passo de tempo em que o código vale (aceita 30 s de diferença no relógio), ou None.
    Um código já usado (passo <= último) não vale de novo."""
    codigo = "".join(c for c in (codigo or "") if c.isdigit())
    if len(codigo) != 6 or not segredo:
        return None
    atual = int((agora if agora is not None else time.time()) // PASSO)
    for p in (atual - 1, atual, atual + 1):
        if p > ultimo and constant_time_compare(_codigo(segredo, p), codigo):
            return p
    return None


def endereco_app(user, segredo):
    """otpauth://… que o app autenticador lê pelo QR code."""
    emissor = settings.NOME_SISTEMA
    rotulo = quote(f"{emissor}:{user.username}")
    return f"otpauth://totp/{rotulo}?secret={segredo}&issuer={quote(emissor)}&digits=6&period={PASSO}"


def qr_svg(texto):
    import io

    import segno

    saida = io.BytesIO()
    segno.make(texto, error="m", micro=False).save(saida, kind="svg", scale=1, border=2, xmldecl=False,
                                                   omitsize=True, dark="#000", light="#fff")
    return saida.getvalue().decode()


def segredo_formatado(segredo):
    return " ".join(segredo[i:i + 4] for i in range(0, len(segredo), 4))


# ---------------------------------------------------------------- códigos de recuperação


def _resumo(user, codigo):
    return salted_hmac("core.dois_fatores.recuperacao", f"{user.pk}:{codigo}").hexdigest()


def _normal(codigo):
    return "".join(c for c in (codigo or "").upper() if c.isalnum())


def gerar_recuperacao(user):
    """Cria códigos novos (os antigos deixam de valer) e devolve os códigos para mostrar uma única vez."""
    codigos = ["".join(secrets.choice(ALFABETO) for _ in range(8)) for _ in range(QTD_RECUPERACAO)]
    user.codigos_recuperacao = [_resumo(user, c) for c in codigos]
    user.save(update_fields=["codigos_recuperacao"])
    return [f"{c[:4]}-{c[4:]}" for c in codigos]


def usar_recuperacao(user, texto):
    codigo = _normal(texto)
    if len(codigo) != 8:
        return False
    resumo = _resumo(user, codigo)
    restantes = [r for r in user.codigos_recuperacao if not constant_time_compare(r, resumo)]
    if len(restantes) == len(user.codigos_recuperacao):
        return False
    user.codigos_recuperacao = restantes
    user.save(update_fields=["codigos_recuperacao"])
    return True


# ---------------------------------------------------------------- uso


def ativar(user, segredo, passo):
    user.totp_segredo, user.totp_ativo_em, user.totp_ultimo_passo = segredo, timezone.now(), passo
    user.save(update_fields=["totp_segredo", "totp_ativo_em", "totp_ultimo_passo"])
    return gerar_recuperacao(user)


def desativar(user):
    user.totp_segredo, user.totp_ativo_em, user.totp_ultimo_passo, user.codigos_recuperacao = "", None, 0, []
    user.save(update_fields=["totp_segredo", "totp_ativo_em", "totp_ultimo_passo", "codigos_recuperacao"])


def conferir(user, texto):
    """'app' (código do autenticador), 'recuperacao' (código de recuperação, que é gasto) ou None."""
    passo = passo_que_confere(user.totp_segredo, texto, user.totp_ultimo_passo)
    if passo is not None:
        user.totp_ultimo_passo = passo
        user.save(update_fields=["totp_ultimo_passo"])
        return "app"
    if usar_recuperacao(user, texto):
        return "recuperacao"
    return None


def pode_usar(user):
    """Quem tem a opção em Meus dados (gestão e concedentes; estagiários não)."""
    return user.is_authenticated and not user.is_estagiario


def precisa(user):
    """Quem cuida de estudantes ou do sistema: gestão (orientador, coordenador, administrador) e responsáveis."""
    return user.is_authenticated and (user.is_gestor or user.gere_concedente)


def exigido(user):
    from .models import Configuracao

    return precisa(user) and Configuracao.atual().exigir_dois_fatores


# ---------------------------------------------------------------- aparelho confiável (30 dias sem pedir o código)


def _marca(user):
    return salted_hmac(SAL_APARELHO, f"{user.password}|{user.totp_segredo}").hexdigest()[:20]


def lembrar_aparelho(response, user):
    valor = signing.dumps({"u": user.pk, "m": _marca(user)}, salt=SAL_APARELHO)
    response.set_cookie(COOKIE_APARELHO, valor, max_age=DIAS_APARELHO * 86400, httponly=True, samesite="Lax",
                        secure=settings.SESSION_COOKIE_SECURE)


def aparelho_confiavel(request, user):
    valor = request.COOKIES.get(COOKIE_APARELHO)
    if not valor:
        return False
    try:
        dados = signing.loads(valor, salt=SAL_APARELHO, max_age=DIAS_APARELHO * 86400)
    except signing.BadSignature:
        return False
    return dados.get("u") == user.pk and constant_time_compare(dados.get("m", ""), _marca(user))
