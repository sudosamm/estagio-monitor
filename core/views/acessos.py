"""Meus dados → Acessos e aparelhos: lista dos acessos à conta e aparelhos conectados (com “Desconectar”)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .. import auditoria, sessoes
from ..models import RegistroAcao, SessaoAparelho, Usuario
from .base import permissao

TIPOS_ACESSO = ("LOGIN", "LOGIN_FALHOU", "LOGOUT", "2FA", "2FA_FALHOU", "SESSAO_RECUSADA", "SESSAO_ENCERRADA")


@login_required
def acessos(request):
    user = request.user
    atual = request.session.session_key
    if request.method == "POST":
        acao = request.POST.get("acao")
        if acao == "outros":
            n = sessoes.desconectar_todas(user, exceto_chave=atual)
            auditoria.registrar(request, "SESSAO_ENCERRADA", f"Desconectou os outros aparelhos ({n})")
            messages.success(request, f"{n} aparelho(s) desconectado(s)." if n else "Não havia outros aparelhos conectados.")
        elif acao == "desconectar":
            rec = get_object_or_404(SessaoAparelho, pk=request.POST.get("id") or 0, usuario=user)
            if rec.chave == atual:  # este aparelho: é o botão “Sair”
                return redirect("acessos")
            sessoes.desconectar(user, rec)
            auditoria.registrar(request, "SESSAO_ENCERRADA", f"Desconectou o aparelho {rec.aparelho or 'desconhecido'}")
            messages.success(request, f"{rec.aparelho or 'Aparelho'} desconectado. Quem estiver nele precisa entrar de novo.")
        return redirect("acessos")
    aparelhos = sessoes.ativas(user)
    from django.utils import timezone

    for a in aparelhos:
        a.atual = a.chave == atual
        a.recente = a.atual or (timezone.now() - a.ultimo_uso).total_seconds() < sessoes.ATUALIZAR_A_CADA
    aparelhos.sort(key=lambda a: (not a.atual, -a.ultimo_uso.timestamp()))
    lista = RegistroAcao.objects.filter(usuario=user, tipo__in=TIPOS_ACESSO)
    pagina = Paginator(lista, 30).get_page(request.GET.get("pagina"))
    return render(request, "core/acessos.html", {"aparelhos": aparelhos, "pagina": pagina})


@permissao("contas")
@require_POST
def desconectar_usuario(request, pk):
    """Celular perdido ou roubado: a gestão desconecta a pessoa de todos os aparelhos (a senha continua a mesma)."""
    from .orientador import _pode_liberar_acesso

    alvo = get_object_or_404(Usuario, pk=pk)
    if not _pode_liberar_acesso(request, alvo):
        raise PermissionDenied
    n = sessoes.desconectar_todas(alvo)
    auditoria.registrar(request, "GESTAO", f"Desconectou {alvo.nome_completo} de todos os aparelhos ({n})", alvo=alvo)
    messages.success(request, f"{alvo.primeiro_nome} foi desconectado(a) de {n} aparelho(s)." if n
                     else f"{alvo.primeiro_nome} não estava conectado(a) em nenhum aparelho.")
    return redirect("editar_usuario", pk=alvo.pk)
