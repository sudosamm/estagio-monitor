"""Avaliações que o estagiário preenche (autoavaliação e avaliação do orientador) e o texto para copiar no SICE."""
from django import forms

from .models import Feedback, PerguntaAvaliacao

ESCALA = [(str(v), f"{v} — {r}") for v, r in reversed(Feedback.NOTAS)]  # 1 — Insuficiente … 5 — Excelente
TEXTO_NOTA = dict(ESCALA)


def perguntas(tipo):
    return list(PerguntaAvaliacao.objects.filter(avaliacao=tipo, ativa=True))


class RespostasForm(forms.Form):
    """Uma pergunta por campo. Nada é obrigatório para salvar o rascunho; ao concluir, as obrigatórias são cobradas."""

    def __init__(self, *a, perguntas=(), **kw):
        super().__init__(*a, **kw)
        self.perguntas = perguntas
        for p in perguntas:
            nome = f"p{p.pk}"
            if p.resposta == PerguntaAvaliacao.Resposta.NOTA:
                campo = forms.ChoiceField(choices=ESCALA, widget=forms.RadioSelect, required=False)
            elif p.resposta == PerguntaAvaliacao.Resposta.ESCOLHA:
                campo = forms.ChoiceField(choices=[(o, o) for o in p.lista_opcoes], widget=forms.RadioSelect,
                                          required=False)
            else:
                attrs = {"rows": 4}
                if p.limite:
                    attrs["maxlength"] = p.limite
                campo = forms.CharField(widget=forms.Textarea(attrs=attrs), required=False, max_length=p.limite or None)
            campo.label = p.enunciado
            campo.help_text = p.ajuda
            campo.pergunta = p
            self.fields[nome] = campo

    def respostas(self):
        return {str(p.pk): (self.cleaned_data.get(f"p{p.pk}") or "").strip() for p in self.perguntas}

    def conferir_obrigatorias(self):
        faltam = 0
        for p in self.perguntas:
            if p.obrigatoria and not (self.cleaned_data.get(f"p{p.pk}") or "").strip():
                self.add_error(f"p{p.pk}", "Responda esta pergunta para concluir.")
                faltam += 1
        return faltam == 0


def linhas(avaliacao, lista=None):
    """[(pergunta, texto da resposta)] na ordem do SICE."""
    lista = lista if lista is not None else perguntas(avaliacao.tipo)
    resultado = []
    for p in lista:
        valor = avaliacao.respostas.get(str(p.pk), "") if avaliacao else ""
        if p.resposta == PerguntaAvaliacao.Resposta.NOTA and valor:
            valor = TEXTO_NOTA.get(valor, valor)
        resultado.append((p, valor))
    return resultado


def pode_ler(usuario, avaliacao):
    """Autoavaliação: a escola do estágio. Avaliação do orientador: coordenação/administração (e o orientador, se
    a configuração permitir). O próprio estagiário sempre."""
    from .models import Configuracao
    from .views.base import eh_orientador_do

    e = avaliacao.estagio
    if usuario.pk == e.estagiario_id:
        return True
    if avaliacao.tipo == PerguntaAvaliacao.Tipo.AUTO:
        return eh_orientador_do(usuario, e)
    if usuario.is_superuser or usuario.coordena(e.curso_id):
        return True
    return e.orientador_id == usuario.pk and Configuracao.atual().orientador_le_avaliacao
