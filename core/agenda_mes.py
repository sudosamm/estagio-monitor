"""Calendário do mês na página inicial do orientador: visitas, feriados, termos, previsões e dias sem registro."""
import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from .models import Agendamento, DiaSemEstagio, chave_municipio
from .services import DIAS_EXTENSO, resumo_horas, status_periodo

# tipo -> (rótulo da legenda, ordem no dia)
TIPOS = {
    "visita": ("Visita", 1),
    "conversa": ("Conversa ou reunião", 2),
    "solicitado": ("Solicitação com data", 3),
    "termo": ("Fim do termo", 4),
    "previsao": ("Previsão de conclusão", 5),
    "inicio": ("Início de estágio", 6),
    "aniversario": ("Aniversário", 7),
}


@dataclass
class DiaAgenda:
    data: date
    do_mes: bool
    hoje: bool
    feriados: list = field(default_factory=list)
    eventos: list = field(default_factory=list)  # {tipo, texto, hora, url}
    sem_registro: int = 0

    @property
    def iso(self):
        return self.data.isoformat()

    @property
    def tipos(self):
        return sorted({e["tipo"] for e in self.eventos}, key=lambda t: TIPOS[t][1])


def _feriados_do_mes(usuario, estagios, inicio, fim):
    """Dias sem estágio que valem para pelo menos um estagiário da pessoa (ou que ela cadastrou)."""
    A = DiaSemEstagio.Abrangencia
    chaves = {chave_municipio(e.local.cidade) for e in estagios if e.local_id and e.local.cidade} - {""}
    locais = {e.local_id for e in estagios if e.local_id}
    filtro = Q(abrangencia=A.TODOS) | Q(abrangencia=A.MUNICIPIO, municipio_chave__in=chaves) \
        | Q(abrangencia=A.CONCEDENTE, concedente_id__in=locais)
    filtro |= Q(abrangencia=A.ESCOLA) if usuario.is_superuser else Q(abrangencia=A.ESCOLA, orientador=usuario)
    qs = DiaSemEstagio.objects.filter(filtro).filter(Q(anual=False, data__range=(inicio, fim)) | Q(anual=True))
    dias = {}
    for d in qs.select_related("concedente"):
        rotulo = d.descricao + (f" ({d.concedente})" if d.abrangencia == A.CONCEDENTE and d.concedente_id else "")
        for dia in d.ocorrencias(inicio, fim):
            if rotulo not in dias.setdefault(dia, []):
                dias[dia].append(rotulo)
    return dias


def agenda_do_mes(usuario, estagios, ano, mes, hoje=None):
    """Semanas (segunda a domingo) com um DiaAgenda por dia. `estagios` já passou por preparar_lote()
    com `desde` <= primeiro dia do mês (ou hoje, o que for menor)."""
    hoje = hoje or timezone.localdate()
    primeiro = date(ano, mes, 1)
    ultimo = date(ano, mes, calendar.monthrange(ano, mes)[1])
    inicio = primeiro - timedelta(days=primeiro.weekday())
    fim = ultimo + timedelta(days=6 - ultimo.weekday())
    dias = {}
    d = inicio
    while d <= fim:
        dias[d] = DiaAgenda(d, d.month == mes, d == hoje)
        d += timedelta(days=1)

    def evento(dia, tipo, texto, url="", hora=""):
        if dia in dias:
            dias[dia].eventos.append({"tipo": tipo, "texto": texto, "url": url, "hora": hora})

    for dia, nomes in _feriados_do_mes(usuario, estagios, inicio, fim).items():
        dias[dia].feriados = nomes

    ags = Agendamento.objects.filter(data_hora__date__range=(inicio, fim)).exclude(status=Agendamento.Status.CANCELADO)
    if not usuario.is_superuser:
        ags = ags.filter(Q(orientador=usuario) | Q(estagios__in=estagios)).distinct()
    for a in ags.prefetch_related("estagios__estagiario").select_related("local"):
        quando = timezone.localtime(a.data_hora)
        nomes = ", ".join(e.estagiario.primeiro_nome for e in a.estagios.all())
        tipo = ("solicitado" if a.status == Agendamento.Status.SOLICITADO
                else "visita" if a.tipo == Agendamento.Tipo.VISITA else "conversa")
        texto = a.assunto + (f" · {nomes}" if nomes else "") + (" (realizada)" if a.status == Agendamento.Status.REALIZADO else "")
        evento(quando.date(), tipo, texto, a.get_absolute_url(), quando.strftime("%H:%M"))

    ontem = min(hoje - timedelta(days=1), fim)
    for e in estagios:
        url = e.get_absolute_url()
        nome = e.estagiario.nome_completo
        if e.data_fim and inicio <= e.data_fim <= fim:
            evento(e.data_fim, "termo", f"Termina o termo de {nome}", url)
        if inicio <= e.data_inicio <= fim:
            evento(e.data_inicio, "inicio", f"{nome} começa o estágio", url)
        nasc = e.estagiario.data_nascimento
        if nasc:
            for ano_ in {inicio.year, fim.year}:
                try:
                    niver = nasc.replace(year=ano_)
                except ValueError:  # 29/02
                    niver = date(ano_, 3, 1)
                if inicio <= niver <= fim:
                    evento(niver, "aniversario", f"Aniversário de {nome} ({ano_ - nasc.year} anos)", url)
        r = resumo_horas(e)
        if r["previsao_termino"] and inicio <= r["previsao_termino"] <= fim:
            evento(r["previsao_termino"], "previsao", f"{nome} deve concluir as {int(r['total'])} h", url)
        de = max(inicio, e.data_inicio, e.acompanhamento_desde or e.data_inicio)
        if de <= ontem:
            for s in status_periodo(e, de, ontem, hoje=hoje, limite=r["previsao_termino"]):
                if s.codigo == "sem_registro":
                    dias[s.data].sem_registro += 1

    for dia in dias.values():
        dia.eventos.sort(key=lambda ev: (ev["hora"] or "99", TIPOS[ev["tipo"]][1], ev["texto"]))
    lista = list(dias.values())
    return [lista[i:i + 7] for i in range(0, len(lista), 7)]


def grade_limites(ano, mes):
    """Primeiro e último dia da grade (segunda antes do dia 1 até o domingo depois do fim do mês)."""
    primeiro = date(ano, mes, 1)
    ultimo = date(ano, mes, calendar.monthrange(ano, mes)[1])
    return primeiro - timedelta(days=primeiro.weekday()), ultimo + timedelta(days=6 - ultimo.weekday())


def dados_json(semanas):
    """O que o painel lateral mostra ao clicar num dia (sem recarregar a página)."""
    novo = reverse("novo_agendamento")
    return {d.iso: {"feriados": d.feriados, "eventos": d.eventos, "sem_registro": d.sem_registro,
                    "agendar": f"{novo}?data={d.iso}",
                    "titulo": f"{DIAS_EXTENSO[d.data.weekday()]}, {d.data:%d/%m}" + (" · hoje" if d.hoje else "")}
            for semana in semanas for d in semana}
