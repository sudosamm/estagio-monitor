"""Importação em massa por CSV: uma linha por estagiário, com a concedente e o supervisor dele.

Concedentes e supervisores que se repetem em várias linhas são criados uma vez só e reaproveitados.
A mesma função faz a prévia (desfazendo tudo no fim) e a importação de verdade, então a prévia mostra
exatamente o que vai acontecer.
"""
import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import transaction

from .models import CAMPOS_CONCEDENTE, Curso, Escala, Estagio, LocalEstagio, Usuario, horas_dos_horarios
from .services import criar_usuario, normalizar_nome, turma_para
from .validators import cnpj_valido, cpf_valido, formatar_cnpj, formatar_cpf, so_digitos

# (coluna, obrigatória, descrição) — a ordem é a do modelo para download
COLUNAS = [
    ("estagiario_nome", True, "Nome completo do estagiário"),
    ("estagiario_cpf", False, "CPF (evita cadastrar a mesma pessoa duas vezes)"),
    ("estagiario_telefone", False, ""),
    ("estagiario_email", False, ""),
    ("matricula", False, ""),
    ("curso", True, "Nome do curso (é criado se não existir)"),
    ("turma", False, "Nome da turma (ex.: 3º A). Vazio = nome do curso"),
    ("ano_turma", False, "Ano de ingresso da turma (ex.: 2024). Vazio = 2 anos antes do início do estágio"),
    ("data_inicio", True, "Início do estágio (dd/mm/aaaa)"),
    ("data_fim", False, "Término previsto no termo (dd/mm/aaaa)"),
    ("horas_anteriores", False, "Horas já cumpridas antes do sistema"),
    ("dias", False, "Ex.: seg,ter ou seg-sex. Vazio = padrão da tela"),
    ("horas_por_dia", False, "Qualquer carga (ex.: 4, 5, 7). Vazio = pelos horários ou o da tela"),
    ("entrada", False, "HH:MM"),
    ("saida_intervalo", False, "HH:MM"),
    ("volta_intervalo", False, "HH:MM"),
    ("saida", False, "HH:MM"),
    ("concedente_nome", True, "Nome fantasia / unidade (sai na folha)"),
    ("concedente_razao_social", False, ""),
    ("concedente_cnpj", False, "CNPJ (ou CPF de profissional liberal)"),
    ("concedente_tipo_instituicao", False, "PUBLICA ou PRIVADA"),
    ("concedente_endereco", False, ""),
    ("concedente_numero", False, ""),
    ("concedente_bairro", False, ""),
    ("concedente_complemento", False, ""),
    ("concedente_cidade", False, ""),
    ("concedente_uf", False, ""),
    ("concedente_cep", False, ""),
    ("concedente_telefone", False, ""),
    ("representante_nome", False, ""),
    ("representante_email", False, ""),
    ("representante_cpf", False, ""),
    ("representante_documento", False, ""),
    ("supervisor_nome", True, "Nome completo do supervisor (fica vinculado à concedente da linha)"),
    ("supervisor_telefone", False, ""),
    ("supervisor_email", False, ""),
    ("supervisor_cargo", False, ""),
    ("orientador", False, "Usuário do orientador (vazio = o escolhido na tela)"),
]
NOMES_COLUNAS = [c for c, _, _ in COLUNAS]

DIAS = {"seg": 0, "ter": 1, "qua": 2, "qui": 3, "sex": 4, "sab": 5, "sáb": 5, "dom": 6}
MAPA_CONCEDENTE = {  # coluna do CSV -> campo da concedente
    "concedente_nome": "nome", "concedente_razao_social": "razao_social", "concedente_cnpj": "cnpj",
    "concedente_tipo_instituicao": "tipo_instituicao", "concedente_endereco": "endereco",
    "concedente_numero": "numero", "concedente_bairro": "bairro", "concedente_complemento": "complemento",
    "concedente_cidade": "cidade", "concedente_uf": "uf", "concedente_cep": "cep",
    "concedente_telefone": "telefone", "representante_nome": "representante_nome",
    "representante_email": "representante_email", "representante_cpf": "representante_cpf",
    "representante_documento": "representante_documento",
}


class ErroImportacao(Exception):
    pass


def _chave(texto):
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.lower().split())


def _data(texto, coluna):
    texto = (texto or "").strip()
    if not texto:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            pass
    raise ErroImportacao(f"{coluna}: data inválida “{texto}” (use dd/mm/aaaa)")


def _hora(texto, coluna):
    texto = (texto or "").strip().lower().replace("h", ":")
    if not texto:
        return None
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?:?", texto)
    if not m or int(m.group(1)) > 23:
        raise ErroImportacao(f"{coluna}: horário inválido “{texto}” (use HH:MM)")
    return time(int(m.group(1)), int(m.group(2) or 0))


def _decimal(texto, coluna):
    texto = (texto or "").strip().replace(",", ".")
    if not texto:
        return None
    try:
        return Decimal(texto)
    except InvalidOperation as exc:
        raise ErroImportacao(f"{coluna}: número inválido “{texto}”") from exc


def _dias(texto):
    """'seg,ter' · 'seg-sex' · 'segunda a sexta' · 'seg e qua' · '0,1' -> [0, 1, ...]"""
    texto = _chave(texto).replace("-feira", "")
    if not texto:
        return None
    if re.fullmatch(r"[0-6](\s*,\s*[0-6])*", texto):
        return sorted({int(x) for x in texto.split(",")})
    dias = set()
    for parte in re.split(r"\s*(?:[,;/]|\se\s)\s*", texto):
        if not parte:
            continue
        intervalo = re.split(r"\s*(?:-|\sa\s)\s*", parte)
        nomes = [p[:3] for p in intervalo]
        if any(n not in DIAS for n in nomes) or len(nomes) > 2:
            raise ErroImportacao(f"dias: não entendi “{parte}” (use seg, ter, qua, qui, sex, sab, dom)")
        if len(nomes) == 2:
            dias.update(range(DIAS[nomes[0]], DIAS[nomes[1]] + 1))
        else:
            dias.add(DIAS[nomes[0]])
    return sorted(dias)


def ler_csv(conteudo):
    """Lê o CSV (aceita ; ou , e UTF-8 com ou sem BOM; também Latin-1, comum no Excel)."""
    if isinstance(conteudo, bytes):
        for codificacao in ("utf-8-sig", "cp1252"):
            try:
                conteudo = conteudo.decode(codificacao)
                break
            except UnicodeDecodeError:
                continue
    conteudo = conteudo.lstrip("﻿")
    primeira = conteudo.split("\n", 1)[0]
    delim = ";" if primeira.count(";") >= primeira.count(",") else ","
    leitor = csv.DictReader(io.StringIO(conteudo), delimiter=delim)
    if not leitor.fieldnames:
        raise ErroImportacao("O arquivo está vazio.")
    cabecalho = {c: _chave(c).replace(" ", "_") for c in leitor.fieldnames if c}
    faltando = [c for c, obrig, _ in COLUNAS if obrig and c not in cabecalho.values()]
    if faltando:
        raise ErroImportacao("Colunas obrigatórias ausentes: " + ", ".join(faltando)
                             + ". Baixe o modelo para ver os nomes das colunas.")
    linhas = []
    for n, bruta in enumerate(leitor, start=2):
        linha = {cabecalho[k]: (v or "").strip() for k, v in bruta.items() if k in cabecalho}
        if any(linha.values()):
            linhas.append((n, linha))
    if not linhas:
        raise ErroImportacao("Nenhuma linha de dados encontrada.")
    return linhas


@dataclass
class Opcoes:
    orientador: Usuario
    dias: list
    horas_por_dia: Decimal | None = None
    entrada: time = None
    saida_intervalo: time = None
    volta_intervalo: time = None
    saida: time = None
    acompanhamento_desde: date = None
    carga_cursos_novos: int = 300
    completar_concedentes: bool = True


@dataclass
class Resultado:
    linhas_ok: list = field(default_factory=list)          # (n, estagiário, concedente, supervisor)
    ignoradas: list = field(default_factory=list)          # (n, motivo)
    erros: list = field(default_factory=list)              # (n, mensagem)
    estagiarios: list = field(default_factory=list)
    supervisores_novos: list = field(default_factory=list)
    supervisores_existentes: set = field(default_factory=set)
    supervisores_vinculados: list = field(default_factory=list)   # (supervisor, concedente) já existente ligado a outra
    concedentes_novas: list = field(default_factory=list)
    concedentes_existentes: set = field(default_factory=set)
    cursos_novos: list = field(default_factory=list)
    confirmado: bool = False

    @property
    def ok(self):
        return not self.erros


def importar(linhas, opcoes, usuario, confirmar=False, concedentes_extra=(), supervisores_extra=()):
    """Processa as linhas. Sem `confirmar`, desfaz tudo no fim (prévia).

    `concedentes_extra` e `supervisores_extra` (da planilha modelo) são cadastros sem estagiário: cada linha tem as
    colunas concedente_* (e supervisor_*, no caso dos supervisores)."""
    r = Resultado()
    senha_hash = make_password(settings.SENHA_PADRAO)
    concedentes, supervisores, cursos, orientadores = {}, {}, {}, {}
    cpfs_no_arquivo = {}
    with transaction.atomic():
        for n, d in linhas:
            try:
                with transaction.atomic():
                    _linha(n, d, opcoes, usuario, r, senha_hash, concedentes, supervisores, cursos, orientadores,
                           cpfs_no_arquivo)
            except ErroImportacao as exc:
                r.erros.append((n, str(exc)))
        for n, d in concedentes_extra:
            try:
                with transaction.atomic():
                    _concedente(d, opcoes, r, concedentes)
            except ErroImportacao as exc:
                r.erros.append((n, str(exc)))
        for n, d in supervisores_extra:
            try:
                with transaction.atomic():
                    local = _concedente(d, opcoes, r, concedentes)
                    _supervisor(d, local, usuario, r, senha_hash, supervisores)
            except ErroImportacao as exc:
                r.erros.append((n, str(exc)))
        if confirmar and r.ok:
            r.confirmado = True
        else:
            transaction.set_rollback(True)
    return r


def _linha(n, d, op, usuario, r, senha_hash, concedentes, supervisores, cursos, orientadores, cpfs_no_arquivo):
    nome = " ".join(d.get("estagiario_nome", "").split())
    if len(nome.split()) < 2:
        raise ErroImportacao("estagiario_nome: informe nome e sobrenome")
    cpf = d.get("estagiario_cpf", "")
    if cpf:
        if not cpf_valido(cpf):
            raise ErroImportacao(f"estagiario_cpf: CPF inválido “{cpf}”")
        cpf = formatar_cpf(cpf)
        if cpf in cpfs_no_arquivo:
            r.ignoradas.append((n, f"{normalizar_nome(nome)} repetido no arquivo (mesmo CPF da linha {cpfs_no_arquivo[cpf]})"))
            return
        cpfs_no_arquivo[cpf] = n
    inicio = _data(d.get("data_inicio"), "data_inicio")
    if not inicio:
        raise ErroImportacao("data_inicio: obrigatória")
    fim = _data(d.get("data_fim"), "data_fim")
    horas_ant = _decimal(d.get("horas_anteriores"), "horas_anteriores") or Decimal(0)

    # escala (colunas do CSV ou padrão da tela)
    dias = _dias(d.get("dias", "")) or op.dias
    horas = _decimal(d.get("horas_por_dia"), "horas_por_dia")
    tem_horario = any(d.get(c) for c in ("entrada", "saida_intervalo", "volta_intervalo", "saida"))
    if tem_horario:
        turnos = [_hora(d.get(c), c) for c in ("entrada", "saida_intervalo", "volta_intervalo", "saida")]
        horas = horas or horas_dos_horarios(*turnos)
    elif not horas or horas == op.horas_por_dia:
        turnos = [op.entrada, op.saida_intervalo, op.volta_intervalo, op.saida]
    else:
        turnos = [None] * 4
    horas = horas or op.horas_por_dia or horas_dos_horarios(*turnos)
    if not horas:
        raise ErroImportacao("horas_por_dia: informe as horas por dia (ex.: 5 ou 7) ou os horários de entrada e saída, "
                             "na planilha ou na tela de importação")

    # orientador
    login = d.get("orientador", "").strip().lower()
    if login:
        if login not in orientadores:
            orientadores[login] = Usuario.objects.filter(username__iexact=login, papel=Usuario.Papel.ORIENTADOR).first()
        orientador = orientadores[login]
        if not orientador:
            raise ErroImportacao(f"orientador: não existe orientador com o usuário “{login}”")
    else:
        orientador = op.orientador

    # curso
    nome_curso = " ".join(d.get("curso", "").split())
    if not nome_curso:
        raise ErroImportacao("curso: obrigatório")
    ck = _chave(nome_curso)
    if ck not in cursos:
        cursos[ck] = next((c for c in Curso.objects.all() if _chave(c.nome) == ck), None)
        if not cursos[ck]:
            cursos[ck] = Curso.objects.create(nome=nome_curso.upper() if nome_curso.isupper() else nome_curso,
                                              carga_horaria=op.carga_cursos_novos, horas_por_dia_padrao=horas)  # só referência interna
            r.cursos_novos.append(cursos[ck])
    curso = cursos[ck]
    ano_turma = d.get("ano_turma", "").strip()
    if ano_turma and not (ano_turma.isdigit() and 2000 <= int(ano_turma) <= inicio.year):
        raise ErroImportacao(f"ano_turma: ano inválido “{ano_turma}”")
    turma = turma_para(curso, d.get("turma", ""), inicio.year, int(ano_turma) if ano_turma else None)

    local = _concedente(d, op, r, concedentes)
    supervisor = _supervisor(d, local, usuario, r, senha_hash, supervisores)

    # estagiário: reaproveita a conta pelo CPF; não duplica estágio ativo
    existente = None
    if cpf:
        existente = Usuario.objects.filter(cpf=cpf).first()
    if not existente:
        candidatos = [u for u in Usuario.objects.filter(papel=Usuario.Papel.ESTAGIARIO, nome_completo__iexact=nome)]
        existente = candidatos[0] if len(candidatos) == 1 and (not cpf or not candidatos[0].cpf) else None
    if existente and existente.estagios.filter(ativo=True).exists():
        r.ignoradas.append((n, f"{existente} já tem estágio ativo no sistema ({existente.username})"))
        return
    extra = {k: v for k, v in {"cpf": cpf, "telefone": d.get("estagiario_telefone", ""),
                                "email": d.get("estagiario_email", ""), "matricula": d.get("matricula", "")}.items() if v}
    if existente:
        aluno = existente
        for k, v in extra.items():
            if not getattr(aluno, k):
                setattr(aluno, k, v)
        aluno.save()
    else:
        aluno = criar_usuario(nome, Usuario.Papel.ESTAGIARIO, usuario, senha_hash=senha_hash, **extra)
        r.estagiarios.append(aluno)

    estagio = Estagio.objects.create(
        estagiario=aluno, orientador=orientador, supervisor=supervisor, curso=curso, turma=turma,
        local=local, data_inicio=inicio, data_fim=fim, horas_anteriores=horas_ant,
        acompanhamento_desde=op.acompanhamento_desde if op.acompanhamento_desde and op.acompanhamento_desde > inicio else None,
    )
    Escala.objects.create(
        estagio=estagio, vigente_desde=inicio, dias=",".join(map(str, dias)), horas_por_dia=horas, criado_por=usuario,
        horario_entrada=turnos[0], saida_intervalo=turnos[1], volta_intervalo=turnos[2], horario_saida=turnos[3],
    )
    r.linhas_ok.append((n, aluno, local, supervisor))


def _concedente(d, op, r, cache):
    dados = {campo: d.get(col, "").strip() for col, campo in MAPA_CONCEDENTE.items() if d.get(col, "").strip()}
    nome = dados.get("nome", "")
    if not nome:
        raise ErroImportacao("concedente_nome: obrigatório")
    if dados.get("cnpj"):
        dig = so_digitos(dados["cnpj"])
        if len(dig) == 14 and cnpj_valido(dig):
            dados["cnpj"] = formatar_cnpj(dig)
        elif len(dig) == 11 and cpf_valido(dig):
            dados["cnpj"] = formatar_cpf(dig)
        else:
            raise ErroImportacao(f"concedente_cnpj: CNPJ/CPF inválido “{dados['cnpj']}”")
    if dados.get("representante_cpf"):
        dados["representante_cpf"] = formatar_cpf(dados["representante_cpf"]) if cpf_valido(dados["representante_cpf"]) else ""
    if "tipo_instituicao" in dados:
        dados["tipo_instituicao"] = {"publica": "PUBLICA", "privada": "PRIVADA"}.get(_chave(dados["tipo_instituicao"]), "")
    if "uf" in dados:
        dados["uf"] = dados["uf"].upper()[:2]
    if "cep" in dados:
        dig = so_digitos(dados["cep"])
        dados["cep"] = f"{dig[:5]}-{dig[5:]}" if len(dig) == 8 else ""
    # uma concedente por unidade: mesmo CNPJ + mesmo nome
    chave = (so_digitos(dados.get("cnpj", "")), _chave(nome))
    if chave in cache:
        return cache[chave]
    local = None
    for l in LocalEstagio.objects.filter(nome__iexact=nome) if not chave[0] else LocalEstagio.objects.exclude(cnpj=""):
        if _chave(l.nome) == chave[1] and so_digitos(l.cnpj) == chave[0]:
            local = l
            break
    if local is None and not chave[0]:
        local = next((l for l in LocalEstagio.objects.all() if _chave(l.nome) == chave[1]), None)
    if local:
        if not local.ativa:  # concedente desativada que voltou a receber estagiários
            local.ativa = True
            local.save(update_fields=["ativa"])
        if op.completar_concedentes:
            mudou = False
            for campo in CAMPOS_CONCEDENTE:
                if campo in dados and not getattr(local, campo):
                    setattr(local, campo, dados[campo])
                    mudou = True
            if mudou:
                local.save()
        r.concedentes_existentes.add(local)
    else:
        local = LocalEstagio.objects.create(**dados)
        r.concedentes_novas.append(local)
    cache[chave] = local
    return local


def _supervisor(d, local, usuario, r, senha_hash, cache):
    """O supervisor fica sempre vinculado à concedente da linha. A mesma pessoa (mesmo nome) em outra concedente
    é a mesma conta, vinculada às duas — a prévia mostra esses casos para conferência."""
    nome = " ".join(d.get("supervisor_nome", "").split())
    if not nome:
        raise ErroImportacao("supervisor_nome: obrigatório (todo estagiário precisa de um supervisor da concedente)")
    if len(nome.split()) < 2:
        raise ErroImportacao("supervisor_nome: informe nome e sobrenome")
    chave = _chave(nome)
    if chave in cache:
        sup = cache[chave]
    else:
        iguais = [u for u in Usuario.objects.filter(papel=Usuario.Papel.SUPERVISOR).prefetch_related("concedentes")
                  if _chave(u.nome_completo) == chave]
        sup = next((u for u in iguais if local in u.concedentes.all()), None) or (iguais[0] if len(iguais) == 1 else None)
        if sup:
            r.supervisores_existentes.add(sup)
        else:
            sup = criar_usuario(nome, Usuario.Papel.SUPERVISOR, usuario, senha_hash=senha_hash)
            r.supervisores_novos.append(sup)
        cache[chave] = sup
    if not sup.concedentes.filter(pk=local.pk).exists():
        if sup.concedentes.exists():
            r.supervisores_vinculados.append((sup, local))
        sup.concedentes.add(local)
    mudou = False
    for campo, col in (("telefone", "supervisor_telefone"), ("email", "supervisor_email"), ("cargo", "supervisor_cargo")):
        if d.get(col) and not getattr(sup, campo):
            setattr(sup, campo, d[col])
            mudou = True
    if mudou:
        sup.save()
    return sup


def modelo_csv():
    """CSV de exemplo (dados fictícios) com todas as colunas."""
    saida = io.StringIO()
    saida.write("﻿")
    w = csv.writer(saida, delimiter=";")
    w.writerow(NOMES_COLUNAS)
    exemplo = {
        "estagiario_nome": "Maria da Silva Souza", "estagiario_cpf": "529.982.247-25", "estagiario_telefone": "(85) 99999-0000",
        "curso": "Técnico em Informática", "turma": "3º A", "ano_turma": "2024", "data_inicio": "24/08/2026", "horas_anteriores": "120",
        "dias": "seg-sex", "horas_por_dia": "8", "entrada": "07:00", "saida_intervalo": "11:00",
        "volta_intervalo": "13:00", "saida": "17:00", "concedente_nome": "EEM Escola Exemplo",
        "concedente_razao_social": "Secretaria da Educação", "concedente_cnpj": "11.222.333/0001-81",
        "concedente_tipo_instituicao": "PUBLICA", "concedente_endereco": "Rua Exemplo", "concedente_numero": "100",
        "concedente_bairro": "Centro", "concedente_cidade": "Fortaleza", "concedente_uf": "CE",
        "concedente_telefone": "(85) 3100-0000", "representante_nome": "Fulana de Tal", "supervisor_nome": "Ciclano Pereira",
        "supervisor_telefone": "(85) 98888-0000",
    }
    w.writerow([exemplo.get(c, "") for c in NOMES_COLUNAS])
    return saida.getvalue()
