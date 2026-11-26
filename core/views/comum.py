import mimetypes
import time

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from escolas.pessoas import na_escola

from .. import emails
from ..forms import PerfilForm
from ..models import Configuracao, Documento, Estagio, Notificacao, Usuario
from ..services import estagios_visiveis


@login_required
def inicio(request):
    user = request.user
    if user.is_gestor:
        return redirect("painel")
    if user.is_responsavel:
        return redirect("responsavel_inicio")
    if user.is_supervisor:
        if not user.vinculado_a_concedente and user.candidaturas_feitas.exists():
            return redirect("minhas_candidaturas")  # conta criada na candidatura, ainda sem aprovação
        return redirect("painel_supervisor")
    estagios = list(estagios_visiveis(user).filter(ativo=True))
    if len(estagios) == 1:
        return redirect(estagios[0])
    return render(request, "core/estagiario_lista.html", {"estagios": estagios_visiveis(user)})


def confirmar_email(request, token):
    """Link do e-mail de confirmação. Funciona mesmo sem estar logado (o link abre no celular, por exemplo)."""
    user = emails.usuario_do_token(token)
    if user is None:
        messages.error(request, "Link de confirmação inválido ou vencido. Peça outro em Meus dados ou à escola.")
        return redirect("perfil" if request.user.is_authenticated else "login")
    novo = not user.email_confirmado_em
    if novo:
        user.email_confirmado_em = timezone.now()
        user.save(update_fields=["email_confirmado_em"])
    if user.deve_trocar_senha and not request.user.is_authenticated:
        # ainda não entrou: o mesmo link leva a criar a senha (como o “Esqueci minha senha”, que vale para e-mails
        # confirmados). O link de criar a senha vale 2 horas e uma vez só.
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        messages.success(request, f"E-mail {user.email} confirmado. Agora crie a sua senha.")
        return redirect("redefinir_senha_email", urlsafe_base64_encode(force_bytes(user.pk)),
                        default_token_generator.make_token(user))
    if novo:
        emails.enviar("EMAIL_CONFIRMADO", [user.email], nome=user.primeiro_nome, usuario=user.username)
        messages.success(request, f"E-mail {user.email} confirmado. Se esquecer a senha, use “Esqueci minha senha”.")
    else:
        messages.info(request, "Este e-mail já estava confirmado.")
    return redirect("perfil" if request.user.is_authenticated else "login")


@login_required
@require_POST
def reenviar_confirmacao(request):
    user = request.user
    if not user.email or user.email_confirmado_em:
        return redirect("perfil")
    if time.time() - request.session.get("confirmacao_enviada", 0) < 60:
        messages.info(request, "Aguarde um minuto para pedir outro link.")
    elif emails.enviar_confirmacao(request, user):
        request.session["confirmacao_enviada"] = time.time()
        messages.info(request, f"Enviamos um novo link para {user.email}.")
    else:
        messages.error(request, "O envio de e-mails não está disponível agora. Fale com a escola.")
    return redirect(request.POST.get("next") if url_has_allowed_host_and_scheme(
        request.POST.get("next"), {request.get_host()}) else "perfil")


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
        from ..sessoes import desconectar_todas

        outros = desconectar_todas(user, exceto_chave=request.session.session_key)
        emails.avisar_senha_alterada(request, user)
        messages.success(request, "Senha alterada com sucesso." + (
            f" Por segurança, {outros} outro(s) aparelho(s) conectado(s) foram desconectados." if outros else ""))
        return redirect("inicio")
    return render(request, "core/trocar_senha.html", {"form": form, "obrigatorio": obrigatorio})


@login_required
def perfil(request):
    config = Configuracao.atual()
    email_antes = (request.user.email or "").strip().lower()
    form = PerfilForm(request.POST or None, request.FILES or None, instance=request.user,
                      curriculos=config.curriculos_habilitados)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        messages.success(request, "Dados atualizados.")
        if user.email and user.email.strip().lower() != email_antes and emails.enviar_confirmacao(request, user):
            request.session["confirmacao_enviada"] = time.time()
            messages.info(request, f"Enviamos um link para {user.email}. Abra o e-mail e confirme (veja também o spam).")
        return redirect("perfil")
    from .. import dois_fatores
    from ..models import RegistroAcao

    from ..sessoes import ativas
    from .acessos import TIPOS_ACESSO

    acessos = RegistroAcao.objects.filter(usuario=request.user, tipo__in=TIPOS_ACESSO)[:3]
    from ..responsaveis import vinculos_de

    responsaveis = list(vinculos_de(request.user)) if request.user.is_estagiario else []
    return render(request, "core/perfil.html", {"form": form, "config": config, "acessos": acessos,
                                                "n_aparelhos": len(ativas(request.user)), "responsaveis": responsaveis,
                                                "pode_2fa": dois_fatores.pode_usar(request.user),
                                                "exige_2fa": dois_fatores.precisa(request.user)})


# Abrem no navegador só PDF e fotos comuns. SVG, HTML e o resto baixam, e qualquer arquivo enviado por usuário
# vai com CSP “sandbox”: mesmo que alguém mande um arquivo com script, ele não roda com a sessão de quem abriu.
TIPOS_INLINE = {"application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp"}


def resposta_arquivo(f, nome, tipo, inline=True):
    inline = inline and tipo in TIPOS_INLINE
    resposta = FileResponse(f, as_attachment=not inline, filename=nome,
                            content_type=tipo if inline else "application/octet-stream")
    if tipo != "application/pdf":  # o leitor de PDF do Chrome não abre em documento “sandbox”
        resposta["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"
    return resposta


def _servir(arquivo, nome, inline=True):
    try:
        f = arquivo.open("rb")
    except FileNotFoundError as exc:
        raise Http404 from exc
    tipo = mimetypes.guess_type(arquivo.name)[0] or "application/octet-stream"
    resposta = resposta_arquivo(f, nome, tipo, inline)
    resposta["Cache-Control"] = "private, max-age=86400"
    return resposta


def pode_ver_foto(user, alvo):
    """Dono, gestores, fotos de gestores, quem divide um estágio com a pessoa e quem pode ver o perfil profissional."""
    if user.pk == alvo.pk or user.is_gestor or alvo.is_gestor:
        return True
    if user.is_responsavel:  # o responsável vê a foto dos estudantes que acompanha
        from ..responsaveis import estudantes_de

        return estudantes_de(user).filter(pk=alvo.pk).exists()
    juntos = (Estagio.objects.filter(Q(estagiario=alvo) | Q(supervisor=alvo))
              .filter(Q(estagiario=user) | Q(supervisor=user) | Q(orientador=user)))
    if juntos.exists():
        return True
    return alvo.papel == Usuario.Papel.ESTAGIARIO and pode_ver_perfil_profissional(user, alvo)


@login_required
def foto_usuario(request, pk):
    """Fotos de perfil: nunca públicas, e só para quem tem motivo de ver (não dá para listar a escola toda)."""
    alvo = get_object_or_404(na_escola(Usuario.objects.all()), pk=pk)
    if not alvo.foto or not pode_ver_foto(request.user, alvo):
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
    return (alvo.perfil_visivel and Configuracao.atual().banco_talentos_habilitado
            and user.vinculado_a_concedente)  # conta de candidatura ainda não aprovada não vê o banco


@login_required
def curriculo_usuario(request, pk):
    alvo = get_object_or_404(na_escola(Usuario.objects.all()), pk=pk, papel=Usuario.Papel.ESTAGIARIO)
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
    if not (user.is_gestor or user.vinculado_a_concedente):  # conta de candidatura sem aprovação não vê
        raise PermissionDenied
    qs = na_escola(Usuario.objects.filter(papel=Usuario.Papel.ESTAGIARIO, is_active=True, perfil_visivel=True))
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
@require_POST
def trocar_tema(request):
    from ..models import Configuracao, Usuario

    tema = request.POST.get("tema", "")
    if Configuracao.atual().tema_escuro and tema in Usuario.Tema.values:
        request.user.tema = tema
        request.user.save(update_fields=["tema"])
    if request.headers.get("X-Requested-With") == "fetch":
        from django.http import JsonResponse

        return JsonResponse({"tema": request.user.tema.lower()})
    from django.utils.http import url_has_allowed_host_and_scheme

    volta = request.META.get("HTTP_REFERER", "")
    if not url_has_allowed_host_and_scheme(volta, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        volta = "/"
    return redirect(volta)


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
    return resposta_arquivo(arquivo, nome, tipo)


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


@login_required
@require_POST
def alternar_modo(request):
    """Liga ou desliga o modo administrador (só para administradores)."""
    from .. import auditoria
    from .base import destino_seguro

    user = request.user
    if not user.e_administrador:
        raise PermissionDenied
    user.modo_administrador = request.POST.get("modo") == "admin"
    user.save(update_fields=["modo_administrador"])
    auditoria.registrar(request, "GESTAO", "Ligou o modo administrador" if user.modo_administrador
                        else "Passou a usar a conta no modo orientador")
    if user.modo_administrador:
        messages.success(request, "Modo administrador ligado: você vê todos os estagiários e as telas de administração.")
    else:
        messages.success(request, "Modo orientador: agora você vê só os seus estagiários, como qualquer orientador. "
                                  "Para administrar, ligue de novo em Meus dados ou no menu da sua foto.")
    from django.urls import reverse

    destino = destino_seguro(request, reverse("painel"))
    if not user.modo_administrador and not destino.startswith(reverse("perfil")):
        destino = reverse("painel")  # a tela em que estava pode ser só de administração
    return redirect(destino)
