"""Autoavaliação e avaliação do orientador, preenchidas pelo estagiário, com o texto pronto para o SICE."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..avaliacoes import RespostasForm, linhas, perguntas, pode_ler
from ..forms import PerguntaAvaliacaoForm
from ..models import Avaliacao, Configuracao, Estagio, PerguntaAvaliacao
from ..services import ano_em_uso, notificar
from .base import orientador_requerido, permissao
from .orientador import contexto_ano, filtrar_lista, turmas_do_ano

TIPOS = dict(PerguntaAvaliacao.Tipo.choices)


def _meu_estagio(request):
    e = (Estagio.objects.filter(estagiario=request.user).select_related("orientador", "estagiario")
         .order_by("-ativo", "-data_inicio").first())
    if not e:
        raise PermissionDenied
    return e


def _tipo(tipo):
    tipo = tipo.upper()
    if tipo not in TIPOS:
        raise Http404
    return tipo


@login_required
def minhas_avaliacoes(request):
    estagio = _meu_estagio(request)
    cfg = Configuracao.atual()
    feitas = {a.tipo: a for a in estagio.avaliacoes.all()}
    itens = [{"tipo": t, "rotulo": r, "av": feitas.get(t), "n": len(perguntas(t))} for t, r in TIPOS.items()]
    return render(request, "core/avaliacoes_estagiario.html", {"e": estagio, "itens": itens, "config": cfg})


@login_required
def responder_avaliacao(request, tipo):
    tipo = _tipo(tipo)
    estagio = _meu_estagio(request)
    cfg = Configuracao.atual()
    av = Avaliacao.objects.filter(estagio=estagio, tipo=tipo).first()
    if not cfg.avaliacoes_abertas and not av:
        messages.info(request, "As avaliações ainda não foram liberadas pela escola.")
        return redirect("minhas_avaliacoes")
    lista = perguntas(tipo)
    inicial = {f"p{k}": v for k, v in (av.respostas if av else {}).items()}
    form = RespostasForm(request.POST if request.method == "POST" else None, initial=inicial, perguntas=lista)
    if request.method == "POST" and form.is_valid():
        concluir = request.POST.get("acao") == "concluir"
        if not concluir or form.conferir_obrigatorias():
            av = av or Avaliacao(estagio=estagio, tipo=tipo)
            av.respostas = form.respostas()
            primeira_vez = concluir and not av.concluida_em
            if concluir:
                av.concluida_em = av.concluida_em or timezone.now()
            av.save()
            if primeira_vez:
                notificar([estagio.orientador], f"{estagio.estagiario.primeiro_nome} concluiu a {TIPOS[tipo].lower()}.",
                          "/avaliacoes/escola/")
                messages.success(request, "Avaliação concluída. Agora é só copiar as respostas para o SICE.")
                return redirect("copiar_avaliacao", tipo=tipo.lower())
            messages.success(request, "Respostas salvas." if not concluir else "Avaliação atualizada.")
            if concluir:
                return redirect("copiar_avaliacao", tipo=tipo.lower())
            return redirect("responder_avaliacao", tipo=tipo.lower())
    return render(request, "core/avaliacao_form.html", {
        "e": estagio, "tipo": tipo, "rotulo": TIPOS[tipo], "form": form, "av": av, "config": cfg,
    })


@login_required
def copiar_avaliacao(request, tipo):
    tipo = _tipo(tipo)
    estagio = _meu_estagio(request)
    av = Avaliacao.objects.filter(estagio=estagio, tipo=tipo).first()
    if not av or not av.concluida_em:
        return redirect("responder_avaliacao", tipo=tipo.lower())
    if request.method == "POST":
        av.copiada_sice_em = None if request.POST.get("acao") == "desfazer" else timezone.now()
        av.save(update_fields=["copiada_sice_em", "atualizada_em"])
        if av.copiada_sice_em:
            messages.success(request, "Pronto! Marcamos que você já colou esta avaliação no SICE.")
        return redirect("minhas_avaliacoes")
    texto = "\n\n".join(f"{p.enunciado}\n{r or '—'}" for p, r in linhas(av))
    return render(request, "core/avaliacao_copiar.html", {
        "e": estagio, "tipo": tipo, "rotulo": TIPOS[tipo], "av": av, "linhas": linhas(av), "texto": texto,
        "config": Configuracao.atual(),
    })


# ---------------------------------------------------------------- escola


@orientador_requerido
def avaliacoes_escola(request):
    ano = ano_em_uso(request)
    qs, f = filtrar_lista(request, ano)
    estagios = list(qs.order_by("estagiario__nome_completo"))
    por = {(a.estagio_id, a.tipo): a for a in Avaliacao.objects.filter(estagio__in=estagios)}
    linhas_ = []
    tot = {t: {"feitas": 0, "sice": 0} for t in TIPOS}
    for e in estagios:
        celulas = []
        for t in TIPOS:
            a = por.get((e.pk, t))
            if a and a.concluida_em:
                tot[t]["feitas"] += 1
                tot[t]["sice"] += bool(a.copiada_sice_em)
            celulas.append((t, a, bool(a and pode_ler(request.user, a))))
        linhas_.append({"e": e, "celulas": celulas})
    return render(request, "core/avaliacoes_escola.html", {
        **contexto_ano(request, ano), "f": f, "linhas": linhas_, "tipos": TIPOS, "tot": tot, "total": len(estagios),
        "turmas": turmas_do_ano(request.user, ano), "config": Configuracao.atual(),
    })


@login_required
def ver_avaliacao(request, pk):
    av = get_object_or_404(Avaliacao.objects.select_related("estagio__estagiario", "estagio__orientador"), pk=pk)
    if not pode_ler(request.user, av):
        raise PermissionDenied
    return render(request, "core/avaliacao_ver.html", {"av": av, "e": av.estagio, "linhas": linhas(av)})


@permissao("avaliacoes")
def perguntas_avaliacao(request, pk=None):
    editando = get_object_or_404(PerguntaAvaliacao, pk=pk) if pk else None
    form = PerguntaAvaliacaoForm(request.POST or None, instance=editando,
                                 initial={"avaliacao": request.GET.get("tipo", "AUTO")} if not editando else None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Pergunta salva.")
        return redirect("perguntas_avaliacao")
    grupos = [(r, PerguntaAvaliacao.objects.filter(avaliacao=t)) for t, r in TIPOS.items()]
    return render(request, "core/perguntas_avaliacao.html", {"form": form, "editando": editando, "grupos": grupos})


@permissao("avaliacoes")
@require_POST
def avisar_avaliacoes(request):
    """Avisa os estagiários ativos (que o usuário acompanha) que ainda não concluíram as avaliações."""
    from ..services import estagios_visiveis

    estagios = estagios_visiveis(request.user).filter(ativo=True).select_related("estagiario")
    concluidas = {}
    for a in Avaliacao.objects.filter(estagio__in=estagios, concluida_em__isnull=False):
        concluidas.setdefault(a.estagio_id, set()).add(a.tipo)
    pendentes = [e.estagiario for e in estagios if concluidas.get(e.pk, set()) != set(TIPOS)]
    notificar(pendentes, "Faltam as suas avaliações do estágio (autoavaliação e avaliação do orientador). "
                         "Responda no sistema e copie as respostas para o SICE.", "/avaliacoes/")
    messages.success(request, f"Lembrete enviado para {len(pendentes)} estagiário(s).")
    return redirect("avaliacoes_escola")
