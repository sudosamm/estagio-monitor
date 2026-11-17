"""Planilha modelo (Excel) para cadastrar estagiários, concedentes e supervisores de uma vez.

O SICE não exporta planilhas, então o ponto de partida é este modelo: uma aba para cada cadastro, com listas
suspensas ligando estagiário → concedente → supervisor. Na leitura, cada estagiário vira uma linha no formato
do importador CSV (com os dados da concedente e do supervisor juntados), e concedentes e supervisores sem
estagiário também são cadastrados.
"""
import io
import re
import unicodedata
import zipfile
from datetime import date, datetime, time

from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .importacao import ErroImportacao
from .validators import cnpj_valido, so_digitos

ABA_ESTAGIARIOS, ABA_CONCEDENTES, ABA_SUPERVISORES = "Estagiários", "Concedentes", "Supervisores"
LINHAS = 500  # linhas preparadas com listas suspensas e formatos

# (chave do importador, título na planilha, obrigatória, explicação, largura, formato)
TEXTO, DATA, HORA = "@", "DD/MM/YYYY", "HH:MM"
COLUNAS_ESTAGIARIOS = [
    ("estagiario_nome", "Nome completo", True, "Nome e sobrenome, como no documento.", 34, None),
    ("estagiario_cpf", "CPF", False, "Evita cadastrar a mesma pessoa duas vezes. Com ou sem pontos.", 16, TEXTO),
    ("estagiario_nascimento", "Data de nascimento", False, "dd/mm/aaaa. Com o nome completo, é o primeiro acesso do estagiário.", 13, DATA),
    ("estagiario_telefone", "Telefone", False, "", 16, TEXTO),
    ("estagiario_email", "E-mail", False, "", 26, None),
    ("matricula", "Matrícula", False, "", 14, TEXTO),
    ("curso", "Curso", True, "Nome do curso. Se não existir no sistema, é criado.", 26, None),
    ("turma", "Turma", False, "Ex.: 3º A. Vazio = nome do curso.", 10, None),
    ("ano_turma", "Ano de ingresso da turma", False, "Ex.: 2024. Vazio = 2 anos antes do início do estágio.", 12, None),
    ("data_inicio", "Início do estágio", True, "dd/mm/aaaa", 13, DATA),
    ("data_fim", "Término previsto", False, "Data do termo de compromisso (dd/mm/aaaa).", 13, DATA),
    ("horas_anteriores", "Horas já cumpridas", False, "Horas feitas antes de começar a usar o sistema.", 11, None),
    ("dias", "Dias de estágio", False, "Ex.: seg-sex, seg,qua,sex. Vazio = padrão escolhido na tela de importação.", 14, None),
    ("horas_por_dia", "Horas por dia", False, "Qualquer carga: 4, 5, 7, 8 (5,5 = 5h30). Vazio = calculada pelos horários ou a da tela.", 9, None),
    ("entrada", "Entrada", False, "HH:MM", 9, HORA),
    ("saida_intervalo", "Saída p/ intervalo", False, "HH:MM", 9, HORA),
    ("volta_intervalo", "Volta do intervalo", False, "HH:MM", 9, HORA),
    ("saida", "Saída", False, "HH:MM", 9, HORA),
    ("concedente_nome", "Concedente", True, "Escolha da aba Concedentes (ou o nome de uma já cadastrada no sistema).", 30, None),
    ("supervisor_nome", "Supervisor", False, "Escolha da aba Supervisores. Vazio = o único supervisor da concedente na aba.", 30, None),
    ("orientador", "Orientador (usuário)", False, "Usuário de acesso do orientador. Vazio = o escolhido na tela.", 18, None),
    ("presencas_desde", "Presenças já cumpridas desde", False, "Dias da escala desta data até ontem entram como presença "
     "confirmada (horas feitas e ainda não lançadas no SICE). Vazio = nenhum.", 14, DATA),
    ("curso_carga_horaria", "Carga horária do curso", False, "Só vale quando o curso é criado. Vazio = a da tela.", 11, None),
]
COLUNAS_CONCEDENTES = [
    ("concedente_nome", "Nome da unidade", True, "Nome fantasia ou unidade (sai na folha de frequência). Órgãos com várias unidades: uma linha por unidade.", 32, None),
    ("concedente_razao_social", "Razão social", False, "", 32, None),
    ("concedente_cnpj", "CNPJ ou CPF", False, "CNPJ da empresa/órgão, ou CPF de profissional liberal.", 20, TEXTO),
    ("concedente_tipo_instituicao", "Pública ou privada", False, "", 12, None),
    ("concedente_endereco", "Endereço", False, "Rua, avenida...", 28, None),
    ("concedente_numero", "Número", False, "", 8, TEXTO),
    ("concedente_bairro", "Bairro", False, "", 18, None),
    ("concedente_complemento", "Complemento", False, "", 14, None),
    ("concedente_cidade", "Município", False, "Usado para os feriados municipais.", 18, None),
    ("concedente_uf", "UF", False, "", 6, None),
    ("concedente_cep", "CEP", False, "", 11, TEXTO),
    ("concedente_telefone", "Telefone", False, "", 16, TEXTO),
    ("representante_nome", "Representante legal", False, "Quem assina o termo pela concedente.", 28, None),
    ("representante_email", "E-mail do representante", False, "", 26, None),
    ("representante_cpf", "CPF do representante", False, "", 16, TEXTO),
    ("representante_documento", "RG do representante", False, "Ex.: RG 2001234567 SSP/CE", 22, None),
]
COLUNAS_SUPERVISORES = [
    ("supervisor_nome", "Nome completo", True, "Nome e sobrenome. Recebe uma conta de acesso.", 32, None),
    ("concedente_nome", "Concedente", True, "Escolha da aba Concedentes. Quem supervisiona em duas concedentes: uma linha para cada.", 32, None),
    ("supervisor_telefone", "Telefone", False, "", 16, TEXTO),
    ("supervisor_email", "E-mail", False, "", 26, None),
    ("supervisor_cargo", "Cargo ou função", False, "", 22, None),
]
ABAS = {ABA_ESTAGIARIOS: COLUNAS_ESTAGIARIOS, ABA_CONCEDENTES: COLUNAS_CONCEDENTES, ABA_SUPERVISORES: COLUNAS_SUPERVISORES}
UFS = "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split()
DIAS_SUGERIDOS = ["seg-sex", "seg-qui", "seg,qua,sex", "ter,qui", "seg,ter", "qua,qui", "sab"]

VERDE, VERDE_CLARO, AMARELO = "005A2B", "E6F2EA", "FFF4CC"


def _chave(texto):
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"\(.*?\)|\*", " ", t.lower())
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


# ------------------------------------------------------------------ gerar o modelo

def gerar_modelo(cursos=(), turmas=(), orientadores=()):
    """Arquivo .xlsx em branco, com listas suspensas. `cursos`, `turmas` e `orientadores` já cadastrados no sistema
    entram nas listas para facilitar o preenchimento."""
    wb = Workbook()
    leia = wb.active
    leia.title = "Leia-me"
    _leia_me(leia)

    listas = wb.create_sheet("Listas")
    colunas_listas = {
        "cursos": sorted(set(cursos)), "turmas": sorted(set(turmas)), "orientadores": sorted(set(orientadores)),
        "tipos": ["Pública", "Privada"], "ufs": UFS, "dias": DIAS_SUGERIDOS,
    }
    refs = {}
    for i, (nome, valores) in enumerate(colunas_listas.items(), start=1):
        letra = get_column_letter(i)
        listas.cell(row=1, column=i, value=nome)
        for j, v in enumerate(valores, start=2):
            listas.cell(row=j, column=i, value=v)
        refs[nome] = f"Listas!${letra}$2:${letra}${max(len(valores), 1) + 1}" if valores else None
    listas.sheet_state = "hidden"

    abas = {}
    for titulo, colunas in ABAS.items():
        ws = wb.create_sheet(titulo)
        abas[titulo] = ws
        for i, (chave, rotulo, obrig, explicacao, largura, formato) in enumerate(colunas, start=1):
            c = ws.cell(row=1, column=i, value=rotulo + (" *" if obrig else ""))
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor=VERDE if obrig else "2E7D4F")
            c.alignment = Alignment(wrap_text=True, vertical="center")
            if explicacao:
                c.comment = Comment(explicacao, "Estágio Monitor", width=260, height=90)
            letra = get_column_letter(i)
            ws.column_dimensions[letra].width = largura
            if formato:
                for linha in range(2, LINHAS + 2):
                    ws.cell(row=linha, column=i).number_format = formato
        ws.row_dimensions[1].height = 34
        ws.freeze_panes = "B2"
        ws.auto_filter.ref = f"A1:{get_column_letter(len(colunas))}1"

    def lista(ws, colunas, chave, formula, aviso=True, titulo=None, mensagem=None):
        if not formula:
            return
        idx = [c[0] for c in colunas].index(chave) + 1
        letra = get_column_letter(idx)
        dv = DataValidation(type="list", formula1=formula, allow_blank=True,
                            errorStyle="warning" if aviso else "stop", showErrorMessage=True)
        dv.errorTitle = titulo or "Valor fora da lista"
        dv.error = mensagem or "Este valor não está na lista. Deseja manter assim mesmo?"
        ws.add_data_validation(dv)
        dv.add(f"{letra}2:{letra}{LINHAS + 1}")

    nomes_concedentes = f"Concedentes!$A$2:$A${LINHAS + 1}"
    est, con, sup = abas[ABA_ESTAGIARIOS], abas[ABA_CONCEDENTES], abas[ABA_SUPERVISORES]
    lista(est, COLUNAS_ESTAGIARIOS, "curso", refs["cursos"])
    lista(est, COLUNAS_ESTAGIARIOS, "turma", refs["turmas"])
    lista(est, COLUNAS_ESTAGIARIOS, "orientador", refs["orientadores"])
    idx_horas = [c[0] for c in COLUNAS_ESTAGIARIOS].index("horas_por_dia") + 1
    dv = DataValidation(type="decimal", operator="between", formula1="0.5", formula2="12", allow_blank=True,
                        errorStyle="stop", showErrorMessage=True)
    dv.errorTitle, dv.error = "Horas por dia", "Digite as horas por dia em número, entre 0,5 e 12 (ex.: 4, 5, 7 ou 5,5)."
    est.add_data_validation(dv)
    dv.add(f"{get_column_letter(idx_horas)}2:{get_column_letter(idx_horas)}{LINHAS + 1}")
    lista(est, COLUNAS_ESTAGIARIOS, "dias", refs["dias"],
          mensagem="Formato livre aceito: seg, ter, qua, qui, sex, sab, dom, separados por vírgula ou com hífen (seg-sex).")
    lista(est, COLUNAS_ESTAGIARIOS, "concedente_nome", nomes_concedentes,
          mensagem="Essa concedente não está na aba Concedentes. Mantenha só se ela já estiver cadastrada no sistema.")
    lista(est, COLUNAS_ESTAGIARIOS, "supervisor_nome", f"Supervisores!$A$2:$A${LINHAS + 1}",
          mensagem="Esse supervisor não está na aba Supervisores. Ele será criado com os dados mínimos.")
    lista(con, COLUNAS_CONCEDENTES, "concedente_tipo_instituicao", refs["tipos"], aviso=False)
    lista(con, COLUNAS_CONCEDENTES, "concedente_uf", refs["ufs"], aviso=False, mensagem="Use a sigla do estado (ex.: CE).")
    lista(sup, COLUNAS_SUPERVISORES, "concedente_nome", nomes_concedentes,
          mensagem="Essa concedente não está na aba Concedentes. Mantenha só se ela já estiver cadastrada no sistema.")
    for chave in ("data_inicio", "data_fim"):
        idx = [c[0] for c in COLUNAS_ESTAGIARIOS].index(chave) + 1
        letra = get_column_letter(idx)
        dv = DataValidation(type="date", operator="greaterThan", formula1="DATE(2000,1,1)", allow_blank=True,
                            errorStyle="stop", showErrorMessage=True)
        dv.errorTitle, dv.error = "Data inválida", "Digite a data como dd/mm/aaaa."
        est.add_data_validation(dv)
        dv.add(f"{letra}2:{letra}{LINHAS + 1}")

    wb.move_sheet("Listas", offset=len(wb.sheetnames))
    wb.active = 1  # abre na aba Estagiários
    saida = io.BytesIO()
    wb.save(saida)
    return saida.getvalue()


def _leia_me(ws):
    ws.column_dimensions["A"].width = 110
    textos = [
        ("Planilha de cadastro — Estágio Monitor", Font(bold=True, size=14, color=VERDE)),
        ("", None),
        ("Preencha nesta ordem:", Font(bold=True)),
        ("1. Concedentes: uma linha por unidade que recebe estagiários (empresa, órgão, escola, profissional liberal).", None),
        ("2. Supervisores: uma linha por supervisor, escolhendo a concedente dele na lista.", None),
        ("3. Estagiários: uma linha por estagiário, escolhendo a concedente e o supervisor nas listas.", None),
        ("", None),
        ("Colunas com * são obrigatórias. Passe o mouse sobre o título da coluna para ver a explicação.", None),
        ("Datas no formato dd/mm/aaaa e horários como HH:MM (ex.: 07:30).", None),
        ("Se a concedente tiver um supervisor só na aba Supervisores, a coluna Supervisor do estagiário pode ficar vazia.", None),
        ("Concedentes e supervisores já cadastrados no sistema (mesmo nome) são reaproveitados, sem duplicar.", None),
        ("Estagiários que já têm estágio ativo no sistema (mesmo CPF) são ignorados: dá para enviar a planilha de novo.", None),
        ("", None),
        ("Depois de preencher:", Font(bold=True)),
        ("Contas → Importar planilha → envie este arquivo. O sistema mostra uma prévia com os erros por linha antes de gravar.", None),
        ("Não há senha inicial: cada pessoa cria a própria em “Primeiro acesso” (estagiário: nome completo + data de nascimento; os demais: código da folha impressa).", None),
        ("", None),
        ("Atenção: esta planilha contém dados pessoais (CPF, telefone). Guarde-a em local seguro e apague cópias que não forem mais necessárias.", Font(italic=True, color="9A3412")),
    ]
    for i, (texto, fonte) in enumerate(textos, start=1):
        c = ws.cell(row=i, column=1, value=texto)
        c.alignment = Alignment(wrap_text=True)
        if fonte:
            c.font = fonte
    ws.sheet_view.showGridLines = False


# ------------------------------------------------------------------ ler a planilha preenchida

def eh_planilha(conteudo, nome=""):
    return nome.lower().endswith(".xlsx") or (conteudo[:2] == b"PK" and not nome.lower().endswith(".csv"))


def _texto(valor, chave):
    if valor is None:
        return ""
    if isinstance(valor, datetime):
        if chave in ("entrada", "saida_intervalo", "volta_intervalo", "saida") or valor.year < 1901:
            return valor.strftime("%H:%M")
        return valor.strftime("%d/%m/%Y")
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    if isinstance(valor, time):
        return valor.strftime("%H:%M")
    if isinstance(valor, float):
        if chave in ("entrada", "saida_intervalo", "volta_intervalo", "saida") and 0 <= valor < 1:
            minutos = round(valor * 24 * 60)
            return f"{minutos // 60:02d}:{minutos % 60:02d}"
        valor = int(valor) if valor.is_integer() else valor
    texto = " ".join(str(valor).split())
    # documentos digitados como número perdem os zeros à esquerda
    if texto.isdigit():
        if chave in ("estagiario_cpf", "representante_cpf") and len(texto) < 11:
            texto = texto.zfill(11)
        elif chave == "concedente_cnpj" and len(texto) < 14:
            texto = texto.zfill(14) if cnpj_valido(texto.zfill(14)) else texto.zfill(11)
        elif chave == "concedente_cep" and len(texto) < 8:
            texto = texto.zfill(8)
    return texto


def _ler_aba(ws, colunas):
    """Linhas preenchidas da aba como [(número da linha, {chave: texto})]."""
    linhas = ws.iter_rows(values_only=True)
    try:
        cabecalho = next(linhas)
    except StopIteration:
        return []
    por_titulo = {}
    for chave, rotulo, *_ in colunas:
        por_titulo[_chave(rotulo)] = chave
        por_titulo[_chave(chave.replace("_", " "))] = chave
    mapa = {i: por_titulo.get(_chave(t)) for i, t in enumerate(cabecalho) if t}
    faltando = [rotulo for chave, rotulo, obrig, *_ in colunas if obrig and chave not in mapa.values()]
    if faltando:
        raise ErroImportacao(f"Aba {ws.title}: faltam as colunas " + ", ".join(faltando)
                             + ". Baixe a planilha modelo de novo.")
    saida = []
    for n, valores in enumerate(linhas, start=2):
        d = {mapa[i]: _texto(v, mapa[i]) for i, v in enumerate(valores) if mapa.get(i)}
        if any(d.values()):
            saida.append((n, d))
    return saida


def ler_planilha(conteudo):
    """Lê o .xlsx preenchido. Devolve (linhas de estagiários no formato do importador, concedentes sem estagiário,
    supervisores sem estagiário). As linhas são numeradas com o nome da aba para as mensagens de erro."""
    try:
        wb = load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    except (zipfile.BadZipFile, KeyError, ValueError, OSError) as exc:
        raise ErroImportacao("Não consegui abrir a planilha. Salve como .xlsx (Excel) e envie de novo.") from exc
    nomes = {_chave(n): n for n in wb.sheetnames}
    abas = {}
    for titulo, colunas in ABAS.items():
        real = nomes.get(_chave(titulo))
        abas[titulo] = _ler_aba(wb[real], colunas) if real else []
    wb.close()
    if not abas[ABA_ESTAGIARIOS] and not abas[ABA_CONCEDENTES] and not abas[ABA_SUPERVISORES]:
        raise ErroImportacao("A planilha está vazia. Preencha as abas Concedentes, Supervisores e Estagiários.")

    erros = []
    concedentes = {}
    for n, d in abas[ABA_CONCEDENTES]:
        k = _chave(d.get("concedente_nome"))
        if not k:
            erros.append(f"Concedentes, linha {n}: falta o nome da unidade")
        elif k in concedentes:
            erros.append(f"Concedentes, linha {n}: “{d['concedente_nome']}” repetida (já está na linha {concedentes[k][0]})")
        else:
            concedentes[k] = (n, d)

    def dados_concedente(nome):
        achada = concedentes.get(_chave(nome))
        return dict(achada[1]) if achada else {"concedente_nome": nome}

    supervisores, por_concedente = {}, {}
    for n, d in abas[ABA_SUPERVISORES]:
        k, kc = _chave(d.get("supervisor_nome")), _chave(d.get("concedente_nome"))
        if not k:
            erros.append(f"Supervisores, linha {n}: falta o nome")
            continue
        if not kc:
            erros.append(f"Supervisores, linha {n}: escolha a concedente de {d['supervisor_nome']}")
            continue
        if (k, kc) in supervisores:
            erros.append(f"Supervisores, linha {n}: {d['supervisor_nome']} repetido na mesma concedente")
            continue
        supervisores[(k, kc)] = (n, d)
        por_concedente.setdefault(kc, []).append(d)
    if erros:
        raise ErroImportacao("; ".join(erros[:10]) + (f" (e mais {len(erros) - 10})" if len(erros) > 10 else ""))

    linhas, usadas_c, usados_s = [], set(), set()
    for n, d in abas[ABA_ESTAGIARIOS]:
        linha = dict(d)
        kc = _chave(d.get("concedente_nome"))
        if kc:
            linha.update(dados_concedente(d["concedente_nome"]))
            usadas_c.add(kc)
        ks = _chave(d.get("supervisor_nome"))
        if not ks and kc and len(por_concedente.get(kc, [])) == 1:
            ks = _chave(por_concedente[kc][0]["supervisor_nome"])
            linha["supervisor_nome"] = por_concedente[kc][0]["supervisor_nome"]
        if ks:
            achado = supervisores.get((ks, kc))
            if achado:
                linha.update({c: v for c, v in achado[1].items() if c.startswith("supervisor_")})
                usados_s.add((ks, kc))
        linhas.append((f"{ABA_ESTAGIARIOS}, linha {n}", linha))

    concedentes_soltas = [(f"{ABA_CONCEDENTES}, linha {n}", d) for k, (n, d) in concedentes.items() if k not in usadas_c]
    supervisores_soltos = []
    for chave, (n, d) in supervisores.items():
        if chave in usados_s:
            continue
        linha = dados_concedente(d["concedente_nome"])
        linha.update(d)
        supervisores_soltos.append((f"{ABA_SUPERVISORES}, linha {n}", linha))
    return linhas, concedentes_soltas, supervisores_soltos
