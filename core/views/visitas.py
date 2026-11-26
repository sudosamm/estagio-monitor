"""“Acompanhamento de Visita” do SICE: o orientador avalia o estagiário na visita e copia para o SICE."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from escolas.marca import sistema_oficial

from ..avaliacoes import RespostasForm, linhas, perguntas
from ..forms import DataInput, Formulario
from ..models import AcompanhamentoVisita, Agendamento, Configuracao, PerguntaAvaliacao
from ..services import notificar
from .base import eh_orientador_do, pegar_estagio

PRATICA, ATITUDINAL = PerguntaAvaliacao.Tipo.PRATICA, PerguntaAvaliacao.Tipo.ATITUDINAL


LIMITE_TEXTO = 300  # como no SICE


def _texto(rotulo, obrigatorio=False):
    return forms.CharField(label=rotulo, required=obrigatorio, max_length=LIMITE_TEXTO,
                           widget=forms.Textarea(attrs={"rows": 3, "maxlength": LIMITE_TEXTO}))


class DadosVisitaForm(Formulario):
    data = forms.DateField(label="Data da visita", widget=DataInput())
    observacoes = _texto("Observações", obrigatorio=True)
    intervencoes = _texto("Intervenções")
    observacoes_atitudinal = _texto("Observações", obrigatorio=True)
    intervencoes_atitudinal = _texto("Intervenções")

    CAMPOS = ("observacoes", "intervencoes", "observacoes_atitudinal", "intervencoes_atitudinal")


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
               **{c: getattr(ac, c) if ac else "" for c in DadosVisitaForm.CAMPOS}}
    dados = DadosVisitaForm(post, initial=inicial, prefix="v")
    respostas = RespostasForm(post, initial={f"p{k}": v for k, v in (ac.respostas if ac else {}).items()},
                              perguntas=todas, prefix="r")
    if post and dados.is_valid() and respostas.is_valid() and respostas.conferir_obrigatorias():
        novo = ac is None
        ac = ac or AcompanhamentoVisita(estagio=estagio, agendamento=ag, autor=request.user)
        ac.data = dados.cleaned_data["data"]
        for c in DadosVisitaForm.CAMPOS:
            setattr(ac, c, dados.cleaned_data[c].strip())
        ac.respostas = respostas.respostas()
        ac.save()
        if novo:
            notificar([estagio.estagiario], f"{request.user.primeiro_nome} registrou o acompanhamento da visita de "
                      f"{ac.data:%d/%m}.", ac.get_absolute_url())
        messages.success(request, f"Acompanhamento salvo. Agora é só lançar no {sistema_oficial()}.")
        return redirect("acompanhamento_sice", pk=ac.pk)
    campos = {c.field.pergunta.pk: c for c in respostas}
    textos = {"pratica": (dados["observacoes"], dados["intervencoes"]),
              "atitudinal": (dados["observacoes_atitudinal"], dados["intervencoes_atitudinal"])}
    blocos = [(titulo, coluna, [campos[p.pk] for p in ps], chave, textos[chave]) for titulo, coluna, ps, chave in secoes]
    return render(request, "core/acompanhamento_form.html", {
        "e": estagio, "ac": ac, "dados": dados, "blocos": blocos, "erros": bool(respostas.errors or dados.errors),
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
    cabecalho = [("Ano", str(ac.data.year)), ("Escola", cfg.nome_escola or "—"), ("Curso", e.curso.nome.upper()),
                 ("Turma", (e.turma.nome or e.turma.curso.nome) if e.turma else "—"),
                 ("Aluno", e.estagiario.nome_completo.upper()), ("Concedente", (e.local.nome if e.local else "—").upper())]
    if e.setor:
        cabecalho.append(("Setor", e.setor.upper()))
    cabecalho += [("Data da Visita", f"{ac.data:%d/%m/%Y}"), ("Orientador", e.orientador.nome_completo.upper())]
    textos = {"pratica": (ac.observacoes, ac.intervencoes), "atitudinal": (ac.observacoes_atitudinal,
                                                                          ac.intervencoes_atitudinal)}
    secoes = []
    for titulo, coluna, ps, chave in _secoes(e):
        lin = linhas(ac, ps)
        if chave == "pratica":  # no SICE só entram as atividades incluídas com “Atividade Sugerida”
            lin = [(p, r) for p, r in lin if r]
        secoes.append({"titulo": titulo, "coluna": coluna, "linhas": lin, "chave": chave, "obs": textos[chave][0],
                       "interv": textos[chave][1]})
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
            messages.success(request, f"Marcado como lançado no {sistema_oficial()}.")
        return redirect(ac.estagio.get_absolute_url() + "?aba=agenda")
    return render(request, "core/acompanhamento_sice.html", _contexto(ac))


@login_required
def acompanhamento_ver(request, pk):
    """Leitura, como o relatório do SICE (o estagiário também vê o que o orientador registrou)."""
    return render(request, "core/acompanhamento_ver.html", _contexto(_pegar(request, pk)))
