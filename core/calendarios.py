"""Importação de calendários de feriados e do calendário letivo (CSV ou ICS).

- CSV: uma linha por feriado/evento. Colunas: data, descricao (obrigatórias), ate, tipo, municipio, uf, anual, curso.
- ICS (iCalendar): o formato exportado pelo Google Agenda, Outlook e por muitas prefeituras. Eventos de dia
  inteiro viram dias sem estágio; eventos de vários dias viram um período; RRULE anual vira “todo ano”.

A leitura não grava nada: devolve os itens para a prévia. A gravação usa services.cadastrar_dias.
"""
import csv
import io
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

from .models import Curso, DiaSemEstagio, chave_municipio

A = DiaSemEstagio.Abrangencia
COLUNAS = [
    ("data", True, "dd/mm/aaaa. Só dd/mm = repete todo ano"),
    ("descricao", True, "Nome do feriado ou evento"),
    ("ate", False, "Último dia, para períodos (recesso, férias)"),
    ("tipo", False, "municipal, nacional, estadual ou escola. Vazio = o escolhido na tela"),
    ("municipio", False, "Para feriado municipal. Vazio = o escolhido na tela"),
    ("uf", False, "Ex.: CE"),
    ("anual", False, "sim = repete todo ano nesta data"),
    ("curso", False, "Só para eventos da escola de um curso"),
]
SINONIMOS = {"nome": "descricao", "feriado": "descricao", "evento": "descricao", "descrição": "descricao",
             "data_inicio": "data", "inicio": "data", "data_fim": "ate", "fim": "ate", "cidade": "municipio",
             "município": "municipio", "abrangencia": "tipo"}
TIPOS = {"municipal": A.MUNICIPIO, "municipio": A.MUNICIPIO, "nacional": A.TODOS, "estadual": A.TODOS,
         "todos": A.TODOS, "escola": A.ESCOLA, "evento": A.ESCOLA, "recesso": A.ESCOLA, "letivo": A.ESCOLA,
         "ferias": A.ESCOLA}
# o Google Agenda marca datas comemorativas que não são feriado (Dia das Mães, Dia dos Namorados…)
NAO_FERIADO = ("observância", "observance", "observancia")
LIMITE_ITENS = 1000
LIMITE_PERIODO = 120  # dias


class ErroCalendario(Exception):
    pass


@dataclass
class Item:
    origem: str          # “linha 3” ou “evento 5”
    data: date
    descricao: str
    abrangencia: str
    ate: date = None
    municipio: str = ""
    anual: bool = False
    curso_id: int = None
    curso_nome: str = ""
    marcado: bool = True
    observacao: str = ""

    @property
    def dias(self):
        return (self.ate - self.data).days + 1 if self.ate else 1

    def para_sessao(self):
        d = asdict(self)
        d["data"] = self.data.isoformat()
        d["ate"] = self.ate.isoformat() if self.ate else None
        return d

    @classmethod
    def da_sessao(cls, d):
        d = dict(d)
        d["data"] = date.fromisoformat(d["data"])
        d["ate"] = date.fromisoformat(d["ate"]) if d["ate"] else None
        return cls(**d)


@dataclass
class Padrao:
    abrangencia: str
    municipio: str = ""
    ano: int = None  # para “dd/mm” sem ano


def _chave(texto):
    t = unicodedata.normalize("NFKD", texto or "")
    return " ".join("".join(c for c in t if not unicodedata.combining(c)).lower().split())


def _decodificar(conteudo):
    if isinstance(conteudo, bytes):
        for cod in ("utf-8-sig", "cp1252"):
            try:
                return conteudo.decode(cod)
            except UnicodeDecodeError:
                continue
    return conteudo


def ler_calendario(conteudo, nome_arquivo, padrao):
    """Devolve (itens, erros). Erros são (onde, mensagem)."""
    texto = _decodificar(conteudo).lstrip("﻿")
    if "BEGIN:VCALENDAR" in texto[:2000].upper() or nome_arquivo.lower().endswith(".ics"):
        itens, erros = _ler_ics(texto, padrao)
    else:
        itens, erros = _ler_csv(texto, padrao)
    if not itens and not erros:
        raise ErroCalendario("Nenhum feriado ou evento encontrado no arquivo.")
    if len(itens) > LIMITE_ITENS:
        raise ErroCalendario(f"O arquivo tem {len(itens)} itens; o limite é {LIMITE_ITENS}. Divida em partes.")
    return itens, erros


# ------------------------------------------------------------------ CSV


def _data_csv(texto, padrao):
    texto = texto.strip()
    m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})", texto)
    if m:  # dd/mm: data fixa, repete todo ano
        return date(padrao.ano or date.today().year, int(m.group(2)), int(m.group(1))), True
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%Y"):
        try:
            return datetime.strptime(texto, fmt).date(), False
        except ValueError:
            pass
    raise ValueError(f"data inválida “{texto}” (use dd/mm/aaaa ou dd/mm)")


def _ler_csv(texto, padrao):
    primeira = texto.split("\n", 1)[0]
    delim = ";" if primeira.count(";") >= primeira.count(",") else ","
    leitor = csv.DictReader(io.StringIO(texto), delimiter=delim)
    if not leitor.fieldnames:
        raise ErroCalendario("O arquivo está vazio.")
    cab = {}
    for c in leitor.fieldnames:
        if c:
            k = _chave(c).replace(" ", "_")
            cab[c] = SINONIMOS.get(k, k)
    faltando = [c for c, obrig, _ in COLUNAS if obrig and c not in cab.values()]
    if faltando:
        raise ErroCalendario("Colunas obrigatórias ausentes: " + ", ".join(faltando) + ". Baixe o modelo.")
    cursos = {_chave(c.nome): c for c in Curso.objects.all()}
    itens, erros = [], []
    for n, bruta in enumerate(leitor, start=2):
        d = {cab[k]: (v or "").strip() for k, v in bruta.items() if k in cab}
        if not any(d.values()):
            continue
        onde = f"linha {n}"
        try:
            data, anual = _data_csv(d.get("data", ""), padrao)
            ate = _data_csv(d["ate"], padrao)[0] if d.get("ate") else None
            if ate and ate < data:
                raise ValueError("“ate” é antes da data")
            if ate and (ate - data).days >= LIMITE_PERIODO:
                raise ValueError(f"período de mais de {LIMITE_PERIODO} dias")
            if not d.get("descricao"):
                raise ValueError("descrição vazia")
            tipo = _chave(d.get("tipo", "")).replace(" ", "")
            abr = TIPOS.get(tipo) if tipo else padrao.abrangencia
            if not abr:
                raise ValueError(f"tipo “{d['tipo']}” desconhecido (use municipal, nacional, estadual ou escola)")
            municipio = d.get("municipio") or (padrao.municipio if abr == A.MUNICIPIO else "")
            if abr == A.MUNICIPIO and not chave_municipio(municipio):
                raise ValueError("feriado municipal sem município (coluna municipio ou o da tela)")
            anual = anual or _chave(d.get("anual", "")) in ("sim", "s", "x", "1", "true", "anual")
            if anual and ate:
                raise ValueError("um período não pode repetir todo ano")
            curso = None
            if d.get("curso") and abr == A.ESCOLA:
                curso = cursos.get(_chave(d["curso"]))
                if not curso:
                    raise ValueError(f"curso “{d['curso']}” não cadastrado")
        except ValueError as exc:
            erros.append((onde, str(exc)))
            continue
        itens.append(Item(onde, data, d["descricao"], abr, ate, municipio if abr == A.MUNICIPIO else "", anual,
                          curso.pk if curso else None, curso.nome if curso else ""))
    return itens, erros


# ------------------------------------------------------------------ ICS


def _desdobrar(texto):
    """Linhas do iCalendar podem continuar na seguinte começando com espaço (RFC 5545)."""
    linhas = []
    for linha in texto.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if linha[:1] in (" ", "\t") and linhas:
            linhas[-1] += linha[1:]
        else:
            linhas.append(linha)
    return linhas


def _valor_ics(texto):
    return (texto.replace("\\n", " ").replace("\\N", " ").replace("\\,", ",").replace("\\;", ";")
            .replace("\\\\", "\\").strip())


def _data_ics(valor):
    m = re.match(r"(\d{4})(\d{2})(\d{2})", valor.strip())
    if not m:
        raise ValueError(f"data inválida “{valor}”")
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _ler_ics(texto, padrao):
    itens, erros, evento, n = [], [], None, 0
    for linha in _desdobrar(texto):
        if linha.upper() == "BEGIN:VEVENT":
            evento, n = {}, n + 1
            continue
        if linha.upper() == "END:VEVENT" and evento is not None:
            onde = f"evento {n}"
            try:
                itens.append(_item_ics(evento, padrao, onde))
            except ValueError as exc:
                erros.append((onde, str(exc)))
            evento = None
            continue
        if evento is None or ":" not in linha:
            continue
        nome, valor = linha.split(":", 1)
        chave, *params = nome.split(";")
        evento[chave.upper()] = (valor, [p.upper() for p in params])
    return itens, erros


def _item_ics(ev, padrao, onde):
    if "DTSTART" not in ev:
        raise ValueError("evento sem data")
    if ev.get("STATUS", ("",))[0].strip().upper() == "CANCELLED":
        raise ValueError("evento cancelado")
    inicio = _data_ics(ev["DTSTART"][0])
    dia_inteiro = "VALUE=DATE" in ev["DTSTART"][1] or len(ev["DTSTART"][0].strip()) == 8
    ate = None
    if "DTEND" in ev:
        fim = _data_ics(ev["DTEND"][0])
        if dia_inteiro:
            fim -= timedelta(days=1)  # no dia inteiro o DTEND é exclusivo
        if fim > inicio:
            ate = fim
    if ate and (ate - inicio).days >= LIMITE_PERIODO:
        raise ValueError(f"período de mais de {LIMITE_PERIODO} dias")
    descricao = _valor_ics(ev.get("SUMMARY", ("",))[0])
    if not descricao:
        raise ValueError("evento sem título")
    regra = ev.get("RRULE", ("",))[0].upper()
    anual = "FREQ=YEARLY" in regra and not ate
    detalhe = _chave(_valor_ics(ev.get("DESCRIPTION", ("",))[0]))
    nao_feriado = any(p in detalhe for p in NAO_FERIADO)
    municipio = padrao.municipio if padrao.abrangencia == A.MUNICIPIO else ""
    if padrao.abrangencia == A.MUNICIPIO and not chave_municipio(municipio):
        raise ValueError("informe na tela o município deste calendário")
    return Item(onde, inicio, descricao[:120], padrao.abrangencia, ate, municipio, anual,
                marcado=not nao_feriado, observacao="data comemorativa, não é feriado" if nao_feriado else
                ("" if dia_inteiro else "evento com horário: conta o dia todo"))


def modelo_csv():
    saida = io.StringIO()
    saida.write("﻿")
    w = csv.writer(saida, delimiter=";")
    w.writerow([c for c, _, _ in COLUNAS])
    w.writerow(["23/11", "Aniversário da cidade (exemplo)", "", "municipal", "Cidade Exemplo", "CE", "sim", ""])
    w.writerow(["02/02/2027", "Recesso escolar (exemplo)", "06/02/2027", "escola", "", "", "", ""])
    w.writerow(["15/03/2027", "Evento do curso (exemplo)", "", "escola", "", "", "", "Técnico em Informática"])
    return saida.getvalue()
