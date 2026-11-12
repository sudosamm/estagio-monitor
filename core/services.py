"""Regras de negócio: contas, escalas, status dos dias, horas e notificações."""
import calendar
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.files.base import ContentFile
from django.db.models import Q, Sum
from django.utils.crypto import get_random_string

from .models import DiaSemEstagio, Estagio, Notificacao, Registro, Usuario

# ---------------------------------------------------------------- contas


def _sem_acento(texto):
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def gerar_username(nome_completo):
    """'Maria da Silva Souza' -> 'maria.souza' (com sufixo numérico se já existir)."""
    partes = [p for p in re.split(r"\s+", _sem_acento(nome_completo).lower().strip()) if p]
    partes = [re.sub(r"[^a-z0-9]", "", p) for p in partes]
    partes = [p for p in partes if p]
    if not partes:
        raise ValueError("Nome inválido")
    base = partes[0] if len(partes) == 1 else f"{partes[0]}.{partes[-1]}"
    username, n = base, 2
    while Usuario.objects.filter(username__iexact=username).exists():
        username = f"{base}{n}"
        n += 1
    return username


def normalizar_nome(nome):
    minusculas = {"da", "de", "do", "das", "dos", "e"}
    palavras = re.split(r"\s+", nome.strip())
    return " ".join(p.lower() if p.lower() in minusculas and i else p.capitalize() for i, p in enumerate(palavras))


def criar_usuario(nome_completo, papel, criado_por=None, senha_hash=None, concedente=None, **extra):
    nome = normalizar_nome(nome_completo)
    partes = nome.split()
    user = Usuario(
        username=gerar_username(nome),
        nome_completo=nome,
        first_name=partes[0][:150],
        last_name=(partes[-1] if len(partes) > 1 else "")[:150],
        papel=papel,
        criado_por=criado_por,
        deve_trocar_senha=True,
        **extra,
    )
    if senha_hash:  # importação em massa: reaproveita o hash da senha padrão (muito mais rápido)
        user.password = senha_hash
    else:
        user.set_password(settings.SENHA_PADRAO)
    user.save()
    if concedente:  # supervisor sempre nasce ligado a uma concedente
        user.concedentes.add(concedente)
    return user


def processar_foto(arquivo, lado=400):
    """Recorta a foto em quadrado, corrige a rotação do celular e salva como JPEG leve (sem metadados)."""
    from PIL import Image, ImageOps

    img = Image.open(arquivo)
    img = ImageOps.exif_transpose(img).convert("RGB")
    img = ImageOps.fit(img, (lado, lado), Image.Resampling.LANCZOS)
    saida = io.BytesIO()
    img.save(saida, "JPEG", quality=85, optimize=True)
    return ContentFile(saida.getvalue(), name=f"{get_random_string(12)}.jpg")


def redefinir_senha_padrao(user):
    user.set_password(settings.SENHA_PADRAO)
    user.deve_trocar_senha = True
    user.save(update_fields=["password", "deve_trocar_senha"])


# ---------------------------------------------------------------- acesso


def estagios_visiveis(user):
    qs = Estagio.objects.select_related("estagiario", "supervisor", "orientador", "local", "curso")
    if user.is_superuser:
        return qs
    if user.is_orientador:
        return qs.filter(orientador=user)
    if user.is_coordenador:
        ids = user.cursos_ids()
        return qs if ids is None else qs.filter(curso_id__in=ids)
    if user.is_supervisor:
        return qs.filter(supervisor=user)
    return qs.filter(estagiario=user)


# ---------------------------------------------------------------- notificações


def notificar(usuarios, texto, link="", exceto=None):
    vistos = set()
    objs = []
    for u in usuarios:
        if not u or u.pk in vistos or (exceto and u.pk == exceto.pk):
            continue
        vistos.add(u.pk)
        objs.append(Notificacao(usuario=u, texto=texto[:255], link=link))
    Notificacao.objects.bulk_create(objs)


# ---------------------------------------------------------------- dias e status


@dataclass
class StatusDia:
    data: date
    codigo: str  # confirmado, aguardando, contestado, ausencia, falta, sem_registro, hoje, previsto, sem_estagio, livre, fora
    rotulo: str
    previsto: bool
    registro: Registro | None = None
    escala: object = None
    motivo_sem_estagio: str = ""
    plano: object = None  # DiaPlanejado
    extra: bool = False  # dia de estágio fora da escala, planejado pelo estagiário
    horas_previstas: Decimal = Decimal(0)

    @property
    def hoje(self):
        from django.utils import timezone

        return self.data == timezone.localdate()


ROTULOS = {
    "confirmado": "Presença confirmada",
    "aguardando": "Presente — aguardando supervisor",
    "contestado": "Presença contestada",
    "ausencia": "Ausência informada",
    "ausencia_ok": "Ausência justificada",
    "falta": "Falta",
    "sem_registro": "Sem registro",
    "hoje": "Hoje — presença não marcada",
    "previsto": "Dia de estágio",
    "sem_estagio": "Sem estágio",
    "livre": "",
    "fora": "Fora do período",
}


def dias_sem_estagio(estagio, inicio, fim):
    qs = DiaSemEstagio.objects.filter(orientador_id=estagio.orientador_id, data__range=(inicio, fim)).filter(
        Q(curso__isnull=True) | Q(curso_id=estagio.curso_id)
    )
    return {d.data: d.descricao for d in qs}


def status_periodo(estagio, inicio, fim, hoje=None, limite=None):
    """Status de cada dia entre inicio e fim.

    `limite` é o último dia de estágio (normalmente a previsão de término): depois dele os dias
    aparecem como fora do período. A data de término do termo não limita, porque o estágio só
    acaba quando a carga horária é cumprida.
    """
    from django.utils import timezone

    hoje = hoje or timezone.localdate()
    registros = {r.data: r for r in estagio.registros.filter(data__range=(inicio, fim))}
    planos = {p.data: p for p in estagio.dias_planejados.filter(data__range=(inicio, fim))}
    feriados = dias_sem_estagio(estagio, inicio, fim)
    resultado = []
    dia = inicio
    while dia <= fim:
        resultado.append(_status_dia(estagio, dia, hoje, registros.get(dia), feriados.get(dia), planos.get(dia), limite))
        dia += timedelta(days=1)
    return resultado


def _status_dia(estagio, dia, hoje, registro, feriado, plano=None, limite=None):
    escala = estagio.escala_em(dia)
    inicio = max(estagio.data_inicio, estagio.acompanhamento_desde or estagio.data_inicio)
    dentro = dia >= inicio and (limite is None or dia <= limite)
    regular = bool(escala and dia.weekday() in escala.dias_lista and not feriado)
    previsto = bool(dentro and (regular or plano))

    if registro:
        if registro.situacao == Registro.Situacao.PRESENTE:
            cod = {
                Registro.Confirmacao.CONFIRMADA: "confirmado",
                Registro.Confirmacao.CONTESTADA: "contestado",
            }.get(registro.confirmacao, "aguardando")
        elif registro.situacao == Registro.Situacao.AUSENCIA:
            cod = "ausencia_ok" if registro.confirmacao == Registro.Confirmacao.CONFIRMADA else "ausencia"
        else:
            cod = "falta"
    elif feriado and dentro and not plano:
        cod = "sem_estagio"
    elif not dentro:
        cod = "fora"
    elif previsto:
        cod = "sem_registro" if dia < hoje else ("hoje" if dia == hoje else "previsto")
    else:
        cod = "livre"
    horas_prev = plano.horas if plano else (escala.horas_por_dia if escala and regular else Decimal(0))
    return StatusDia(dia, cod, ROTULOS[cod], previsto, registro, escala, feriado or "", plano,
                     bool(plano and not regular), horas_prev)


def status_hoje(estagio):
    from django.utils import timezone

    hoje = timezone.localdate()
    return status_periodo(estagio, hoje, hoje, hoje)[0]


def calendario_mes(estagio, ano, mes, limite=None):
    """Semanas (listas de 7) com StatusDia ou None para preencher o grid."""
    _, ultimo = calendar.monthrange(ano, mes)
    inicio, fim = date(ano, mes, 1), date(ano, mes, ultimo)
    dias = status_periodo(estagio, inicio, fim, limite=limite)
    semanas, semana = [], [None] * inicio.weekday()
    for d in dias:
        semana.append(d)
        if len(semana) == 7:
            semanas.append(semana)
            semana = []
    if semana:
        semanas.append(semana + [None] * (7 - len(semana)))
    return semanas


# ---------------------------------------------------------------- horas


def resumo_horas(estagio):
    regs = estagio.registros.filter(situacao=Registro.Situacao.PRESENTE)
    confirmadas = regs.filter(confirmacao=Registro.Confirmacao.CONFIRMADA).aggregate(s=Sum("horas"))["s"] or Decimal(0)
    pendentes = regs.filter(confirmacao=Registro.Confirmacao.PENDENTE).aggregate(s=Sum("horas"))["s"] or Decimal(0)
    total = Decimal(estagio.carga_horaria_total)
    cumpridas = confirmadas + estagio.horas_anteriores
    faltam = max(total - cumpridas - pendentes, Decimal(0))
    pct = float(min(cumpridas / total * 100, 100)) if total else 0
    pct_pend = float(min(pendentes / total * 100, 100 - pct)) if total else 0
    contagem = {
        "presencas": regs.count(),
        "ausencias": estagio.registros.filter(situacao=Registro.Situacao.AUSENCIA).count(),
        "faltas": estagio.registros.filter(situacao=Registro.Situacao.FALTA).count(),
    }
    termino, dias_restantes = simular_termino(estagio, faltam)
    return {
        "total": total,
        "cumpridas": cumpridas,
        "pendentes": pendentes,
        "faltam": faltam,
        "pct": round(pct, 1),
        "pct_pendente": round(pct_pend, 1),
        "previsao_termino": termino,
        "dias_restantes": dias_restantes,
        "apos_termo": bool(termino and estagio.data_fim and termino > estagio.data_fim),
        **contagem,
    }


def simular_termino(estagio, horas_faltando):
    """Percorre os próximos dias de estágio até completar as horas que faltam.

    Conta a escala vigente em cada dia, pula feriados/eventos da escola e dias que já têm
    registro (ex.: ausência informada para o futuro) e inclui os dias planejados pelo
    estagiário (reposições ou dias com outra carga). Devolve (data de término, nº de dias).
    """
    from django.utils import timezone

    if horas_faltando <= 0:
        return None, 0
    hoje = timezone.localdate()
    inicio = max(hoje, estagio.data_inicio)
    limite = inicio + timedelta(days=730)
    feriados = dias_sem_estagio(estagio, inicio, limite)
    ja_registrados = set(estagio.registros.filter(data__gte=inicio).values_list("data", flat=True))
    planos = dict(estagio.dias_planejados.filter(data__gte=inicio).values_list("data", "horas"))
    acumulado, dia, n = Decimal(0), inicio, 0
    while dia <= limite:
        if dia not in ja_registrados:
            esc = estagio.escala_em(dia)
            if dia in planos:
                horas = planos[dia]
            elif esc and dia.weekday() in esc.dias_lista and dia not in feriados:
                horas = esc.horas_por_dia
            else:
                horas = 0
            if horas:
                acumulado += horas
                n += 1
                if acumulado >= horas_faltando:
                    return dia, n
        dia += timedelta(days=1)
    return None, n


def previsao_termino(estagio, horas_faltando):
    return simular_termino(estagio, horas_faltando)[0]


def limite_calendario(estagio, resumo):
    """Último dia que deve aparecer como dia de estágio no calendário."""
    from django.utils import timezone

    if resumo["faltam"] <= 0:
        ultimo = estagio.registros.filter(situacao=Registro.Situacao.PRESENTE).order_by("-data").first()
        return ultimo.data if ultimo else timezone.localdate()
    return resumo["previsao_termino"]


def horas_padrao(estagio, dia):
    plano = estagio.dias_planejados.filter(data=dia).first()
    if plano:
        return plano.horas
    esc = estagio.escala_em(dia)
    return esc.horas_por_dia if esc else estagio.curso.horas_por_dia_padrao


def proximos_dias(estagio, quantidade=5, limite=None):
    from django.utils import timezone

    hoje = timezone.localdate()
    fim = hoje + timedelta(days=60)
    return [s for s in status_periodo(estagio, hoje, fim, limite=limite) if s.codigo in ("hoje", "previsto")][:quantidade]


# ---------------------------------------------------------------- folha de frequência

DIAS_EXTENSO = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


def linhas_folha(estagio, ano, mes):
    """Linhas da folha oficial: fins de semana em cinza, feriados/eventos preenchidos com o nome."""
    _, ultimo = calendar.monthrange(ano, mes)
    inicio, fim = date(ano, mes, 1), date(ano, mes, ultimo)
    feriados = dias_sem_estagio(estagio, inicio, fim)
    planos = set(estagio.dias_planejados.filter(data__range=(inicio, fim)).values_list("data", flat=True))
    linhas = []
    for n in range(1, ultimo + 1):
        dia = date(ano, mes, n)
        fds = dia.weekday() >= 5 and dia not in planos
        antes = dia < estagio.data_inicio
        linhas.append({
            "data": dia, "dia_semana": DIAS_EXTENSO[dia.weekday()],
            "feriado": feriados.get(dia, "") if dia not in planos else "",
            "cinza": fds or antes or (dia in feriados and dia not in planos),
        })
    return linhas


# ---------------------------------------------------------------- captação de concedentes


def gestores_da_candidatura(cand):
    """Orientadores e coordenadores que devem analisar a candidatura (coordenador só se tiver o curso)."""
    from .models import Usuario

    cursos = set(cand.vagas.values_list("curso_id", flat=True))
    pessoas = []
    for u in Usuario.objects.filter(is_active=True).filter(
            Q(papel__in=[Usuario.Papel.ORIENTADOR, Usuario.Papel.COORDENADOR]) | Q(is_superuser=True)):
        if not u.pode("candidaturas"):
            continue
        ids = u.cursos_ids() if u.is_coordenador else None
        if ids is None or ids & cursos:
            pessoas.append(u)
    return pessoas


def _nome_escola():
    from .models import Configuracao

    return Configuracao.atual().nome_escola or settings.NOME_INSTITUICAO


def aprovar_candidatura(cand, usuario, destino="nova", criar_supervisor=False, parecer="", endereco=""):
    """Cadastra (ou atualiza) a concedente, cria o supervisor indicado e prepara o aviso para a concedente."""
    from django.db import transaction
    from django.utils import timezone

    from .models import CAMPOS_CONCEDENTE, AvisoExterno, LocalEstagio, Usuario

    with transaction.atomic():
        if destino == "nova":
            local = LocalEstagio.objects.create(**{c: getattr(cand, c) for c in CAMPOS_CONCEDENTE})
        else:
            local = LocalEstagio.objects.get(pk=destino)
            for campo in CAMPOS_CONCEDENTE:  # completa só o que estava vazio
                if not getattr(local, campo) and getattr(cand, campo):
                    setattr(local, campo, getattr(cand, campo))
            local.save()
        supervisor = None
        if criar_supervisor and cand.supervisor_nome:
            supervisor = criar_usuario(cand.supervisor_nome, Usuario.Papel.SUPERVISOR, usuario, concedente=local,
                                       telefone=cand.supervisor_telefone, email=cand.supervisor_email,
                                       cargo=cand.supervisor_cargo)
        cand.status, cand.local = cand.Status.APROVADA, local
        cand.analisado_por, cand.analisado_em, cand.parecer = usuario, timezone.now(), parecer
        cand.save()
        linhas = [
            f"Olá, {cand.contato_nome.split()[0]}!",
            "",
            f"O cadastro de {cand.nome} como concedente de estágio para o ano letivo de {cand.ano} foi aprovado "
            f"pela {_nome_escola()}. Obrigado pela parceria!",
        ]
        vagas = ", ".join(f"{v.quantidade} de {v.curso.nome}" for v in cand.vagas.select_related("curso"))
        if vagas:
            linhas.append(f"Vagas informadas: {vagas}.")
        if parecer:
            linhas += ["", parecer]
        if supervisor:
            linhas += ["", f"O(a) supervisor(a) {supervisor.nome_completo} já tem acesso ao sistema de acompanhamento "
                           f"de estágio{f' ({endereco})' if endereco else ''}, com o usuário {supervisor.username}. "
                           "A senha inicial será informada pela escola e deverá ser trocada no primeiro acesso."]
        linhas += ["", "Em breve entraremos em contato para combinar os próximos passos.",
                   f"{usuario.nome_completo} — {_nome_escola()}", f"Protocolo {cand.protocolo}"]
        aviso = AvisoExterno.objects.create(
            candidatura=cand, destinatario=cand.contato_nome, email=cand.contato_email or cand.representante_email,
            telefone=cand.contato_telefone, assunto=f"Cadastro de concedente aprovado — {_nome_escola()}",
            mensagem="\n".join(linhas), criado_por=usuario,
        )
    return local, supervisor, aviso


def recusar_candidatura(cand, usuario, parecer):
    from django.utils import timezone

    from .models import AvisoExterno

    cand.status, cand.parecer = cand.Status.RECUSADA, parecer
    cand.analisado_por, cand.analisado_em = usuario, timezone.now()
    cand.save()
    mensagem = "\n".join([
        f"Olá, {cand.contato_nome.split()[0]}!", "",
        f"Agradecemos o interesse de {cand.nome} em receber estagiários da {_nome_escola()} em {cand.ano}. "
        "Neste momento não foi possível aprovar o cadastro.", "", parecer, "",
        f"{usuario.nome_completo} — {_nome_escola()}", f"Protocolo {cand.protocolo}",
    ])
    return AvisoExterno.objects.create(
        candidatura=cand, destinatario=cand.contato_nome, email=cand.contato_email or cand.representante_email,
        telefone=cand.contato_telefone, assunto=f"Cadastro de concedente — {_nome_escola()}", mensagem=mensagem,
        criado_por=usuario,
    )
