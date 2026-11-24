"""Aparelhos conectados e sessão presa ao aparelho.

Cada login vira um SessaoAparelho (aparelho, IP, último uso), que a pessoa vê em Meus dados → Acessos e aparelhos e
pode desconectar. A sessão guarda duas marcas do aparelho em que começou:

- a assinatura do aparelho: grupo do sistema (Windows; Android/Linux; Apple) e família do navegador (Chrome, Firefox,
  Edge…). Não muda com atualizações nem com a “versão para computador” do celular;
- o resumo de um cookie próprio do aparelho (“aparelho”), separado do cookie da sessão.

Se o cookie da sessão aparecer em outro navegador/sistema, ou sem o cookie do aparelho, a sessão é encerrada no
servidor na hora (nos dois aparelhos, porque é a mesma sessão), a pessoa recebe um aviso e a ação fica registrada.
Sair em qualquer aparelho também encerra a sessão no servidor: quem tiver uma cópia do cookie fica de fora.

Limite honesto: quem copiar todos os cookies e imitar exatamente o mesmo navegador e sistema não é detectado por
nenhum site. Para isso existe a verificação em duas etapas.
"""
import hashlib
import secrets
import time

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone

COOKIE = "aparelho"
COOKIE_VALIDADE = 400 * 24 * 3600  # o máximo que os navegadores aceitam
ATUALIZAR_A_CADA = 300  # segundos entre as gravações de “último uso”


def _resumo(texto):
    return hashlib.sha256(texto.encode()).hexdigest()


def _grupo_e_navegador(ua):
    """Traços que não mudam no mesmo aparelho, nem com a “versão para computador” do celular (que troca Android por
    Linux e iPhone por Mac no texto do navegador): grupo do sistema e, fora da Apple, a família do navegador."""
    import re

    if re.search(r"iPhone|iPad|Macintosh|Mac OS X", ua):
        return "apple", "webkit"  # no iPhone todos os navegadores são WebKit e o modo computador vira “Safari no Mac”
    grupo = ("windows" if "Windows" in ua else "linux" if re.search(r"Android|Linux|CrOS|X11", ua) else "outro")
    navegador = next((n for p, n in ((r"Edg[A]?/", "edge"), (r"OPR/|Opera", "opera"), (r"SamsungBrowser", "samsung"),
                                     (r"Firefox/", "firefox"), (r"Chrome/", "chrome"), (r"Safari/", "safari"))
                      if re.search(p, ua)), "outro")
    return grupo, navegador


def assinatura(request):
    ua = (request.META.get("HTTP_USER_AGENT", "") or "")[:400]
    return _resumo("aparelho|" + "|".join(_grupo_e_navegador(ua)))


def _ip(request):
    from .seguranca import ip_de

    return ip_de(request)


def _cookie_valido(valor):
    return bool(valor) and 20 <= len(valor) <= 64 and valor.replace("-", "").replace("_", "").isalnum()


# ---------------------------------------------------------------- entrada e saída (sinais do Django)


def ao_entrar(sender, request, user, **kw):
    """Login em qualquer tela (normal, verificação em duas etapas, primeiro acesso, cadastro da concedente)."""
    if request is None or not hasattr(request, "session"):
        return
    from .auditoria import aparelho
    from .models import SessaoAparelho

    sessao = request.session
    if not sessao.session_key:
        sessao.save()
    rec, _ = SessaoAparelho.objects.update_or_create(
        chave=sessao.session_key,
        defaults={"usuario": user, "aparelho": aparelho(request)[:80], "assinatura": assinatura(request),
                  "ip": _ip(request), "criada_em": timezone.now(), "ultimo_uso": timezone.now()},
    )
    sessao.update({"_ap_id": rec.pk, "_ap_chave": sessao.session_key, "_ap_ass": rec.assinatura,
                   "_ap_visto": time.time()})
    token = request.COOKIES.get(COOKIE, "")
    if _cookie_valido(token):  # aparelho que já tem o cookie: a sessão fica presa a ele desde já
        sessao["_ap_cookie"] = _resumo(token)
        sessao.pop("_ap_cookie_novo", None)
    else:  # cookie novo: só vale depois que o navegador o devolver (ver conferir)
        token = secrets.token_urlsafe(24)
        request._cookie_aparelho = token  # o middleware grava na resposta
        sessao["_ap_cookie_novo"] = _resumo(token)
        sessao.pop("_ap_cookie", None)


def ao_sair(sender, request, user, **kw):
    if request is None or not hasattr(request, "session"):
        return
    from .models import SessaoAparelho

    ap_id = request.session.get("_ap_id")
    chave = request.session.session_key
    if ap_id:
        SessaoAparelho.objects.filter(pk=ap_id).delete()
    elif chave:
        SessaoAparelho.objects.filter(chave=chave).delete()


# ---------------------------------------------------------------- conferência a cada requisição


def _adotar(request):
    """Sessão aberta antes desta proteção existir: passa a ser listada e presa a este navegador/sistema. O cookie do
    aparelho só entra no próximo login (gravá-lo aqui, com várias abas abrindo ao mesmo tempo, desconectaria a
    pessoa por engano)."""
    from django.db import IntegrityError

    from .auditoria import aparelho
    from .models import SessaoAparelho

    sessao = request.session
    if not sessao.session_key:
        return
    try:
        rec, _ = SessaoAparelho.objects.get_or_create(
            chave=sessao.session_key,
            defaults={"usuario": request.user, "aparelho": aparelho(request)[:80], "assinatura": assinatura(request),
                      "ip": _ip(request)},
        )
    except IntegrityError:
        rec = SessaoAparelho.objects.filter(chave=sessao.session_key).first()
        if rec is None:
            return
    if rec.usuario_id != request.user.pk:
        return
    sessao.update({"_ap_id": rec.pk, "_ap_chave": sessao.session_key, "_ap_ass": rec.assinatura,
                   "_ap_visto": time.time()})


def _expulsar(request, motivo, detalhe=""):
    """Encerra a sessão no servidor (vale para todos os aparelhos que tiverem este cookie), sem o sinal de “saiu”."""
    from django.contrib import messages
    from django.urls import reverse

    from .auditoria import aparelho, registrar
    from .models import SessaoAparelho
    from .services import notificar

    user = request.user
    ap_id = request.session.get("_ap_id")
    origem = SessaoAparelho.objects.filter(pk=ap_id).first() if ap_id else None
    if origem:
        origem.delete()
    request.session.flush()
    request.user = AnonymousUser()
    if motivo == "aparelho":
        texto = (f"Por segurança, encerramos uma sessão da sua conta: ela começou em {origem.aparelho if origem else 'um aparelho'} "
                 f"e foi usada em outro ({aparelho(request) or 'desconhecido'}). Se não foi você, troque a senha.")
        registrar(request, "SESSAO_RECUSADA", f"Sessão usada em outro aparelho foi encerrada{detalhe}", usuario=user)
        notificar([user], texto[:255], reverse("acessos"))
        messages.warning(request, "Por segurança, a sessão foi encerrada porque o acesso veio de um aparelho "
                                  "diferente do que entrou. Entre de novo com seu usuário e senha.")
    else:
        messages.info(request, "Este aparelho foi desconectado da conta. Entre de novo para continuar.")


def conferir(request):
    """Devolve True se a sessão foi encerrada nesta requisição."""
    from .models import SessaoAparelho

    sessao = request.session
    ap_id = sessao.get("_ap_id")
    if ap_id is None:
        _adotar(request)
        return False
    guardada = sessao.get("_ap_ass")
    if guardada and guardada != assinatura(request):
        _expulsar(request, "aparelho", " (navegador ou sistema diferente)")
        return True
    cookie = sessao.get("_ap_cookie")
    recebido = _resumo(request.COOKIES.get(COOKIE, ""))
    if cookie and recebido != cookie:
        _expulsar(request, "aparelho", " (sem o cookie do aparelho)")
        return True
    if not cookie and sessao.get("_ap_cookie_novo") == recebido:  # o navegador guardou o cookie do login
        sessao["_ap_cookie"] = recebido
        del sessao["_ap_cookie_novo"]
    if sessao.session_key and sessao.get("_ap_chave") != sessao.session_key:
        # a troca de senha gira a chave da sessão: o registro acompanha
        SessaoAparelho.objects.filter(pk=ap_id).update(chave=sessao.session_key)
        sessao["_ap_chave"] = sessao.session_key
    agora = time.time()
    if agora - sessao.get("_ap_visto", 0) >= ATUALIZAR_A_CADA:
        mudou = SessaoAparelho.objects.filter(pk=ap_id, usuario=request.user).update(
            ultimo_uso=timezone.now(), ip=_ip(request))
        if not mudou:  # desconectado em outro aparelho
            _expulsar(request, "desconectado")
            return True
        sessao["_ap_visto"] = agora
    return False


class SessaoAparelhoMiddleware:
    """Depois do AuthenticationMiddleware. Também grava o cookie do aparelho criado no login."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.shortcuts import redirect

        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and hasattr(request, "session"):
            if conferir(request):
                if request.path.startswith("/static/"):
                    return self.get_response(request)
                return redirect("login")
        response = self.get_response(request)
        token = getattr(request, "_cookie_aparelho", None)
        if token:
            response.set_cookie(COOKIE, token, max_age=COOKIE_VALIDADE, secure=settings.SESSION_COOKIE_SECURE,
                                httponly=True, samesite="Lax")
        return response


# ---------------------------------------------------------------- listar e desconectar


def ativas(user):
    """Aparelhos conectados agora (sessões que ainda valem). Apaga da lista as que já acabaram."""
    from django.contrib.sessions.models import Session

    from .models import SessaoAparelho

    registros = list(SessaoAparelho.objects.filter(usuario=user))
    validas = set(Session.objects.filter(session_key__in=[r.chave for r in registros], expire_date__gt=timezone.now())
                  .values_list("session_key", flat=True))
    vencidas = [r.pk for r in registros if r.chave not in validas]
    if vencidas:
        SessaoAparelho.objects.filter(pk__in=vencidas).delete()
    return [r for r in registros if r.chave in validas]


def _sessoes_do_usuario(user):
    """Todas as sessões válidas da pessoa, inclusive as que ainda não foram listadas (abertas e não usadas desde
    que esta proteção entrou)."""
    from django.contrib.sessions.models import Session

    chaves = []
    for s in Session.objects.filter(expire_date__gt=timezone.now()).iterator():
        try:
            if str(s.get_decoded().get("_auth_user_id")) == str(user.pk):
                chaves.append(s.session_key)
        except Exception:  # noqa: BLE001 — sessão corrompida: ignora
            continue
    return chaves


def desconectar(user, registro):
    from django.contrib.sessions.models import Session

    Session.objects.filter(session_key=registro.chave).delete()
    registro.delete()


def desconectar_todas(user, exceto_chave=None):
    """Encerra as sessões da pessoa em todos os aparelhos (menos a `exceto_chave`). Devolve quantas encerrou."""
    from django.contrib.sessions.models import Session

    from .models import SessaoAparelho

    chaves = set(_sessoes_do_usuario(user)) | set(SessaoAparelho.objects.filter(usuario=user)
                                                   .values_list("chave", flat=True))
    chaves.discard(exceto_chave)
    n = Session.objects.filter(session_key__in=chaves).delete()[0]
    SessaoAparelho.objects.filter(usuario=user, chave__in=chaves).delete()
    return n


def limpar_antigas():
    """Tarefa periódica: sessões vencidas saem do banco (o Django não apaga sozinho) e da lista de aparelhos."""
    from django.contrib.sessions.models import Session

    from .models import SessaoAparelho

    Session.objects.filter(expire_date__lt=timezone.now()).delete()
    validas = Session.objects.values_list("session_key", flat=True)
    SessaoAparelho.objects.exclude(chave__in=validas).delete()
