"""“Acompanhamento de Visita” do SICE: o orientador avalia o estagiário na visita e copia para o SICE."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from ..avaliacoes import RespostasForm, linhas, perguntas
from ..forms import DataInput, Formulario
from ..models import AcompanhamentoVisita, Agendamento, Configuracao, PerguntaAvaliacao
from ..services import notificar
from .base import eh_orientador_do, pegar_estagio

PRATICA, ATITUDINAL = PerguntaAvaliacao.Tipo.PRATICA, PerguntaAvaliacao.Tipo.ATITUDINAL


class DadosVisitaForm(Formulario):
    data = forms.DateField(label="Data da visita", widget=DataInput())
    observacoes = forms.CharField(label="Observações", required=False, widget=forms.Textarea(attrs={"rows": 3}))
    intervencoes = forms.CharField(label="Intervenções", required=False, widget=forms.Textarea(attrs={"rows": 3}))


def _secoes(estagio):
    return [("Avaliação Prática", "Atividade de Estágio", perguntas(PRATICA, estagio.curso_id), "pratica"),
            ("Avaliação Atitudinal", "Critério Atitudinal", perguntas(ATITUDINAL), "atitudinal")]


@login_required
def acompanhamento_form(request, estagio_pk, pk=None):
    estagio = pegar_estagio(request, estagio_pk)
    if not eh_orientador_do(request.user, estagio):
        raise PermissionDenied
    ac = get_object_or_404(AcompanhamentoVisita, pk=pk, estagio=estagio) if pk else None
    ag = None
    if not ac and request.GET.get("visita", "").isdigit():
        ag = Agendamento.objects.filter(pk=request.GET["visita"], estagios=estagio).first()
        ac = AcompanhamentoVisita.objects.filter(agendamento=ag, estagio=estagio).first() if ag else None
        if ac:
            return redirect("acompanhamento_editar", estagio_pk=estagio.pk, pk=ac.pk)
    secoes = _secoes(estagio)
    todas = [p for _, _, ps, _ in secoes for p in ps]
    post = request.POST if request.method == "POST" else None
    inicial = {"data": ac.data if ac else (timezone.localtime(ag.data_hora).date() if ag and ag.data_hora
                                           else timezone.localdate()),
               "observacoes": ac.observacoes if ac else "", "intervencoes": ac.intervencoes if ac else ""}
    dados = DadosVisitaForm(post, initial=inicial, prefix="v")
    respostas = RespostasForm(post, initial={f"p{k}": v for k, v in (ac.respostas if ac else {}).items()},
                              perguntas=todas, prefix="r")
    if post and dados.is_valid() and respostas.is_valid() and respostas.conferir_obrigatorias():
        novo = ac is None
        ac = ac or AcompanhamentoVisita(estagio=estagio, agendamento=ag, autor=request.user)
        ac.data = dados.cleaned_data["data"]
        ac.observacoes = dados.cleaned_data["observacoes"].strip()
        ac.intervencoes = dados.cleaned_data["intervencoes"].strip()
        ac.respostas = respostas.respostas()
        ac.save()
        if novo:
            notificar([estagio.estagiario], f"{request.user.primeiro_nome} registrou o acompanhamento da visita de "
                      f"{ac.data:%d/%m}.", ac.get_absolute_url())
        messages.success(request, "Acompanhamento salvo. Agora é só lançar no SICE.")
        return redirect("acompanhamento_sice", pk=ac.pk)
    campos = {c.field.pergunta.pk: c for c in respostas}
    blocos = [(titulo, coluna, [campos[p.pk] for p in ps], chave) for titulo, coluna, ps, chave in secoes]
    return render(request, "core/acompanhamento_form.html", {
        "e": estagio, "ac": ac, "dados": dados, "blocos": blocos, "erros": bool(respostas.errors),
        "sem_pratica": not secoes[0][2],
    })


def _pegar(request, pk):
    ac = get_object_or_404(AcompanhamentoVisita.objects.select_related("estagio__estagiario", "estagio__orientador",
                                                                       "estagio__curso", "estagio__local",
                                                                       "estagio__turma"), pk=pk)
    e = ac.estagio
    if not (request.user.pk == e.estagiario_id or eh_orientador_do(request.user, e)):
        raise PermissionDenied
    return ac


def _contexto(ac):
    e = ac.estagio
    cfg = Configuracao.atual()
    cabecalho = [("Escola", cfg.nome_escola or "—"), ("Curso", e.curso.nome.upper()),
                 ("Aluno", e.estagiario.nome_completo.upper()), ("Concedente", (e.local.nome if e.local else "—").upper()),
                 ("Orientador", e.orientador.nome_completo.upper()), ("Data", f"{ac.data:%d/%m/%Y}")]
    secoes = [(titulo, coluna, linhas(ac, ps)) for titulo, coluna, ps, _ in _secoes(e)]
    return {"ac": ac, "e": e, "cabecalho": cabecalho, "secoes": secoes, "config": cfg}


@login_required
def acompanhamento_sice(request, pk):
    ac = _pegar(request, pk)
    if not eh_orientador_do(request.user, ac.estagio):
        raise PermissionDenied
    if request.method == "POST":
        ac.lancado_sice_em = None if request.POST.get("acao") == "desfazer" else timezone.now()
        ac.save(update_fields=["lancado_sice_em", "atualizado_em"])
        if ac.lancado_sice_em:
            messages.success(request, "Marcado como lançado no SICE.")
        return redirect(ac.estagio.get_absolute_url() + "?aba=agenda")
    return render(request, "core/acompanhamento_sice.html", _contexto(ac))


@login_required
def acompanhamento_ver(request, pk):
    """Leitura, como o relatório do SICE (o estagiário também vê o que o orientador registrou)."""
    return render(request, "core/acompanhamento_ver.html", _contexto(_pegar(request, pk)))
