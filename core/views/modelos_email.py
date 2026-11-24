"""Configurações → E-mails: o administrador edita o texto de cada e-mail automático."""
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse

from .. import emails
from ..forms import ModeloEmailForm
from ..models import ModeloEmail
from .base import orientador_requerido


def _exemplo(request):
    return {"nome": request.user.primeiro_nome, "usuario": "maria.souza", "validade": "2 horas",
            "link": emails.endereco(request, "/exemplo-de-link/"), "quando": emails.quando(), "ip": "200.100.50.25",
            "tentativas": 3, "minutos": 15, "contato": "(85) 99999-0000",
            "mensagem": "Errei a senha várias vezes e o acesso foi bloqueado.", "quantidade": 3,
            "lista": "• Ana Souza — seg 16/11, 08:00–12:00 (4h)\n• Bruno Lima — seg 16/11, 08:00–12:00 (4h)",
            "mes": "outubro de 2026", "erro": "ValueError", "pagina": "/painel/", "origem": "core/views/orientador.py:120",
            "ocorrencias": 1}


@orientador_requerido
def lista(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    salvos = {m.tipo: m for m in ModeloEmail.objects.all()}
    itens = [(chave, t, salvos.get(chave)) for chave, t in emails.TIPOS.items()]
    return render(request, "core/modelos_email.html", {"itens": itens})


@orientador_requerido
def editar(request, tipo):
    if not request.user.is_superuser:
        raise PermissionDenied
    if tipo not in emails.TIPOS:
        raise Http404
    t = emails.TIPOS[tipo]
    salvo = ModeloEmail.objects.filter(tipo=tipo).first()
    assunto, corpo, ativo = emails.modelo(tipo)
    acao = request.POST.get("acao", "salvar")
    if acao == "padrao" and request.method == "POST":
        ModeloEmail.objects.filter(tipo=tipo).delete()
        messages.success(request, f"“{t.nome}” voltou ao texto padrão.")
        return redirect("modelo_email", tipo=tipo)
    form = ModeloEmailForm(request.POST or None, tipo=tipo, initial={"assunto": assunto, "corpo": corpo, "ativo": ativo})
    previa = None
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        if acao == "salvar":
            ModeloEmail.objects.update_or_create(tipo=tipo, defaults={
                "assunto": d["assunto"], "corpo": d["corpo"], "ativo": d["ativo"], "atualizado_por": request.user})
            messages.success(request, f"Texto de “{t.nome}” salvo.")
            return redirect("modelos_email")
        previa = emails.montar(tipo, assunto=d["assunto"], corpo=d["corpo"], **_exemplo(request))
        if acao == "teste":
            if not settings.EMAIL_ATIVO:
                messages.error(request, "O servidor de e-mail não está configurado.")
            elif not request.user.email:
                messages.error(request, "Cadastre o seu e-mail em Meus dados para receber o teste.")
            else:
                try:
                    send_mail(f"[TESTE] {previa[0]}", previa[1], settings.DEFAULT_FROM_EMAIL, [request.user.email])
                    messages.success(request, f"Teste enviado para {request.user.email} (com dados de exemplo).")
                except Exception as exc:  # noqa: BLE001
                    messages.error(request, f"O servidor de e-mail recusou o envio: {exc}")
    variaveis = [(v, emails.NOMES_VARIAVEIS[v]) for v in (*t.variaveis, *emails.COMUNS)]
    return render(request, "core/modelo_email.html", {
        "form": form, "tipo": tipo, "t": t, "salvo": salvo, "previa": previa, "variaveis": variaveis,
        "voltar": reverse("modelos_email"),
    })
