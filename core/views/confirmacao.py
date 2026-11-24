"""Link “Confirmar todas” do supervisor (sem login) e o pedido da escola por e-mail ou WhatsApp."""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .. import confirmacao as conf
from ..models import Usuario
from ..services import estagios_visiveis
from .base import destino_seguro, orientador_requerido


@never_cache
def confirmar_por_link(request, codigo):
    link = conf.link_do_codigo(codigo)
    estado = conf.situacao(link)
    ctx = {"estado": estado, "link": link}
    if estado == "ok":
        if request.method == "POST":
            ctx["feitos"] = conf.confirmar_pelo_link(link, request)
            ctx["estado"] = "feito"
        else:
            ctx["registros"] = list(conf.registros_do_link(link))
            if not ctx["registros"]:
                ctx["estado"] = "nada"
    resposta = render(request, "core/confirmar_link.html", ctx)
    resposta["X-Robots-Tag"] = "noindex, nofollow"
    resposta["Referrer-Policy"] = "no-referrer"  # o código do link não vaza para outros sites
    return resposta


@orientador_requerido
@require_POST
def pedir_confirmacao(request, pk):
    sup = get_object_or_404(Usuario, pk=pk, papel=Usuario.Papel.SUPERVISOR, is_active=True)
    if not estagios_visiveis(request.user).filter(supervisor=sup, ativo=True).exists():
        raise PermissionDenied
    voltar = destino_seguro(request, "/painel/")
    if request.POST.get("canal") == "whatsapp":
        url = conf.endereco_whatsapp(sup, request, criado_por=request.user)
        if not url:
            messages.error(request, f"{sup.primeiro_nome} não tem um celular válido cadastrado ou não há nada pendente.")
            return redirect(voltar)
        return redirect(url)
    n = conf.enviar_email(sup, request, criado_por=request.user)
    if n:
        messages.success(request, f"E-mail enviado para {sup.primeiro_nome} com {n} presença(s) para confirmar.")
    else:
        messages.error(request, f"Não deu para enviar: {sup.primeiro_nome} está sem e-mail, o servidor de e-mail "
                                "não está configurado ou não há nada pendente.")
    return redirect(voltar)
