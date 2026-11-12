"""Encerramento do ano letivo e anonimização de dados antigos."""
from collections import Counter

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .. import encerramento as enc
from ..models import Anonimizacao, Configuracao, Encerramento
from ..services import anos_disponiveis, ano_referencia
from .base import permissao


@permissao("encerramento")
def encerramento(request):
    user = request.user
    anos = anos_disponiveis()
    ano = int(request.GET["ano"]) if request.GET.get("ano", "").isdigit() else ano_referencia()
    if request.method == "POST":
        acao = request.POST.get("acao")
        if acao == "encerrar":
            ano = int(request.POST.get("ano") or ano)
            e = enc.encerrar(
                user, ano, incluir_incompletos=bool(request.POST.get("incluir_incompletos")),
                desativar_contas=bool(request.POST.get("desativar_contas")),
                desativar_supervisores=bool(request.POST.get("desativar_supervisores")),
                inativar_turmas=bool(request.POST.get("inativar_turmas")), avancar_ano=bool(request.POST.get("avancar_ano")),
            )
            r = e.resumo
            messages.success(request, f"Ano {ano} encerrado: {len(r['estagios'])} estágio(s) encerrado(s), "
                                      f"{len(r['contas']) + len(r['supervisores'])} conta(s) desativada(s), "
                                      f"{len(r['turmas'])} turma(s) arquivada(s). Dá para desfazer por "
                                      f"{enc.DIAS_PARA_DESFAZER} dias.")
            return redirect(reverse("encerramento") + f"?ano={ano}")
        if acao == "desfazer":
            e = get_object_or_404(Encerramento, pk=request.POST.get("encerramento"))
            if enc.pode_desfazer(e):
                enc.desfazer(e, user)
                messages.success(request, f"Encerramento de {e.ano} desfeito: estágios, contas e turmas reativados.")
            else:
                messages.error(request, "Esse encerramento não pode mais ser desfeito.")
            return redirect(reverse("encerramento") + f"?ano={e.ano}")
        if acao == "anonimizar":
            if request.POST.get("confirmacao", "").strip().upper() != "ANONIMIZAR":
                messages.error(request, "Para anonimizar, digite ANONIMIZAR no campo de confirmação.")
            else:
                feitos = enc.anonimizar(enc.candidatos_anonimizacao(user), user)
                messages.success(request, f"Dados pessoais de {feitos['pessoas']} estagiário(s) anonimizados; "
                                          f"{feitos['arquivos']} arquivo(s) apagado(s).")
            return redirect(reverse("encerramento") + "#lgpd")
    candidatos = enc.candidatos_anonimizacao(user)
    historico = Encerramento.objects.select_related("feito_por", "desfeito_por")[:20]
    for h in historico:
        h.desfazivel = enc.pode_desfazer(h)
        h.n_contas = len(h.resumo.get("contas", [])) + len(h.resumo.get("supervisores", []))
    return render(request, "core/encerramento.html", {
        "ano": ano, "anos": anos, "d": enc.diagnostico(user, ano), "historico": historico,
        "candidatos_por_ano": sorted(Counter(e.turma.ano_estagio for e in candidatos).items()),
        "n_candidatos": len({e.estagiario_id for e in candidatos}), "limite": enc.ano_limite(),
        "config": Configuracao.atual(), "anonimizacoes": Anonimizacao.objects.select_related("feita_por")[:10],
        "dias_desfazer": enc.DIAS_PARA_DESFAZER, "ja_encerrado": any(h.ano == ano and not h.desfeito_em for h in historico),
    })
