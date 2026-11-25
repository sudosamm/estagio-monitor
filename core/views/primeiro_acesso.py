"""Primeiro acesso: a pessoa prova quem é e cria a própria senha (não existe mais senha inicial compartilhada).

- Estagiário: nome completo + data de nascimento (cadastrada pela gestão ou pela importação dos termos).
- Supervisor, orientador, coordenador ou estagiário sem data de nascimento: usuário + código de uso único,
  gerado pela gestão e repassado só para a pessoa.
"""
import time

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.forms import SetPasswordForm
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache

from .. import termos
from ..forms import PrimeiroAcessoCodigoForm, PrimeiroAcessoNascimentoForm
from ..models import Usuario
from ..seguranca import (
    MENSAGEM_BLOQUEIO_1O, chave_texto, codigo_confere, concluir_primeiro_acesso, ip_de, limpar, limpar_1o,
    primeiro_acesso_bloqueado, registrar_falha_1o,
)

CHAVE_SESSAO = "primeiro_acesso"
PRAZO_SENHA = 15 * 60  # segundos entre provar quem é e salvar a senha


def _pendentes():
    return Usuario.objects.filter(deve_trocar_senha=True, is_active=True, anonimizado_em__isnull=True)


def achar_por_nascimento(texto, nascimento):
    chave = chave_texto(texto)
    qs = _pendentes().filter(papel=Usuario.Papel.ESTAGIARIO, data_nascimento=nascimento)
    achados = [u for u in qs if chave_texto(u.nome_completo) == chave]
    return achados[0] if len(achados) == 1 else None


def achar_por_codigo(texto, codigo):
    pendentes = _pendentes().exclude(codigo_acesso="")
    candidatos = list(pendentes.filter(username__iexact=texto.strip()))
    digitos = "".join(c for c in texto if c.isdigit())
    if not candidatos and len(digitos) == 11:  # o responsável pode informar o CPF
        from ..validators import formatar_cpf

        candidatos = list(pendentes.filter(cpf=formatar_cpf(digitos)))
    if not candidatos:
        chave = chave_texto(texto)
        candidatos = [u for u in pendentes if chave_texto(u.nome_completo) == chave]
    return next((u for u in candidatos if codigo_confere(u, codigo)), None)


@never_cache
def primeiro_acesso(request):
    if request.user.is_authenticated:
        return redirect("inicio")
    modo = "codigo" if (request.POST.get("modo") or request.GET.get("modo")) == "codigo" else "nascimento"
    Form = PrimeiroAcessoCodigoForm if modo == "codigo" else PrimeiroAcessoNascimentoForm
    form = Form(request.POST or None)
    erro = ""
    if request.method == "POST" and form.is_valid():
        d, ip = form.cleaned_data, ip_de(request)
        texto = d["usuario"] if modo == "codigo" else d["nome"]
        if primeiro_acesso_bloqueado(texto, ip):
            erro = MENSAGEM_BLOQUEIO_1O
        else:
            user = achar_por_codigo(texto, d["codigo"]) if modo == "codigo" else achar_por_nascimento(texto, d["nascimento"])
            if user:
                limpar_1o(texto)
                request.session.cycle_key()
                request.session[CHAVE_SESSAO] = {"uid": user.pk, "ate": time.time() + PRAZO_SENHA}
                return redirect("primeiro_acesso_senha")
            registrar_falha_1o(texto, ip)
            erro = ("Não encontramos uma conta esperando o primeiro acesso com esses dados. Confira e tente de novo. "
                    "Se você já criou sua senha, entre pela tela de login.")
    return render(request, "registration/primeiro_acesso.html", {"form": form, "modo": modo, "erro": erro})


@never_cache
def primeiro_acesso_senha(request):
    dados = request.session.get(CHAVE_SESSAO) or {}
    user = _pendentes().filter(pk=dados.get("uid")).first() if dados.get("ate", 0) > time.time() else None
    if user is None:
        request.session.pop(CHAVE_SESSAO, None)
        messages.error(request, "O tempo para criar a senha acabou. Comece o primeiro acesso de novo.")
        return redirect("primeiro_acesso")
    form = SetPasswordForm(user, request.POST or None)
    for f in form.fields.values():
        f.help_text = ""
    erro_termos = request.method == "POST" and request.POST.get("aceito") != "1"
    if request.method == "POST" and form.is_valid() and not erro_termos:
        concluir_primeiro_acesso(user, form.cleaned_data["new_password1"])
        termos.registrar_aceite(user, request)
        limpar(user.username)
        request.session.pop(CHAVE_SESSAO, None)
        login(request, user, backend="core.seguranca.BackendComLimite")
        messages.success(request, f"Pronto! Seu usuário é {user.username}. Nas próximas vezes, entre com ele e a senha que você criou.")
        return redirect("inicio")
    return render(request, "registration/primeiro_acesso_senha.html", {"form": form, "alvo": user,
                                                                       "erro_termos": erro_termos})
