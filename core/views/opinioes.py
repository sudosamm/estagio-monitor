"""Período de testes: o botão “Sua opinião” (estagiários e supervisores) e a página que reúne as respostas."""
from collections import Counter
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Avg
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from ..forms import OpiniaoForm
from ..models import Sugestao, Usuario
from ..services import notificar
from .novidades import LIMITE_POR_HORA, _ip


@login_required
@require_POST
def enviar_opiniao(request):
    user = request.user
    form = OpiniaoForm(request.POST)
    quer_json = "application/json" in request.headers.get("Accept", "")
    voltar = request.POST.get("pagina", "")
    if not url_has_allowed_host_and_scheme(voltar, {request.get_host()}) or not voltar.startswith("/"):
        voltar = reverse("inicio")
    erro = ""
    if not form.is_valid():
        erro = " ".join(form.non_field_errors()) or "Confira o que foi preenchido."
    elif Sugestao.objects.filter(usuario=user, criado_em__gte=timezone.now() - timedelta(hours=1)).count() >= LIMITE_POR_HORA:
        erro = "Você já mandou várias opiniões na última hora. Obrigado! Tente de novo daqui a pouco."
    if erro:
        if quer_json:
            return JsonResponse({"ok": False, "erro": erro}, status=400)
        messages.error(request, erro)
        return redirect(voltar)
    d = form.cleaned_data
    mensagem = (d["mensagem"] or "").strip() or f"(só a nota: {dict(OpiniaoForm.NOTAS)[d['nota']]})"
    with transaction.atomic():
        s = Sugestao.objects.create(tipo=d["tipo"], nota=d["nota"], nome=user.nome_completo, email=user.email,
                                    mensagem=mensagem, usuario=user, pagina=voltar[:300], ip=_ip(request),
                                    navegador=request.META.get("HTTP_USER_AGENT", "")[:300])
        if d["tipo"] == "ERRO" or (d["nota"] and d["nota"] <= 2):  # só o que pede atenção vai para o sino
            admins = Usuario.objects.filter(is_superuser=True, is_active=True).exclude(pk=user.pk)
            notificar(admins, f"Opinião ({s.get_tipo_display().lower()}{f', nota {s.nota}' if s.nota else ''}) de "
                      f"{user.primeiro_nome}: {' '.join(mensagem.split())[:80]}", reverse("opinioes"))
    if quer_json:
        return JsonResponse({"ok": True})
    messages.success(request, "Obrigado pela sua opinião!")
    return redirect(voltar)


@login_required
def opinioes(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    qs = Sugestao.objects.select_related("usuario").prefetch_related("anexos")
    f = {k: request.GET.get(k, "") for k in ("tipo", "papel", "situacao")}
    if f["tipo"]:
        qs = qs.filter(tipo=f["tipo"])
    if f["papel"] == "VISITANTE":
        qs = qs.filter(usuario__isnull=True)
    elif f["papel"]:
        qs = qs.filter(usuario__papel=f["papel"])
    if f["situacao"] != "todas":
        qs = qs.filter(resolvida=f["situacao"] == "resolvidas")
    todas = Sugestao.objects.all()
    notas = Counter(todas.exclude(nota=None).values_list("nota", flat=True))
    por_papel = Counter(todas.values_list("usuario__papel", flat=True))
    paginas = Counter(todas.values_list("pagina", flat=True)).most_common(6)
    return render(request, "core/opinioes.html", {
        "itens": qs[:300], "f": f, "tipos": Sugestao.Tipo.choices, "papeis": Usuario.Papel.choices,
        "total": todas.count(), "abertas": todas.filter(resolvida=False).count(),
        "media": todas.exclude(nota=None).aggregate(m=Avg("nota"))["m"],
        "notas": [(n, notas.get(n, 0)) for n in (5, 4, 3, 2, 1)], "max_nota": max(notas.values(), default=0),
        "por_papel": [(dict(Usuario.Papel.choices).get(p, "Visitante"), n) for p, n in por_papel.most_common()],
        "paginas": [(p or "—", n) for p, n in paginas],
    })


@login_required
@require_POST
def marcar_opiniao(request, pk):
    if not request.user.is_superuser:
        raise PermissionDenied
    s = get_object_or_404(Sugestao, pk=pk)
    s.resolvida = not s.resolvida
    s.save(update_fields=["resolvida"])
    return redirect(request.POST.get("voltar") if url_has_allowed_host_and_scheme(
        request.POST.get("voltar"), {request.get_host()}) else "opinioes")
