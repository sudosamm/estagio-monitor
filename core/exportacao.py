"""Exportação da situação dos estagiários para planilha (.xlsx)."""
import io
from datetime import date

from django.db.models import F, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .models import Agendamento, Registro

VERDE = "005A2B"
CAB = Font(bold=True, color="FFFFFF")
CAB_FUNDO = PatternFill("solid", fgColor=VERDE)
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def _num(valor):
    return float(valor) if valor is not None else None


def _aba(ws, colunas, linhas, larguras=None):
    ws.append(colunas)
    for c in ws[1]:
        c.font, c.fill = CAB, CAB_FUNDO
        c.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 30
    for linha in linhas:
        ws.append(linha)
    ws.freeze_panes = "B2"
    if linhas:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(colunas))}{len(linhas) + 1}"
    for i, titulo in enumerate(colunas, 1):
        largura = (larguras or {}).get(titulo)
        if largura is None:
            maior = max([len(str(titulo))] + [len(str(l[i - 1])) for l in linhas if l[i - 1] is not None][:300])
            largura = min(max(maior + 2, 8), 45)
        ws.column_dimensions[get_column_letter(i)].width = largura
    for row in ws.iter_rows(min_row=2):
        for c in row:
            if isinstance(c.value, date):
                c.number_format = "DD/MM/YYYY HH:MM" if hasattr(c.value, "hour") else "DD/MM/YYYY"
            elif isinstance(c.value, float):
                c.number_format = "0.0"


def gerar_planilha(linhas, tot, descricao, emitido_por, agora):
    """linhas/tot: saída de acompanhamento.consolidar()."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Estagiários"
    colunas = ["Estagiário", "Matrícula", "Usuário", "Curso", "Turma", "Concedente", "Município", "Setor", "Supervisor",
               "Orientador", "Início", "Fim do termo", "Carga (h)", "Cumpridas (h)", "A validar (h)", "Faltam (h)",
               "% cumprido", "Presenças", "Ausências justificadas", "Faltas", "Dias sem registro", "Visitas realizadas",
               "Previsão de término", "Situação", "Documentos atrasados", "Último feedback (média)", "Pontos de atenção"]
    dados = []
    for l in linhas:
        e, r = l["e"], l["r"]
        dados.append([
            e.estagiario.nome_completo, e.estagiario.matricula, e.estagiario.username, e.curso.nome,
            (e.turma.nome or e.turma.curso.nome) if e.turma else "", e.local.nome if e.local else "",
            e.local.cidade if e.local else "", e.setor, e.supervisor.nome_completo if e.supervisor else "",
            e.orientador.nome_completo, e.data_inicio, e.data_fim, _num(r["total"]), _num(r["cumpridas"]),
            _num(r["pendentes"]), _num(r["faltam"]), _num(r["pct"]), r["presencas"], r["ausencias"], r["faltas"],
            l["sem_registro"], e.n_visitas, r["previsao_termino"] if e.ativo else None, l["situacao"],
            ", ".join(l["docs_atrasados"]), (float(l["feedback"].media) if l["feedback"] and l["feedback"].media else None),
            "; ".join(l["motivos"]),
        ])
    _aba(ws, colunas, dados, {"Pontos de atenção": 60, "Estagiário": 32})

    # horas validadas por mês
    estagios = [l["e"] for l in linhas]
    por_mes = (Registro.objects.filter(estagio__in=estagios, situacao=Registro.Situacao.PRESENTE,
                                       confirmacao=Registro.Confirmacao.CONFIRMADA)
               .annotate(mes=TruncMonth("data")).values("estagio", "mes").annotate(h=Sum("horas")))
    tabela, meses = {}, set()
    for item in por_mes:
        mes = item["mes"]
        mes = mes.date() if hasattr(mes, "date") else mes
        meses.add(mes)
        tabela[(item["estagio"], mes)] = item["h"]
    meses = sorted(meses)
    ws2 = wb.create_sheet("Horas por mês")
    cab = ["Estagiário", "Horas anteriores"] + [f"{MESES[m.month - 1]}/{m.year}" for m in meses] + ["Total cumprido"]
    dados2 = []
    for l in linhas:
        e = l["e"]
        valores = [_num(tabela.get((e.pk, m))) for m in meses]
        dados2.append([e.estagiario.nome_completo, _num(e.horas_anteriores) or None] + valores
                      + [_num(l["r"]["cumpridas"])])
    _aba(ws2, cab, dados2, {"Estagiário": 32})

    # visitas e conversas
    ws3 = wb.create_sheet("Visitas e conversas")
    agendamentos = (Agendamento.objects.filter(estagios__in=estagios).distinct()
                    .select_related("local", "orientador").prefetch_related("estagios__estagiario")
                    .order_by(F("data_hora").asc(nulls_first=True), "criado_em"))
    dados3 = []
    for a in agendamentos:
        quando = timezone.localtime(a.data_hora).replace(tzinfo=None) if a.data_hora else None
        dados3.append([
            quando, a.get_tipo_display(), a.get_modalidade_display(), a.get_status_display(), a.assunto,
            ", ".join(e.estagiario.nome_completo for e in a.estagios.all() if e in estagios),
            a.local.nome if a.local else "", a.orientador.nome_completo, a.relato,
        ])
    _aba(ws3, ["Data e hora", "Tipo", "Modalidade", "Situação", "Assunto", "Estagiários", "Concedente", "Orientador",
               "Relato / ata"], dados3, {"Relato / ata": 60, "Estagiários": 40, "Data e hora": 17})

    # resumo
    ws4 = wb.create_sheet("Resumo", 0)
    ws4["A1"] = "Situação dos estagiários"
    ws4["A1"].font = Font(bold=True, size=14, color=VERDE)
    ws4["A2"] = descricao
    ws4["A3"] = f"Emitido em {agora:%d/%m/%Y %H:%M} por {emitido_por}"
    ws4["A3"].font = Font(italic=True, color="666666")
    itens = [("Estagiários na planilha", len(linhas)), ("Ativos", tot["ativos"]),
             ("Carga cumprida, em média (%)", tot["pct_medio"]), ("Já cumpriram a carga", tot["concluidos"]),
             ("Terminam depois do termo", tot["atrasados"]), ("Faltas registradas", tot["faltas"]),
             ("Dias sem registro", tot["sem_registro"]), ("Presenças a validar", tot["pendentes"]),
             ("Visitas e conversas realizadas", tot["visitas"])]
    for i, (rotulo, valor) in enumerate(itens, 5):
        ws4.cell(i, 1, rotulo)
        ws4.cell(i, 2, valor).font = Font(bold=True)
    ws4.cell(len(itens) + 6, 1, "Horas cumpridas = presenças validadas pelo supervisor + horas anteriores ao sistema. "
                                "As abas seguintes têm o detalhe por estagiário, as horas por mês e as visitas.").font = \
        Font(italic=True, color="666666")
    ws4.column_dimensions["A"].width = 34
    ws4.column_dimensions["B"].width = 12

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
