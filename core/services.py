"""Regras de negócio: contas, escalas, status dos dias, horas e notificações."""
import calendar
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Q, Sum

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


def criar_usuario(nome_completo, papel, criado_por=None, **extra):
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
    user.set_password(settings.SENHA_PADRAO)
    user.save()
    return user


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


def status_periodo(estagio, inicio, fim, hoje=None):
    from django.utils import timezone

    hoje = hoje or timezone.localdate()
    registros = {r.data: r for r in estagio.registros.filter(data__range=(inicio, fim))}
    feriados = dias_sem_estagio(estagio, inicio, fim)
    resultado = []
    dia = inicio
    while dia <= fim:
        resultado.append(_status_dia(estagio, dia, hoje, registros.get(dia), feriados.get(dia)))
        dia += timedelta(days=1)
    return resultado


def _status_dia(estagio, dia, hoje, registro, feriado):
    escala = estagio.escala_em(dia)
    dentro = dia >= estagio.data_inicio and (not estagio.data_fim or dia <= estagio.data_fim)
    previsto = bool(dentro and escala and dia.weekday() in escala.dias_lista and not feriado)

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
    elif feriado and dentro:
        cod = "sem_estagio"
    elif not dentro:
        cod = "fora"
    elif previsto:
        cod = "sem_registro" if dia < hoje else ("hoje" if dia == hoje else "previsto")
    else:
        cod = "livre"
    return StatusDia(dia, cod, ROTULOS[cod], previsto, registro, escala, feriado or "")


def status_hoje(estagio):
    from django.utils import timezone

    hoje = timezone.localdate()
    return status_periodo(estagio, hoje, hoje, hoje)[0]


def calendario_mes(estagio, ano, mes):
    """Semanas (listas de 7) com StatusDia ou None para preencher o grid."""
    _, ultimo = calendar.monthrange(ano, mes)
    inicio, fim = date(ano, mes, 1), date(ano, mes, ultimo)
    dias = status_periodo(estagio, inicio, fim)
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
    return {
        "total": total,
        "cumpridas": cumpridas,
        "pendentes": pendentes,
        "faltam": faltam,
        "pct": round(pct, 1),
        "pct_pendente": round(pct_pend, 1),
        "previsao_termino": previsao_termino(estagio, faltam),
        **contagem,
    }


def previsao_termino(estagio, horas_faltando):
    """Simula os próximos dias previstos na escala até completar as horas que faltam."""
    from django.utils import timezone

    if horas_faltando <= 0:
        return None
    hoje = timezone.localdate()
    inicio = max(hoje, estagio.data_inicio)
    limite = inicio + timedelta(days=730)
    feriados = dias_sem_estagio(estagio, inicio, limite)
    ja_registrados = set(estagio.registros.filter(data__gte=inicio).values_list("data", flat=True))
    acumulado, dia = Decimal(0), inicio
    while dia <= limite:
        esc = estagio.escala_em(dia)
        if esc and dia.weekday() in esc.dias_lista and dia not in feriados and dia not in ja_registrados:
            acumulado += esc.horas_por_dia
            if acumulado >= horas_faltando:
                return dia
        dia += timedelta(days=1)
    return None


def horas_padrao(estagio, dia):
    esc = estagio.escala_em(dia)
    return esc.horas_por_dia if esc else estagio.curso.horas_por_dia_padrao


def proximos_dias(estagio, quantidade=5):
    from django.utils import timezone

    hoje = timezone.localdate()
    fim = hoje + timedelta(days=60)
    return [s for s in status_periodo(estagio, hoje, fim) if s.codigo in ("hoje", "previsto")][:quantidade]
