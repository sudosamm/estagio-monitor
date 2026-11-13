"""Check-in por QR code mostrado pelo supervisor."""
import time

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache

from .. import qrcheckin as qr
from ..models import Estagio, HistoricoRegistro, Registro, Usuario
from ..services import horas_padrao
from .supervisor import supervisor_requerido

PONTOS = [("entrada", "Marcar entrada"), ("saida_intervalo", "Saída para o intervalo"),
          ("volta_intervalo", "Volta do intervalo"), ("hora_saida", "Marcar saída")]


# ---------------------------------------------------------------- tela do supervisor


@supervisor_requerido
def qr_supervisor(request):
    return render(request, "core/qr_supervisor.html", {"troca": qr.TROCA})


@supervisor_requerido
@never_cache
def qr_novo(request):
    """Novo código + quem marcou hoje pelo QR (a tela do supervisor consulta a cada 20 s)."""
    url = request.build_absolute_uri(reverse("checkin_qr", args=[qr.gerar(request.user)]))
    hoje = timezone.localdate()
    feitos = (HistoricoRegistro.objects.filter(estagio__supervisor=request.user, acao=HistoricoRegistro.Acao.QRCODE,
                                               data=hoje)
              .select_related("estagio__estagiario").order_by("-em")[:30])
    return JsonResponse({
        "svg": qr.svg(url), "troca": qr.TROCA,
        "marcados": [{"nome": h.estagio.estagiario.nome_completo, "hora": timezone.localtime(h.em).strftime("%H:%M"),
                      "o_que": ", ".join(m[0].lower() for m in h.mudancas if m[0] in ("Entrada", "Saída",
                                         "Saída para o intervalo", "Volta do intervalo"))}
                     for h in feitos],
    })


# ---------------------------------------------------------------- lado do estagiário


@never_cache
def checkin_qr(request, token):
    """Link do QR: confere o código na hora e guarda na sessão (sobrevive ao login, se precisar entrar)."""
    sup_id = qr.ler(token)
    if not sup_id:
        return render(request, "core/qr_estagiario.html", {"erro": "Este QR code expirou. Peça para o supervisor mostrar "
                                                                    "a tela de novo e escaneie outra vez."}, status=410)
    request.session[qr.SESSAO] = {"s": sup_id, "em": time.time()}
    destino = reverse("checkin_qr_confirmar")
    if not request.user.is_authenticated:
        return redirect(f"{reverse('login')}?next={destino}")
    return redirect(destino)


@login_required
@never_cache
def checkin_qr_confirmar(request):
    dados = request.session.get(qr.SESSAO)
    if not dados or time.time() - dados.get("em", 0) > qr.SESSAO_VALIDADE:
        request.session.pop(qr.SESSAO, None)
        return render(request, "core/qr_estagiario.html", {"erro": "Escaneie o QR code do supervisor para marcar."})
    supervisor = Usuario.objects.filter(pk=dados["s"]).first()
    estagio = (Estagio.objects.filter(estagiario=request.user, supervisor_id=dados["s"], ativo=True)
               .select_related("estagiario", "supervisor").first())
    if not estagio:
        request.session.pop(qr.SESSAO, None)
        nome = supervisor.nome_completo if supervisor else "esse supervisor"
        return render(request, "core/qr_estagiario.html", {"erro": f"Este QR code é de {nome}, que não é seu supervisor. "
                                                                    "Use o QR do seu supervisor."})
    hoje = timezone.localdate()
    reg = Registro.objects.filter(estagio=estagio, data=hoje).first()
    presente = bool(reg and reg.situacao == Registro.Situacao.PRESENTE and reg.hora_chegada)
    opcoes = []
    if not presente:
        opcoes.append(PONTOS[0])
    elif not reg.hora_saida:
        escala = estagio.escala_em(hoje)
        if not reg.saida_intervalo and escala and escala.tem_intervalo:
            opcoes.append(PONTOS[1])
        elif reg.saida_intervalo and not reg.volta_intervalo:
            opcoes.append(PONTOS[2])
        opcoes.append(PONTOS[3])
    if request.method == "POST":
        acao = request.POST.get("acao")
        if acao not in dict(opcoes):
            messages.error(request, "Essa marcação não está disponível agora.")
            return redirect("checkin_qr_confirmar")
        request.session.pop(qr.SESSAO, None)  # cada marcação pede um QR novo
        agora = timezone.localtime().time().replace(second=0, microsecond=0)
        if acao == "entrada":
            reg = reg or Registro(estagio=estagio, data=hoje, registrado_por=request.user)
            reg.situacao = Registro.Situacao.PRESENTE
            reg.hora_chegada = agora
            reg.horas = reg.horas or horas_padrao(estagio, hoje) or 0
        else:
            setattr(reg, acao, agora)
            if acao == "hora_saida" and reg.calcular_horas():
                reg.horas = reg.calcular_horas()
        reg.confirmar(supervisor, Registro.Confirmacao.CONFIRMADA, "Confirmada pelo QR code do supervisor.")
        reg.anotar(request.user, HistoricoRegistro.Acao.QRCODE, request).save()
        rotulo = dict(PONTOS)[acao].replace("Marcar ", "").capitalize()
        messages.success(request, f"{rotulo} às {agora:%H:%M}, já confirmada por {supervisor.primeiro_nome}.")
        return redirect(estagio)
    return render(request, "core/qr_estagiario.html", {
        "e": estagio, "supervisor": supervisor, "reg": reg, "opcoes": opcoes, "agora": timezone.localtime(),
    })

