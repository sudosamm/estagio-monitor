"""Equipe da concedente (responsável pela concedente e escola) e “Vou me ausentar” do supervisor."""
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .. import auditoria, equipe as eq
from ..forms import MembroEquipeForm, SubstituicaoForm
from ..models import Estagio, Justificativa, LocalEstagio, Registro, Substituicao, Usuario
from ..seguranca import gerar_codigo, liberar_primeiro_acesso
from ..services import criar_usuario, preparar_lote, status_hoje
from .base import destino_seguro


@login_required
def minha_equipe(request):
    """Atalho do menu: a concedente de que a pessoa é responsável (ou a lista, se forem várias)."""
    ids = request.user.ids_geridas()
    if not ids:
        raise PermissionDenied
    if len(ids) == 1:
        return redirect("equipe_concedente", next(iter(ids)))
    locais = LocalEstagio.objects.filter(pk__in=ids)
    return render(request, "core/equipe_escolher.html", {"locais": locais})


@login_required
def equipe_concedente(request, pk):
    local = get_object_or_404(LocalEstagio, pk=pk)
    user = request.user
    if not eq.pode_gerir(user, local):
        raise PermissionDenied
    escola = user.pode("contas")
    membros = eq.equipe_de(local).annotate(
        n_estagios=Count("estagios_supervisionados", filter=Q(estagios_supervisionados__ativo=True,
                                                              estagios_supervisionados__local=local)))
    form_membro = MembroEquipeForm(prefix="m")
    form_sub = SubstituicaoForm(prefix="s", equipe=membros, initial={"inicio": timezone.localdate()})
    acao = request.POST.get("acao", "")
    voltar = reverse("equipe_concedente", args=[local.pk])

    if request.method == "POST":
        if acao == "adicionar":
            form_membro = MembroEquipeForm(request.POST, prefix="m")
            if form_membro.is_valid():
                d = form_membro.cleaned_data
                novo = criar_usuario(d["nome_completo"], Usuario.Papel.SUPERVISOR, user, concedente=local,
                                     cargo=d["cargo"], telefone=d["telefone"], email=d["email"])
                auditoria.registrar(request, "EQUIPE", f"Cadastrou {novo.nome_completo} na equipe", alvo=local)
                return _folha(request, [(novo, gerar_codigo(novo))], f"Acesso de {novo.nome_completo}", voltar)
        elif acao == "substituir":
            form_sub = SubstituicaoForm(request.POST, prefix="s", equipe=membros)
            if form_sub.is_valid():
                d = form_sub.cleaned_data
                erros = eq.validar_substituicao(local, d["substituto"], d["titular"], d["inicio"], d["fim"])
                if erros:
                    for e in erros:
                        form_sub.add_error(None, e)
                else:
                    eq.criar_substituicao(local, d["substituto"], d["titular"], d["inicio"], d["fim"], d["motivo"],
                                          user, request)
                    messages.success(request, f"{d['substituto'].primeiro_nome} pode confirmar presenças de "
                                              f"{d['inicio']:%d/%m} a {d['fim']:%d/%m}.")
                    return redirect(voltar)
        elif acao == "revogar":
            s = get_object_or_404(Substituicao, pk=request.POST.get("id"), concedente=local, revogada_em__isnull=True)
            eq.revogar(s, user, request)
            messages.success(request, "Permissão encerrada.")
            return redirect(voltar)
        elif acao in ("codigo", "desativar", "reativar", "responsavel"):
            alvo = get_object_or_404(membros, pk=request.POST.get("id"))
            return _acao_conta(request, local, alvo, acao, escola, voltar)

    hoje = timezone.localdate()
    estagios = preparar_lote(Estagio.objects.filter(local=local, ativo=True)
                             .select_related("estagiario", "supervisor", "curso"), hoje, totais=False)
    pendentes = dict(Registro.objects.filter(estagio__in=estagios, confirmacao=Registro.Confirmacao.PENDENTE,
                                             data__lte=hoje)
                     .exclude(justificativa__status=Justificativa.Status.PENDENTE)
                     .values_list("estagio").annotate(n=Count("pk")))
    for e in estagios:
        e.st, e.n_pendentes = status_hoje(e), pendentes.get(e.pk, 0)
    subs = list(local.substituicoes.select_related("substituto", "titular", "criada_por")
                .filter(Q(revogada_em__isnull=True, fim__gte=hoje) | Q(criada_em__gte=timezone.now() - timedelta(days=60))))
    return render(request, "core/equipe.html", {
        "local": local, "membros": membros, "estagios": estagios, "form_membro": form_membro, "form_sub": form_sub,
        "subs": subs, "escola": escola, "responsaveis": set(local.responsaveis.values_list("pk", flat=True)),
        "pode_conta": {m.pk: eq.pode_mexer_na_conta(user, m, local) for m in membros} if not escola else {},
    })


def _folha(request, linhas, titulo, voltar):
    from .orientador import _folha as folha

    return folha(request, linhas, titulo, "Entregue o código só para a própria pessoa. Ele vale 30 dias e uma vez.",
                 voltar=voltar)


def _acao_conta(request, local, alvo, acao, escola, voltar):
    user = request.user
    if acao == "responsavel":
        if not escola:
            raise PermissionDenied
        if local.responsaveis.filter(pk=alvo.pk).exists():
            alvo.concedentes_geridas.remove(local)
            auditoria.registrar(request, "EQUIPE", f"Tirou {alvo.nome_completo} de responsável", alvo=local)
            messages.success(request, f"{alvo.primeiro_nome} deixou de ser responsável por {local}.")
        else:
            alvo.concedentes_geridas.add(local)
            auditoria.registrar(request, "EQUIPE", f"Fez {alvo.nome_completo} responsável", alvo=local)
            messages.success(request, f"{alvo.primeiro_nome} agora é responsável por {local}: cadastra a equipe e as "
                                      "substituições.")
        return redirect(voltar)
    if escola:  # a escola usa as telas de contas, que já têm as regras dela
        return redirect("editar_usuario", alvo.pk)
    if not eq.pode_mexer_na_conta(user, alvo, local):
        messages.error(request, "Essa conta também é usada em outra concedente: peça à escola.")
        return redirect(voltar)
    if acao == "codigo":
        codigo = liberar_primeiro_acesso(alvo)
        auditoria.registrar(request, "EQUIPE", f"Gerou novo acesso para {alvo.nome_completo}", alvo=local)
        return _folha(request, [(alvo, codigo)], f"Novo acesso de {alvo.nome_completo}", voltar)
    if acao == "desativar":
        if alvo.estagios_supervisionados.filter(ativo=True).exists():
            messages.error(request, f"{alvo.primeiro_nome} ainda é supervisor(a) de estagiários. Peça à escola para "
                                    "trocar o supervisor antes de desativar.")
            return redirect(voltar)
        alvo.is_active = False
        alvo.save(update_fields=["is_active"])
        Substituicao.objects.filter(substituto=alvo, revogada_em__isnull=True).update(revogada_em=timezone.now(),
                                                                                      revogada_por=user)
        auditoria.registrar(request, "EQUIPE", f"Desativou a conta de {alvo.nome_completo}", alvo=local)
        messages.success(request, f"Conta de {alvo.primeiro_nome} desativada.")
    else:
        alvo.is_active = True
        alvo.save(update_fields=["is_active"])
        auditoria.registrar(request, "EQUIPE", f"Reativou a conta de {alvo.nome_completo}", alvo=local)
        messages.success(request, f"Conta de {alvo.primeiro_nome} reativada.")
    return redirect(voltar)


@login_required
@require_POST
def indicar_substituto(request):
    """O próprio supervisor indica um colega da concedente para confirmar as presenças enquanto estiver fora."""
    user = request.user
    if not user.is_supervisor:
        raise PermissionDenied
    local = get_object_or_404(LocalEstagio, pk=request.POST.get("concedente"), supervisores=user)
    form = SubstituicaoForm(request.POST, prefix="s", equipe=eq.equipe_de(local), titular_fixo=user)
    if form.is_valid():
        d = form.cleaned_data
        erros = eq.validar_substituicao(local, d["substituto"], user, d["inicio"], d["fim"])
        if not erros:
            eq.criar_substituicao(local, d["substituto"], user, d["inicio"], d["fim"], d["motivo"], user, request)
            messages.success(request, f"{d['substituto'].primeiro_nome} vai confirmar as presenças dos seus estagiários "
                                      f"de {d['inicio']:%d/%m} a {d['fim']:%d/%m}.")
            return redirect("painel_supervisor")
        for e in erros:
            messages.error(request, e)
    else:
        for erros in form.errors.values():
            messages.error(request, " ".join(erros))
    return redirect("painel_supervisor")


@login_required
@require_POST
def encerrar_substituicao(request, pk):
    s = get_object_or_404(Substituicao, pk=pk, revogada_em__isnull=True)
    user = request.user
    if not (s.titular_id == user.pk or s.substituto_id == user.pk or eq.pode_gerir(user, s.concedente)):
        raise PermissionDenied
    eq.revogar(s, user, request)
    messages.success(request, "Permissão encerrada.")
    return redirect(destino_seguro(request, reverse("painel_supervisor")))
