"""Verificação em duas etapas: configurar em Meus dados e pedir o código ao entrar."""
import time

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache

from .. import auditoria
from .. import dois_fatores as df
from ..models import Usuario
from ..seguranca import JANELA, LoginForm, ip_de, registrar_falha

CHAVE_SESSAO = "dois_fatores"
PRAZO = 5 * 60  # segundos entre acertar a senha e digitar o código
SESSAO_NOVO = "dois_fatores_novo"


class EntrarView(LoginView):
    """Login normal; quem tem a verificação ligada passa antes pela tela do código."""

    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        user = form.get_user()
        if user.dois_fatores_ativo and not df.aparelho_confiavel(self.request, user):
            self.request.session.cycle_key()
            self.request.session[CHAVE_SESSAO] = {"uid": user.pk, "ate": time.time() + PRAZO,
                                                  "next": self.get_success_url(), "backend": user.backend}
            return redirect("verificar_dois_fatores")
        return super().form_valid(form)


def _falhas(user):
    from django.utils import timezone

    from ..models import TentativaLogin

    return TentativaLogin.objects.filter(username=df.PREFIXO_2FA + user.username.lower(),
                                         criado_em__gte=timezone.now() - JANELA).count()


@never_cache
def verificar(request):
    dados = request.session.get(CHAVE_SESSAO) or {}
    user = (Usuario.objects.filter(pk=dados.get("uid"), is_active=True).first()
            if dados.get("ate", 0) > time.time() else None)
    if user is None or not user.dois_fatores_ativo:
        request.session.pop(CHAVE_SESSAO, None)
        messages.error(request, "O tempo para digitar o código acabou. Entre de novo com a sua senha.")
        return redirect("login")
    erro = ""
    if request.method == "POST":
        if _falhas(user) >= df.LIMITE_FALHAS:
            request.session.pop(CHAVE_SESSAO, None)
            messages.error(request, "Muitos códigos errados. Aguarde 15 minutos e entre de novo.")
            return redirect("login")
        tipo = df.conferir(user, request.POST.get("codigo", ""))
        if tipo:
            request.session.pop(CHAVE_SESSAO, None)
            login(request, user, backend=dados.get("backend") or "core.seguranca.BackendComLimite")
            destino = dados.get("next") or "/"
            if not url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
                destino = "/"
            resposta = redirect(destino)
            if request.POST.get("confiar") == "1":
                df.lembrar_aparelho(resposta, user)
            if tipo == "recuperacao":
                restam = len(user.codigos_recuperacao)
                auditoria.registrar(request, "2FA", "Entrou com um código de recuperação", usuario=user)
                messages.warning(request, f"Você entrou com um código de recuperação. Restam {restam}. "
                                          "Se perdeu o celular, configure a verificação de novo em Meus dados.")
            return resposta
        registrar_falha(df.PREFIXO_2FA + user.username, ip_de(request))
        auditoria.registrar(request, "2FA_FALHOU", "Código de verificação errado", usuario=user)
        erro = "Código incorreto. Confira o app e digite os 6 números que aparecem agora."
    return render(request, "registration/verificar_dois_fatores.html", {"erro": erro, "alvo": user})


@never_cache
@login_required
def configurar(request):
    user = request.user
    if not df.pode_usar(user):
        raise PermissionDenied
    exigido = df.exigido(user)
    acao = request.POST.get("acao", "")
    erro = ""
    if user.dois_fatores_ativo:
        if request.method == "POST" and acao in ("desligar", "novos_codigos"):
            if df.passo_que_confere(user.totp_segredo, request.POST.get("codigo"), user.totp_ultimo_passo) is None:
                erro = "Código incorreto. Digite o código que o app mostra agora."
            elif acao == "desligar":
                if exigido:
                    erro = "A escola exige a verificação em duas etapas para o seu perfil: ela não pode ser desligada."
                else:
                    df.desativar(user)
                    auditoria.registrar(request, "2FA", "Desligou a verificação em duas etapas")
                    messages.success(request, "Verificação em duas etapas desligada.")
                    return redirect("dois_fatores")
            else:
                codigos = df.gerar_recuperacao(user)
                auditoria.registrar(request, "2FA", "Gerou novos códigos de recuperação")
                return render(request, "core/dois_fatores.html", {"codigos": codigos, "exigido": exigido})
        return render(request, "core/dois_fatores.html", {"ativo": True, "erro": erro, "exigido": exigido,
                                                          "restam": len(user.codigos_recuperacao)})

    segredo = request.session.get(SESSAO_NOVO) or df.novo_segredo()
    request.session[SESSAO_NOVO] = segredo
    if request.method == "POST" and acao == "ativar":
        passo = df.passo_que_confere(segredo, request.POST.get("codigo"))
        if passo is None:
            erro = "Código incorreto. Confira se o relógio do celular está certo e digite o código que aparece agora."
        else:
            codigos = df.ativar(user, segredo, passo)
            request.session.pop(SESSAO_NOVO, None)
            auditoria.registrar(request, "2FA", "Ligou a verificação em duas etapas")
            messages.success(request, "Pronto! A partir de agora, o sistema pede o código do celular ao entrar.")
            return render(request, "core/dois_fatores.html", {"codigos": codigos, "exigido": exigido,
                                                              "proximo": request.GET.get("next", "")})
    uri = df.endereco_app(user, segredo)
    return render(request, "core/dois_fatores.html", {
        "qr": df.qr_svg(uri), "uri": uri, "segredo": df.segredo_formatado(segredo), "erro": erro, "exigido": exigido,
    })
