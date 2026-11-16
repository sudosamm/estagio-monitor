"""“O que há de novo” (pop-up e página) e a página de sugestões e erros."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .. import novidades as nov


@login_required
def novidades(request):
    user = request.user
    if request.method == "POST":
        user.novidades_popup = request.POST.get("popup") == "sim"
        user.save(update_fields=["novidades_popup"])
        messages.success(request, "Preferência salva.")
        return redirect("novidades")
    versoes = nov.para(user)
    vistas_antes = user.novidades_vistas
    if (user.novidades_vistas or "") < nov.ultima_versao():
        user.novidades_vistas = nov.ultima_versao()
        user.save(update_fields=["novidades_vistas"])
    return render(request, "core/novidades.html", {"versoes": versoes, "vistas_antes": vistas_antes,
                                                   "admin": user.is_superuser})


@login_required
@require_POST
def novidades_visto(request):
    """Fechou o pop-up: “ver a cada atualização” (padrão) ou “não mostrar novamente”."""
    user = request.user
    user.novidades_vistas = nov.ultima_versao()
    campos = ["novidades_vistas"]
    if request.POST.get("acao") == "nunca":
        user.novidades_popup = False
        campos.append("novidades_popup")
    elif request.POST.get("acao") == "sempre":
        user.novidades_popup = True
        campos.append("novidades_popup")
    user.save(update_fields=campos)
    if request.headers.get("X-Requested-With") == "fetch":
        return JsonResponse({"ok": True, "popup": user.novidades_popup})
    return redirect(request.POST.get("next") if (request.POST.get("next") or "").startswith("/") else "/")


# ---------------------------------------------------------------- sugestões e erros

LIMITE_POR_HORA = 5


def _ip(request):
    return (request.META.get("HTTP_CF_CONNECTING_IP") or request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
            or request.META.get("REMOTE_ADDR")) or None


def sugestoes(request):
    """Aberta a todos (inclusive quem não consegue entrar): manda para o e-mail da equipe e guarda no sistema."""
    from datetime import timedelta

    from django.db import transaction
    from django.urls import reverse
    from django.utils import timezone

    from ..forms import SugestaoForm
    from ..models import AnexoSugestao, Sugestao, Usuario
    from ..services import notificar
    from ..sugestoes import destinatarios, enviar

    user = request.user if request.user.is_authenticated else None
    pagina = (request.GET.get("de") or request.META.get("HTTP_REFERER", ""))[:300]
    inicial = {"nome": user.nome_completo if user else "", "email": user.email if user else "", "pagina": pagina}
    if request.GET.get("tipo") in Sugestao.Tipo.values:
        inicial["tipo"] = request.GET["tipo"]
    form = SugestaoForm(request.POST or None, request.FILES or None, initial=inicial)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        if d["site"]:  # robô preencheu o campo escondido: finge que deu certo
            return redirect(reverse("sugestoes") + "?enviado=1")
        ip = _ip(request)
        uma_hora = timezone.now() - timedelta(hours=1)
        recentes = Sugestao.objects.filter(criado_em__gte=uma_hora)
        recentes = recentes.filter(usuario=user) if user else recentes.filter(ip=ip, usuario__isnull=True)
        if recentes.count() >= LIMITE_POR_HORA:
            form.add_error(None, "Você já mandou várias mensagens na última hora. Espere um pouco e tente de novo.")
        else:
            with transaction.atomic():
                s = Sugestao.objects.create(
                    tipo=d["tipo"], nome=d["nome"].strip(), email=d["email"], mensagem=d["mensagem"].strip(),
                    usuario=user, pagina=request.POST.get("pagina", "")[:300],
                    navegador=request.META.get("HTTP_USER_AGENT", "")[:300], ip=ip)
                for a in d["anexos"]:
                    AnexoSugestao.objects.create(sugestao=s, arquivo=a, nome_original=a.name[:255], tamanho=a.size)
                admins = Usuario.objects.filter(is_superuser=True, is_active=True).exclude(pk=getattr(user, "pk", None))
                notificar(admins, f"{s.get_tipo_display()} enviado por {s.nome}: {' '.join(s.mensagem.split())[:90]}",
                          reverse("admin:core_sugestao_change", args=[s.pk]))
                transaction.on_commit(lambda: enviar(s.pk))
            return redirect(reverse("sugestoes") + "?enviado=1")
    return render(request, "core/sugestoes.html", {
        "form": form, "enviado": request.GET.get("enviado") == "1", "pagina": pagina,
        "tem_destino": bool(destinatarios()),
    })


def anexo_sugestao(request, pk):
    """Download de um anexo de sugestão (só administradores)."""
    from django.core.exceptions import PermissionDenied
    from django.http import FileResponse
    from django.shortcuts import get_object_or_404

    from ..models import AnexoSugestao

    if not (request.user.is_authenticated and request.user.is_superuser):
        raise PermissionDenied
    a = get_object_or_404(AnexoSugestao, pk=pk)
    resp = FileResponse(a.arquivo.open("rb"), as_attachment=True, filename=a.nome_original)
    resp["Cache-Control"] = "private, no-store"
    return resp
