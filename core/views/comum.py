import mimetypes

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from django.db.models import Q

from ..forms import PerfilForm
from ..models import Configuracao, Documento, Estagio, Notificacao, Usuario
from ..services import estagios_visiveis


@login_required
def inicio(request):
    user = request.user
    if user.is_gestor:
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
    config = Configuracao.atual()
    form = PerfilForm(request.POST or None, request.FILES or None, instance=request.user,
                      curriculos=config.curriculos_habilitados)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Dados atualizados.")
        return redirect("perfil")
    return render(request, "core/perfil.html", {"form": form, "config": config})


def _servir(arquivo, nome, inline=True):
    try:
        f = arquivo.open("rb")
    except FileNotFoundError as exc:
        raise Http404 from exc
    tipo = mimetypes.guess_type(arquivo.name)[0] or "application/octet-stream"
    resposta = FileResponse(f, as_attachment=not inline, filename=nome, content_type=tipo)
    resposta["Cache-Control"] = "private, max-age=86400"
    return resposta


@login_required
def foto_usuario(request, pk):
    """Fotos de perfil só para quem está logado (nunca públicas)."""
    alvo = get_object_or_404(Usuario, pk=pk)
    if not alvo.foto:
        raise Http404
    return _servir(alvo.foto, f"{alvo.username}.jpg")


@login_required
def logo_folha(request):
    config = Configuracao.atual()
    if not config.logo_folha:
        raise Http404
    return _servir(config.logo_folha, config.logo_folha.name.rsplit("/", 1)[-1])


def pode_ver_perfil_profissional(user, alvo):
    """Dono, orientadores, supervisor do próprio estágio e — com o banco de talentos aberto — supervisores."""
    if user.pk == alvo.pk or user.is_gestor:
        return True
    if not user.is_supervisor:
        return False
    if Estagio.objects.filter(estagiario=alvo, supervisor=user).exists():
        return True
    return alvo.perfil_visivel and Configuracao.atual().banco_talentos_habilitado


@login_required
def curriculo_usuario(request, pk):
    alvo = get_object_or_404(Usuario, pk=pk, papel=Usuario.Papel.ESTAGIARIO)
    if not alvo.curriculo or not pode_ver_perfil_profissional(request.user, alvo):
        raise Http404
    return _servir(alvo.curriculo, f"curriculo-{alvo.username}.pdf")


@login_required
def banco_talentos(request):
    """Perfis dos estagiários que autorizaram a exibição, para as concedentes escolherem."""
    config = Configuracao.atual()
    user = request.user
    if not (user.is_gestor or user.is_supervisor):
        raise PermissionDenied
    if not config.banco_talentos_habilitado and not user.is_gestor:
        raise Http404
    qs = Usuario.objects.filter(papel=Usuario.Papel.ESTAGIARIO, is_active=True, perfil_visivel=True)
    q, curso = request.GET.get("q", "").strip(), request.GET.get("curso", "")
    if q:
        qs = qs.filter(Q(nome_completo__icontains=q) | Q(habilidades__icontains=q) | Q(apresentacao__icontains=q))
    if curso:
        qs = qs.filter(estagios__curso_id=curso)
    pessoas = list(qs.distinct().prefetch_related("estagios__curso", "estagios__turma"))
    for p in pessoas:
        ultimo = max(p.estagios.all(), key=lambda e: e.data_inicio, default=None)
        p.curso_atual = ultimo.curso if ultimo else None
        p.turma_atual = ultimo.turma if ultimo else None
    from ..models import Curso

    return render(request, "core/talentos.html", {
        "pessoas": pessoas, "q": q, "curso": curso, "cursos": Curso.objects.all(), "config": config,
    })


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
    if not doc.arquivo:
        raise Http404("Documento entregue em papel")
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
