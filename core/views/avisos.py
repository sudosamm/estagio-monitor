"""Notificações no celular (inscrição de cada aparelho) e comunicados do orientador para a turma."""
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .. import push
from ..forms import ComunicadoForm
from ..models import Comunicado, InscricaoPush, Notificacao
from ..services import estagios_visiveis, notificar
from .base import orientador_requerido


@login_required
def push_chave(request):
    if not push.push_ativo():
        return JsonResponse({"ativo": False})
    return JsonResponse({"ativo": True, "chave": push.chave_publica()})


@login_required
@require_POST
def push_inscrever(request):
    try:
        dados = json.loads(request.body)
        endpoint, chaves = dados["endpoint"], dados["keys"]
        p256dh, auth = chaves["p256dh"], chaves["auth"]
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"ok": False, "erro": "Inscrição inválida."}, status=400)
    if not endpoint.startswith("https://") or len(endpoint) > 600:
        return JsonResponse({"ok": False, "erro": "Endereço de push inválido."}, status=400)
    InscricaoPush.objects.update_or_create(endpoint=endpoint, defaults={
        "usuario": request.user, "p256dh": p256dh[:200], "auth": auth[:100],
        "navegador": request.META.get("HTTP_USER_AGENT", "")[:200],
    })
    return JsonResponse({"ok": True})


@login_required
@require_POST
def push_cancelar(request):
    try:
        endpoint = json.loads(request.body).get("endpoint", "")
    except ValueError:
        endpoint = ""
    InscricaoPush.objects.filter(usuario=request.user, endpoint=endpoint).delete()
    return JsonResponse({"ok": True})


@login_required
@require_POST
def push_teste(request):
    n = Notificacao.objects.create(usuario=request.user, texto="Teste: as notificações estão funcionando neste aparelho.",
                                   link="/perfil/")
    enviados = push.enviar([n], assincrono=False)
    return JsonResponse({"ok": bool(enviados), "enviados": enviados})


# ---------------------------------------------------------------- comunicados


@orientador_requerido
def comunicados(request):
    user = request.user
    estagios = estagios_visiveis(user).filter(ativo=True)
    form = ComunicadoForm(request.POST or None, usuario=user)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        alvo = estagios
        partes = []
        if d.get("turma"):
            alvo = alvo.filter(turma=d["turma"])
            partes.append(f"turma {d['turma'].rotulo}")
        if d.get("curso"):
            alvo = alvo.filter(curso=d["curso"])
            partes.append(str(d["curso"]))
        if d.get("local"):
            alvo = alvo.filter(local=d["local"])
            partes.append(str(d["local"]))
        pessoas = set()
        if d["para"] in ("estagiarios", "todos"):
            alunos = {e.estagiario for e in alvo.select_related("estagiario") if e.estagiario.is_active}
            pessoas |= alunos
            if d.get("responsaveis"):
                from ..responsaveis import responsaveis_de

                pessoas |= set(responsaveis_de(alunos))
        if d["para"] in ("supervisores", "todos"):
            pessoas |= {e.supervisor for e in alvo.select_related("supervisor") if e.supervisor and e.supervisor.is_active}
        pessoas.discard(user)
        if not pessoas:
            form.add_error(None, "Ninguém recebe com esses filtros. Confira a turma, o curso ou a concedente.")
        else:
            quem = dict(form.fields["para"].choices)[d["para"]].lower()
            c = Comunicado.objects.create(autor=user, titulo=d["titulo"], texto=d["texto"],
                                          para=f"{quem}{' · ' + ' · '.join(partes) if partes else ''}"[:200])
            c.destinatarios.set(pessoas)
            notificar(pessoas, f"{user.primeiro_nome}: {d['titulo']}", c.get_absolute_url(), detalhe=d["texto"])
            messages.success(request, f"Aviso enviado para {len(pessoas)} pessoa{'s' if len(pessoas) > 1 else ''}.")
            return redirect("comunicados")
    enviados = Comunicado.objects.filter(autor=user).prefetch_related("destinatarios")[:50]
    if user.is_superuser:
        enviados = Comunicado.objects.select_related("autor").prefetch_related("destinatarios")[:50]
    return render(request, "core/comunicados.html", {"form": form, "enviados": enviados})


@login_required
def comunicado(request, pk):
    c = get_object_or_404(Comunicado.objects.select_related("autor"), pk=pk)
    autor = request.user.is_superuser or c.autor_id == request.user.pk
    if not (autor or c.destinatarios.filter(pk=request.user.pk).exists()):
        raise PermissionDenied
    return render(request, "core/comunicado.html", {"c": c, "autor": autor,
                                                    "n": c.destinatarios.count() if autor else None})


@login_required
def meus_comunicados(request):
    return render(request, "core/comunicados_recebidos.html", {
        "itens": request.user.comunicados_recebidos.select_related("autor")[:50],
    })
