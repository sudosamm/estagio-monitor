"""Autoavaliação e avaliação do orientador, mês a mês como no SICE, com o texto pronto para copiar lá."""
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..avaliacoes import (
    SIGLAS_MES, RespostasForm, linhas, mes_de, meses_do_estagio, nome_mes, perguntas, pode_ler, quadro,
)
from ..forms import PerguntaAvaliacaoForm
from ..models import Avaliacao, Configuracao, Estagio, PerguntaAvaliacao
from ..services import ano_em_uso, notificar
from .base import orientador_requerido, permissao
from .orientador import contexto_ano, filtrar_lista, turmas_do_ano

TIPOS = {t: r for t, r in PerguntaAvaliacao.Tipo.choices if t in ("AUTO", "ORIENTADOR")}  # mensais, do estagiário
TODOS_TIPOS = dict(PerguntaAvaliacao.Tipo.choices)


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


def _mes(estagio, texto):
    try:
        mes = date.fromisoformat(texto + "-01")
    except ValueError as exc:
        raise Http404 from exc
    if mes not in meses_do_estagio(estagio):
        raise Http404
    return mes


@login_required
def minhas_avaliacoes(request):
    estagio = _meu_estagio(request)
    linhas_, faltam = quadro(estagio)
    return render(request, "core/avaliacoes_estagiario.html", {
        "e": estagio, "linhas": linhas_, "faltam": faltam, "tipos": TIPOS, "config": Configuracao.atual(),
        "mes_atual": mes_de(timezone.localdate()),
    })


@login_required
def responder_avaliacao(request, tipo, mes):
    tipo = _tipo(tipo)
    estagio = _meu_estagio(request)
    mes = _mes(estagio, mes)
    cfg = Configuracao.atual()
    av = Avaliacao.objects.filter(estagio=estagio, tipo=tipo, mes=mes).first()
    if not cfg.avaliacoes_abertas and not av:
        messages.info(request, "As avaliações ainda não foram liberadas pela escola.")
        return redirect("minhas_avaliacoes")
    lista = perguntas(tipo)
    inicial = {f"p{k}": v for k, v in (av.respostas if av else {}).items()}
    form = RespostasForm(request.POST if request.method == "POST" else None, initial=inicial, perguntas=lista)
    if request.method == "POST" and form.is_valid():
        concluir = request.POST.get("acao") == "concluir"
        if not concluir or form.conferir_obrigatorias():
            av = av or Avaliacao(estagio=estagio, tipo=tipo, mes=mes)
            av.respostas = form.respostas()
            primeira_vez = concluir and not av.concluida_em
            if concluir:
                av.concluida_em = av.concluida_em or timezone.now()
            av.save()
            if primeira_vez and tipo == PerguntaAvaliacao.Tipo.AUTO:  # a do orientador é anônima para ele
                notificar([estagio.orientador], f"{estagio.estagiario.primeiro_nome} concluiu a {TIPOS[tipo].lower()} "
                          f"de {nome_mes(mes)}.", "/avaliacoes/escola/")
            if concluir:
                messages.success(request, "Avaliação concluída. Agora é só copiar as respostas para o SICE.")
                return redirect("copiar_avaliacao", tipo=tipo.lower(), mes=f"{mes:%Y-%m}")
            messages.success(request, "Respostas salvas. Dá para continuar depois.")
            return redirect("responder_avaliacao", tipo=tipo.lower(), mes=f"{mes:%Y-%m}")
    return render(request, "core/avaliacao_form.html", {
        "e": estagio, "tipo": tipo, "rotulo": TIPOS[tipo], "form": form, "av": av, "config": cfg, "mes": mes,
        "nome_mes": nome_mes(mes),
    })


@login_required
def copiar_avaliacao(request, tipo, mes):
    tipo = _tipo(tipo)
    estagio = _meu_estagio(request)
    mes = _mes(estagio, mes)
    av = Avaliacao.objects.filter(estagio=estagio, tipo=tipo, mes=mes).first()
    if not av or not av.concluida_em:
        return redirect("responder_avaliacao", tipo=tipo.lower(), mes=f"{mes:%Y-%m}")
    if request.method == "POST":
        av.copiada_sice_em = None if request.POST.get("acao") == "desfazer" else timezone.now()
        av.save(update_fields=["copiada_sice_em", "atualizada_em"])
        if av.copiada_sice_em:
            messages.success(request, f"Pronto! {TIPOS[tipo]} de {nome_mes(mes)} marcada como colada no SICE.")
        return redirect("minhas_avaliacoes")
    cabecalho = [("Mês de Referência", SIGLAS_MES[mes.month - 1]), ("Ano", str(mes.year))]
    if tipo == PerguntaAvaliacao.Tipo.ORIENTADOR:
        cabecalho.append(("Orientador", estagio.orientador.nome_completo.upper()))
    lin = linhas(av)
    texto = "\n\n".join(f"{p.enunciado}\n{r or '—'}" for p, r in lin)
    return render(request, "core/avaliacao_copiar.html", {
        "e": estagio, "tipo": tipo, "rotulo": TIPOS[tipo], "av": av, "linhas": lin, "texto": texto,
        "config": Configuracao.atual(), "mes": mes, "nome_mes": nome_mes(mes), "cabecalho": cabecalho,
    })


# ---------------------------------------------------------------- escola


@orientador_requerido
def avaliacoes_escola(request):
    ano = ano_em_uso(request)
    qs, f = filtrar_lista(request, ano)
    estagios = list(qs.order_by("estagiario__nome_completo"))
    atual = mes_de(timezone.localdate())
    opcoes = [atual]
    for _ in range(11):
        opcoes.append(date(opcoes[-1].year - (opcoes[-1].month == 1), (opcoes[-1].month - 2) % 12 + 1, 1))
    try:
        mes = date.fromisoformat(request.GET.get("mes", "") + "-01")
    except ValueError:
        mes = atual
    por = {(a.estagio_id, a.tipo): a for a in Avaliacao.objects.filter(estagio__in=estagios, mes=mes)}
    concluidas = {}
    for a in Avaliacao.objects.filter(estagio__in=estagios, concluida_em__isnull=False).values("estagio_id", "mes", "tipo"):
        concluidas.setdefault(a["estagio_id"], set()).add((a["mes"], a["tipo"]))
    linhas_, tot = [], {t: {"feitas": 0, "sice": 0} for t in TIPOS}
    cobrados = 0
    for e in estagios:
        meses = meses_do_estagio(e)
        if mes not in meses:
            continue
        cobrados += 1
        celulas = []
        for t in TIPOS:
            a = por.get((e.pk, t))
            if a and a.concluida_em:
                tot[t]["feitas"] += 1
                tot[t]["sice"] += bool(a.copiada_sice_em)
            celulas.append((t, a, bool(a and pode_ler(request.user, a))))
        atrasados = sum(1 for m in meses if m < mes and any((m, t) not in concluidas.get(e.pk, set()) for t in TIPOS))
        linhas_.append({"e": e, "celulas": celulas, "atrasados": atrasados})
    return render(request, "core/avaliacoes_escola.html", {
        **contexto_ano(request, ano), "f": f, "linhas": linhas_, "tipos": TIPOS, "tot": tot, "total": cobrados,
        "turmas": turmas_do_ano(request.user, ano), "config": Configuracao.atual(), "mes": mes, "opcoes": opcoes,
        "nome_mes": nome_mes(mes),
    })


@orientador_requerido
def avaliacoes_sobre_mim(request):
    """O orientador recebe as respostas das avaliações sobre ele juntas e sem nomes."""
    from ..avaliacoes import MIN_ANONIMATO, resumo_anonimo

    texto = request.GET.get("mes", "")
    try:
        mes = date.fromisoformat(texto + "-01") if texto else None
    except ValueError:
        mes = None
    meses = sorted(set(Avaliacao.objects.filter(tipo=PerguntaAvaliacao.Tipo.ORIENTADOR, concluida_em__isnull=False,
                                                estagio__orientador=request.user).values_list("mes", flat=True)),
                   reverse=True)
    return render(request, "core/avaliacoes_sobre_mim.html", {
        "r": resumo_anonimo(request.user, mes), "mes": mes, "meses": meses, "minimo": MIN_ANONIMATO,
        "nome_mes": nome_mes(mes) if mes else "todos os meses",
    })


@login_required
def ver_avaliacao(request, pk):
    av = get_object_or_404(Avaliacao.objects.select_related("estagio__estagiario", "estagio__orientador"), pk=pk)
    if not pode_ler(request.user, av):
        raise PermissionDenied
    return render(request, "core/avaliacao_ver.html", {"av": av, "e": av.estagio, "linhas": linhas(av),
                                                       "nome_mes": nome_mes(av.mes)})


@permissao("avaliacoes")
def perguntas_avaliacao(request, pk=None):
    editando = get_object_or_404(PerguntaAvaliacao, pk=pk) if pk else None
    form = PerguntaAvaliacaoForm(request.POST or None, instance=editando,
                                 initial={"avaliacao": request.GET.get("tipo", "AUTO")} if not editando else None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Pergunta salva.")
        return redirect("perguntas_avaliacao")
    grupos = [(r, PerguntaAvaliacao.objects.filter(avaliacao=t).select_related("curso")) for t, r in TODOS_TIPOS.items()]
    return render(request, "core/perguntas_avaliacao.html", {"form": form, "editando": editando, "grupos": grupos})


def estagiarios_pendentes(estagios, mes):
    """Estagiários que ainda não concluíram as duas avaliações do mês."""
    feitas = {}
    for a in Avaliacao.objects.filter(estagio__in=estagios, mes=mes, concluida_em__isnull=False):
        feitas.setdefault(a.estagio_id, set()).add(a.tipo)
    return [e.estagiario for e in estagios if mes in meses_do_estagio(e) and feitas.get(e.pk, set()) != set(TIPOS)]


@permissao("avaliacoes")
@require_POST
def avisar_avaliacoes(request):
    from ..services import estagios_visiveis

    mes = mes_de(timezone.localdate())
    estagios = list(estagios_visiveis(request.user).filter(ativo=True).select_related("estagiario"))
    pendentes = estagiarios_pendentes(estagios, mes)
    notificar(pendentes, f"Faltam as suas avaliações de {nome_mes(mes)} (autoavaliação e avaliação do orientador). "
                         "Responda no sistema e copie as respostas para o SICE.", "/avaliacoes/")
    messages.success(request, f"Lembrete enviado para {len(pendentes)} estagiário(s).")
    return redirect("avaliacoes_escola")
