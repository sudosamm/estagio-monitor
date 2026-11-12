"""Indicadores do andamento dos estagiários: por turma, por concedente e semana a semana."""
from collections import Counter
from datetime import timedelta

from django.utils import timezone

from .acompanhamento import com_contagens, consolidar
from .models import Documento, Justificativa, Registro
from .services import estagios_visiveis, filtrar_ano, status_periodo

PREVISTOS = {"confirmado", "aguardando", "contestado", "ausencia", "ausencia_ok", "falta", "sem_registro"}
PRESENTES = {"confirmado", "aguardando"}
AVISADAS = {"ausencia", "ausencia_ok"}  # ausência avisada ou justificada (atestado aceito)
SITUACOES = ["Carga cumprida", "Em andamento", "Termina após o termo", "Encerrado"]


def _pct(parte, todo):
    return round(parte * 100 / todo, 1) if todo else None


def _grupo():
    return {"ativos": 0, "pct_soma": 0, "concluidos": 0, "previstos": 0, "presentes": 0, "faltas": 0,
            "visitados": 0, "docs_ok": 0, "docs_total": 0, "atencao": 0, "a_validar": 0, "fb_soma": 0, "fb_n": 0,
            "fb_mes": 0}


def _fechar(g):
    g["carga"] = round(g["pct_soma"] / g["ativos"], 1) if g["ativos"] else None
    g["frequencia"] = _pct(g["presentes"], g["previstos"])
    g["com_visita"] = _pct(g["visitados"], g["ativos"])
    g["documentos"] = _pct(g["docs_ok"], g["docs_total"])
    g["feedback"] = round(g["fb_soma"] / g["fb_n"], 1) if g["fb_n"] else None
    g["feedback_mes"] = _pct(g["fb_mes"], g["ativos"])
    return g


def calcular(usuario, ano, curso=None, semanas=8, hoje=None):
    hoje = hoje or timezone.localdate()
    ontem = hoje - timedelta(days=1)
    qs = filtrar_ano(estagios_visiveis(usuario), ano)
    if curso:
        qs = qs.filter(curso=curso)
    estagios = list(com_contagens(qs.select_related("turma__curso", "local").prefetch_related("escalas"))
                    .order_by("estagiario__nome_completo"))
    linhas, atencao, tot = consolidar(estagios, hoje)
    atencao_ids = {e.pk for e, _ in atencao}

    # semana a semana (segunda a domingo), só dias de estágio já passados
    primeira = hoje - timedelta(days=hoje.weekday()) - timedelta(weeks=semanas - 1)
    serie = {primeira + timedelta(weeks=i): Counter() for i in range(semanas)}
    freq = {}
    for e in estagios:
        if not e.ativo:
            continue
        inicio = max(primeira, e.data_inicio, e.acompanhamento_desde or e.data_inicio)
        c = Counter()
        if inicio <= ontem:
            for s in status_periodo(e, inicio, ontem, hoje=hoje):
                if s.codigo not in PREVISTOS:
                    continue
                semana = serie[s.data - timedelta(days=s.data.weekday())]
                tipo = ("presentes" if s.codigo in PRESENTES else "avisadas" if s.codigo in AVISADAS else "faltas")
                for alvo in (c, semana):
                    alvo["previstos"] += 1
                    alvo[tipo] += 1
        freq[e.pk] = c

    mes_atual = hoje.replace(day=1)
    por_turma, por_concedente = {}, {}
    situacoes = Counter()
    geral = _grupo()
    for l in linhas:
        e, r = l["e"], l["r"]
        situacoes[l["situacao"]] += 1
        if not e.ativo:
            continue
        c = freq.get(e.pk, Counter())
        obrig = [i for i in l["pasta"] if i.tipo.obrigatorio]
        chave_t = (e.turma.curso.nome, e.turma.nome or "", e.turma.ano_ingresso) if e.turma else (e.curso.nome, "sem turma", 0)
        rotulo_t = (f"{e.turma.nome or e.turma.curso.nome} · {e.turma.curso.nome}" if e.turma
                    else f"{e.curso.nome} · sem turma")
        chave_c = e.local.nome if e.local else "— sem concedente —"
        grupos = [geral, por_turma.setdefault(chave_t, {"rotulo": rotulo_t, "turma": e.turma, **_grupo()}),
                  por_concedente.setdefault(chave_c, {"rotulo": chave_c, "local": e.local, **_grupo()})]
        for g in grupos:
            g["ativos"] += 1
            g["pct_soma"] += r["pct"]
            g["concluidos"] += l["concluido"]
            g["previstos"] += c["previstos"]
            g["presentes"] += c["presentes"]
            g["faltas"] += r["faltas"]
            g["visitados"] += e.n_visitas > 0
            g["docs_ok"] += sum(1 for i in obrig if i.codigo == "conferido")
            g["docs_total"] += len(obrig)
            g["atencao"] += e.pk in atencao_ids
            g["a_validar"] += e.n_pendentes
            fb = l["feedback"]
            if fb and fb.media:
                g["fb_soma"] += fb.media
                g["fb_n"] += 1
            g["fb_mes"] += bool(fb and fb.mes == mes_atual)
    turmas = [_fechar(g) for _, g in sorted(por_turma.items())]
    concedentes = sorted((_fechar(g) for g in por_concedente.values()),
                         key=lambda g: (g["frequencia"] is None, g["frequencia"] or 0, g["rotulo"]))
    _fechar(geral)

    ativos_ids = [e.pk for e in estagios if e.ativo]
    pendencias = {
        "atestados": Justificativa.objects.filter(estagio_id__in=ativos_ids, status=Justificativa.Status.PENDENTE).count(),
        "documentos": Documento.objects.filter(estagio_id__in=ativos_ids, situacao=Documento.Situacao.ENVIADO).count(),
        "presencas": Registro.objects.filter(estagio_id__in=ativos_ids, confirmacao=Registro.Confirmacao.PENDENTE,
                                             situacao=Registro.Situacao.PRESENTE,
                                             data__lt=hoje - timedelta(days=2)).count(),
    }
    tendencia = []
    for inicio, c in serie.items():
        tendencia.append({
            "semana": inicio.isoformat(), "rotulo": f"{inicio:%d/%m}",
            "taxa": _pct(c["presentes"], c["previstos"]), "previstos": c["previstos"], "presentes": c["presentes"],
            "avisadas": c["avisadas"], "faltas": c["faltas"],
        })
    total = sum(situacoes.values())
    return {
        "geral": geral, "turmas": turmas, "concedentes": concedentes, "tendencia": tendencia,
        "situacoes": [{"rotulo": s, "n": situacoes[s], "pct": _pct(situacoes[s], total)} for s in SITUACOES if situacoes[s]],
        "total": total, "pendencias": pendencias, "semanas": semanas, "inicio": primeira, "ontem": ontem,
    }
