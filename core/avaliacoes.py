"""Avaliações mensais que o estagiário preenche (autoavaliação e avaliação do orientador), como no SICE, e o texto
pronto para copiar lá."""
from datetime import date

from django import forms
from django.utils import timezone

from .models import Feedback, PerguntaAvaliacao

ESCALA = [(str(v), f"{v} — {r}") for v, r in reversed(Feedback.NOTAS)]  # 1 — Insuficiente … 5 — Excelente
TEXTO_NOTA = dict(ESCALA)


SIGLAS_MES = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]
NOMES_MES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
             "novembro", "dezembro"]


def mes_de(d):
    return date(d.year, d.month, 1)


def proximo_mes(m):
    return date(m.year + (m.month == 12), m.month % 12 + 1, 1)


def nome_mes(m):
    return f"{NOMES_MES[m.month - 1]} de {m.year}"


def meses_do_estagio(estagio, hoje=None):
    """Meses que o SICE cobra (do início do estágio até o mês atual, ou até o último registro se já encerrou),
    do mais recente para o mais antigo."""
    from .models import Configuracao

    hoje = hoje or timezone.localdate()
    inicio = mes_de(max(estagio.data_inicio, estagio.acompanhamento_desde or estagio.data_inicio))
    cfg = Configuracao.atual()
    if cfg.avaliacoes_prazo:
        inicio = max(inicio, mes_de(cfg.avaliacoes_prazo))
    fim = mes_de(hoje)
    if not estagio.ativo:
        ultimo = estagio.registros.order_by("-data").values_list("data", flat=True).first()
        fim = min(fim, mes_de(ultimo or estagio.data_fim or estagio.data_inicio))
    meses, m = [], inicio
    while m <= fim:
        meses.append(m)
        m = proximo_mes(m)
    return list(reversed(meses))


def quadro(estagio, hoje=None):
    """[(mês, {tipo: avaliação ou None})] e quantos meses ainda têm alguma avaliação por concluir."""
    from .models import PerguntaAvaliacao

    meses = meses_do_estagio(estagio, hoje)
    feitas = {(a.mes, a.tipo): a for a in estagio.avaliacoes.all()}
    linhas_, faltam = [], 0
    for m in meses:
        tipos = {t: feitas.get((m, t)) for t in PerguntaAvaliacao.Tipo.values}
        if any(not (a and a.concluida_em) for a in tipos.values()):
            faltam += 1
        linhas_.append((m, tipos))
    return linhas_, faltam


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


def disparar_lembrete(agora=None):
    """A partir do dia 20, uma vez por mês: lembra quem ainda não concluiu as avaliações do mês (como o SICE cobra)."""
    from datetime import datetime

    from django.db.models import Q
    from django.urls import reverse

    from .models import Configuracao, Estagio
    from .services import notificar

    agora = timezone.localtime(agora)
    cfg = Configuracao.atual()
    if not cfg.avaliacoes_abertas or agora.day < 20:
        return 0
    mes = mes_de(agora.date())
    marco = timezone.make_aware(datetime(mes.year, mes.month, 20))
    reservado = Configuracao.objects.filter(pk=1).filter(
        Q(lembrete_avaliacoes_em__isnull=True) | Q(lembrete_avaliacoes_em__lt=marco)).update(lembrete_avaliacoes_em=agora)
    if not reservado:
        return 0
    from .views.avaliacoes import estagiarios_pendentes

    estagios = list(Estagio.objects.filter(ativo=True).select_related("estagiario"))
    pendentes = [u for u in estagiarios_pendentes(estagios, mes) if u.is_active]
    notificar(pendentes, f"Faltam as suas avaliações de {nome_mes(mes)} no SICE (autoavaliação e avaliação do "
                         "orientador). Responda aqui e copie as respostas prontas.", reverse("minhas_avaliacoes"))
    return len(pendentes)
