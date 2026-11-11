import mimetypes

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..forms import PerfilForm
from ..models import Documento, Notificacao
from ..services import estagios_visiveis


@login_required
def inicio(request):
    user = request.user
    if user.is_orientador or user.is_superuser:
        return redirect("painel")
    if user.is_supervisor:
        return redirect("painel_supervisor")
    estagios = list(estagios_visiveis(user).filter(ativo=True))
    if len(estagios) == 1:
        return redirect(estagios[0])
    return render(request, "core/estagiario_lista.html", {"estagios": estagios_visiveis(user)})


@login_required
def trocar_senha(request):
    obrigatorio = request.user.deve_trocar_senha
    form = PasswordChangeForm(request.user, request.POST or None)
    for f in form.fields.values():
        f.help_text = ""
    if request.method == "POST" and form.is_valid():
        user = form.save()
        user.deve_trocar_senha = False
        user.save(update_fields=["deve_trocar_senha"])
        update_session_auth_hash(request, user)
        messages.success(request, "Senha alterada com sucesso.")
        return redirect("inicio")
    return render(request, "core/trocar_senha.html", {"form": form, "obrigatorio": obrigatorio})


@login_required
def perfil(request):
    form = PerfilForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Dados atualizados.")
        return redirect("perfil")
    return render(request, "core/perfil.html", {"form": form})


@login_required
def notificacoes(request):
    itens = request.user.notificacoes.all()[:100]
    resposta = render(request, "core/notificacoes.html", {"itens": itens})
    return resposta


@login_required
@require_POST
def notificacoes_marcar_lidas(request):
    request.user.notificacoes.filter(lida=False).update(lida=True)
    return redirect("notificacoes")


@login_required
def notificacao_abrir(request, pk):
    n = get_object_or_404(Notificacao, pk=pk, usuario=request.user)
    if not n.lida:
        n.lida = True
        n.save(update_fields=["lida"])
    return redirect(n.link or "notificacoes")


@login_required
def baixar_documento(request, pk):
    doc = get_object_or_404(Documento.objects.select_related("estagio"), pk=pk)
    if not doc.pode_ver(request.user):
        raise PermissionDenied
    try:
        arquivo = doc.arquivo.open("rb")
    except FileNotFoundError as exc:
        raise Http404("Arquivo não encontrado") from exc
    nome = doc.nome_original or doc.arquivo.name.rsplit("/", 1)[-1]
    tipo = mimetypes.guess_type(nome)[0] or "application/octet-stream"
    inline = tipo.startswith("image/") or tipo == "application/pdf"
    return FileResponse(arquivo, as_attachment=not inline, filename=nome, content_type=tipo)


@login_required
@require_POST
def excluir_documento(request, pk):
    doc = get_object_or_404(Documento, pk=pk)
    if not (request.user.is_superuser or request.user.pk in (doc.orientador_id, doc.enviado_por_id)):
        raise PermissionDenied
    destino = doc.estagio.get_absolute_url() + "?aba=arquivos" if doc.estagio_id else "/documentos/"
    doc.arquivo.delete(save=False)
    doc.delete()
    messages.success(request, "Arquivo removido.")
    return redirect(destino)
