"""Telas do administrador: erros do sistema e registro de ações."""
from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import ErroSistema, RegistroAcao

TIPOS_ACAO = [
    ("", "Todas"), ("LOGIN", "Entradas"), ("LOGIN_FALHOU", "Senhas erradas"), ("2FA", "Verificação em duas etapas"),
    ("2FA_FALHOU", "Códigos errados"), ("GESTAO", "Mudanças da gestão"), ("EQUIPE", "Equipe das concedentes"),
    ("DADOS", "Downloads de dados pessoais"), ("CONFIRMACAO", "Confirmações pelo link"), ("TERMOS", "Aceite dos termos"),
    ("LOGOUT", "Saídas"),
]


def _so_admin(request):
    if not request.user.is_superuser:
        raise PermissionDenied


@login_required
def erros(request):
    _so_admin(request)
    ver = request.GET.get("ver", "abertos")
    qs = ErroSistema.objects.select_related("usuario")
    if ver == "abertos":
        qs = qs.filter(resolvido=False)
    elif ver == "resolvidos":
        qs = qs.filter(resolvido=True)
    from ..models import Notificacao

    Notificacao.objects.filter(usuario=request.user, lida=False, link=request.path).update(lida=True)
    return render(request, "core/erros_sistema.html", {
        "erros": qs[:200], "ver": ver, "abertos": ErroSistema.objects.filter(resolvido=False).count(),
        "ultimas_24h": ErroSistema.objects.filter(ultimo_em__gte=timezone.now() - timedelta(days=1)).count(),
    })


@login_required
@require_POST
def marcar_erro(request, pk=None):
    _so_admin(request)
    if request.POST.get("acao") == "limpar":
        n, _ = ErroSistema.objects.filter(resolvido=True).delete()
        messages.success(request, f"{n} erro(s) resolvido(s) apagado(s).")
        return redirect("erros_sistema")
    erro = get_object_or_404(ErroSistema, pk=pk)
    erro.resolvido = not erro.resolvido
    erro.save(update_fields=["resolvido"])
    messages.success(request, "Marcado como resolvido." if erro.resolvido else "Reaberto.")
    ver = request.POST.get("ver", "abertos")
    return redirect(f"{reverse('erros_sistema')}?ver={ver if ver in ('abertos', 'resolvidos', 'todos') else 'abertos'}")


def _data(texto):
    try:
        return datetime.strptime(texto, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


@login_required
def acoes(request):
    _so_admin(request)
    qs = RegistroAcao.objects.select_related("usuario")
    q, tipo = request.GET.get("q", "").strip(), request.GET.get("tipo", "")
    de, ate = _data(request.GET.get("de")), _data(request.GET.get("ate"))
    if q:
        qs = qs.filter(Q(quem__icontains=q) | Q(alvo__icontains=q) | Q(descricao__icontains=q) | Q(ip__startswith=q))
    if tipo:
        qs = qs.filter(tipo=tipo)
    if de:
        qs = qs.filter(quando__date__gte=de)
    if ate:
        qs = qs.filter(quando__date__lte=ate)
    pagina = Paginator(qs, 100).get_page(request.GET.get("pagina"))
    filtros = request.GET.copy()
    filtros.pop("pagina", None)
    return render(request, "core/registro_acoes.html", {
        "pagina": pagina, "q": q, "tipo": tipo, "de": request.GET.get("de", ""), "ate": request.GET.get("ate", ""),
        "tipos": TIPOS_ACAO, "filtros": filtros.urlencode(),
    })
