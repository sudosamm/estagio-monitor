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
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils.crypto import get_random_string

from .models import DiaSemEstagio, Estagio, Notificacao, Registro, Usuario, chave_municipio

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
    # sem senha: a pessoa cria a própria no primeiro acesso (nome + nascimento ou código de uso único)
    if senha_hash:  # importação em massa: um hash “inutilizável” pronto, sem gerar um por conta
        user.password = senha_hash
    else:
        user.set_unusable_password()
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


# ---------------------------------------------------------------- turmas e ano de referência

ANOS_ATE_ESTAGIO = 2  # a turma de 2024 estagia em 2026


def ano_referencia():
    from .models import Configuracao

    return Configuracao.atual().ano_referencia_efetivo


def ano_em_uso(request):
    """Ano que a pessoa está vendo nas listas: o escolhido na tela (guardado na sessão) ou o de referência.

    Devolve None quando ela escolheu “todos os anos”.
    """
    escolhido = request.GET.get("ano")
    if escolhido is not None:
        if escolhido == "todos":
            request.session["ano_lista"] = "todos"
        elif escolhido.isdigit():
            request.session["ano_lista"] = int(escolhido)
        else:
            request.session.pop("ano_lista", None)
    ano = request.session.get("ano_lista")
    if ano == "todos":
        return None
    return ano or ano_referencia()


def filtrar_ano(qs, ano, prefixo=""):
    """Estágios das turmas que estagiam no ano (os sem turma aparecem sempre, para não sumirem)."""
    if ano is None:
        return qs
    return qs.filter(Q(**{f"{prefixo}turma__ano_estagio": ano}) | Q(**{f"{prefixo}turma__isnull": True}))


def anos_disponiveis():
    from .models import Turma

    anos = set(Turma.objects.values_list("ano_estagio", flat=True)) | {ano_referencia()}
    return sorted(anos, reverse=True)


def turma_para(curso, nome, ano_estagio, ano_ingresso=None):
    """A turma do curso naquele ano (cria se não existir)."""
    from .models import Turma

    nome = " ".join((nome or "").split())
    ingresso = ano_ingresso or ano_estagio - ANOS_ATE_ESTAGIO
    turma = next((t for t in Turma.objects.filter(curso=curso, ano_ingresso=ingresso) if t.nome.lower() == nome.lower()),
                 None)
    return turma or Turma.objects.create(curso=curso, nome=nome, ano_ingresso=ingresso, ano_estagio=ano_estagio)


# ---------------------------------------------------------------- supervisor do estágio


def trocar_supervisor(estagio, novo, feita_por, motivo=""):
    """Põe outro supervisor no estágio (o anterior só sai assim). Registra o histórico e avisa os envolvidos."""
    from django.urls import reverse

    from .models import TrocaSupervisor

    anterior = estagio.supervisor
    if novo is None:
        raise ValueError("O supervisor só pode ser trocado por outro.")
    if anterior and anterior.pk == novo.pk:
        return None
    if estagio.local_id and not novo.concedentes.filter(pk=estagio.local_id).exists():
        raise ValueError(f"{novo} não é supervisor(a) de {estagio.local}.")
    estagio.supervisor = novo
    estagio.save(update_fields=["supervisor"])
    troca = TrocaSupervisor.objects.create(estagio=estagio, anterior=anterior, novo=novo, motivo=motivo,
                                           feita_por=feita_por)
    link = reverse("estagio_detalhe", args=[estagio.pk])
    notificar([novo], f"{estagio.estagiario} agora está sob a sua supervisão.", link, exceto=feita_por)
    if anterior:
        notificar([anterior], f"{estagio.estagiario} passou a ser supervisionado(a) por {novo}.", "", exceto=feita_por)
    notificar([estagio.estagiario], f"Seu supervisor de estágio agora é {novo}.", link, exceto=feita_por)
    return troca


# ---------------------------------------------------------------- notificações


def notificar(usuarios, texto, link="", exceto=None, detalhe="", email=True):
    """Aviso no sino de cada pessoa, no celular (se ela ativou) e, se estiver configurado, também por e-mail.

    `detalhe`: texto completo que vai só no e-mail (o sino e o celular mostram o resumo).
    `email=False`: só sino e celular (lembretes do dia a dia, que no e-mail chegariam tarde demais)."""
    vistos = set()
    objs, destinatarios = [], []
    for u in usuarios:
        if not u or u.pk in vistos or (exceto and u.pk == exceto.pk):
            continue
        vistos.add(u.pk)
        objs.append(Notificacao(usuario=u, texto=texto[:255], link=link))
        if email and u.email and u.is_active and u.avisos_email:
            destinatarios.append(u)
    Notificacao.objects.bulk_create(objs)
    if destinatarios and email_ativo():
        mensagens = [mensagem_aviso(u, texto, link, detalhe) for u in destinatarios]
        transaction.on_commit(lambda: enviar_emails(mensagens))
    if objs:
        from . import push

        transaction.on_commit(lambda: push.enviar(objs))


def email_ativo():
    from django.conf import settings

    from .models import Configuracao

    return settings.EMAIL_ATIVO and Configuracao.atual().avisos_email


def mensagem_aviso(usuario, texto, link="", detalhe=""):
    """(assunto, corpo, remetente, [destinatário]) no formato de send_mass_mail."""
    from django.conf import settings

    site = settings.SITE_URL
    corpo = [f"Olá, {usuario.primeiro_nome}.", "", texto] + (["", detalhe] if detalhe else [])
    if link and site:
        corpo += ["", f"Abrir no sistema: {site}{link}"]
    corpo += ["", "—", f"Aviso automático do {settings.NOME_SISTEMA}. Não responda este e-mail."]
    if site:
        corpo.append(f"Para não receber avisos por e-mail, desmarque a opção em Meus dados: {site}/perfil/")
    assunto = f"[{settings.NOME_SISTEMA}] {texto[:90]}{'…' if len(texto) > 90 else ''}"
    return (assunto.replace("\n", " "), "\n".join(corpo), settings.DEFAULT_FROM_EMAIL, [usuario.email])


def enviar_emails(mensagens):
    """Envia numa conexão só. Em produção roda em segundo plano: uma falha no e-mail nunca derruba a página."""
    import logging
    import threading

    from django.conf import settings
    from django.core.mail import send_mass_mail

    def enviar():
        try:
            send_mass_mail(mensagens, fail_silently=False)
        except Exception:  # noqa: BLE001 — servidor de e-mail fora do ar não pode quebrar o sistema
            logging.getLogger("core.email").exception("Falha ao enviar %d e-mail(s) de aviso", len(mensagens))

    if settings.EMAIL_ASSINCRONO:
        threading.Thread(target=enviar, daemon=True).start()
    else:
        enviar()


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
    def horarios(self):
        """(preenchidos, esperados) dos horários do dia: entrada, saída e, se houver, as duas do intervalo."""
        r = self.registro
        if not r or r.situacao != Registro.Situacao.PRESENTE:
            return (0, 0)
        intervalo = bool((self.escala and self.escala.tem_intervalo) or r.saida_intervalo or r.volta_intervalo)
        campos = ([r.hora_chegada, r.saida_intervalo, r.volta_intervalo, r.hora_saida] if intervalo
                  else [r.hora_chegada, r.hora_saida])
        return (sum(1 for c in campos if c), len(campos))

    @property
    def nivel(self):
        """0, 25, 50, 75 ou 100: o “nível de água” do dia no calendário. Presença lançada só com as horas
        (sem horário nenhum) conta como completa."""
        feitos, total = self.horarios
        if not total or not feitos:
            return 100
        return feitos * 100 // total // 25 * 25

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


# ---------------------------------------------------------------- carga em lote (listas de estágios)


def preparar_lote(estagios, desde, totais=True):
    """Para listas (painel, lista de estagiários, relatórios): carrega de uma vez o que status_periodo,
    resumo_horas e simular_termino consultariam estágio por estágio — escalas, registros e dias planejados a
    partir de `desde`, feriados e os totais de horas. Fica guardado nos próprios objetos; quem não passa por
    aqui continua consultando do jeito normal. `desde` precisa ser <= hoje para a previsão de término usar o lote."""
    from .models import DiaPlanejado, Escala, LocalEstagio

    estagios = list(estagios)
    if not estagios:
        return estagios
    ids = [e.pk for e in estagios]
    sem_local = [e for e in estagios if e.local_id and "local" not in e._state.fields_cache]
    if sem_local:
        locais = LocalEstagio.objects.in_bulk({e.local_id for e in sem_local})
        for e in sem_local:
            e.local = locais.get(e.local_id)
    escalas, registros, planos = {}, {}, {}
    if all("escalas" in getattr(e, "_prefetched_objects_cache", {}) for e in estagios):
        escalas = {e.pk: list(e.escalas.all()) for e in estagios}
    else:
        for esc in Escala.objects.filter(estagio_id__in=ids):
            escalas.setdefault(esc.estagio_id, []).append(esc)
    for r in Registro.objects.filter(estagio_id__in=ids, data__gte=desde):
        registros.setdefault(r.estagio_id, {})[r.data] = r
    for p in DiaPlanejado.objects.filter(estagio_id__in=ids, data__gte=desde):
        planos.setdefault(p.estagio_id, {})[p.data] = p
    feriados = list(DiaSemEstagio.objects.filter(Q(anual=True) | Q(data__gte=desde)))
    soma = {}
    if totais:
        soma = {t.pop("estagio_id"): t for t in Registro.objects.filter(estagio_id__in=ids)
                .values("estagio_id").annotate(**_totais())}
    vazio = {"confirmadas": None, "pendentes": None, "presencas": 0, "ausencias": 0, "faltas": 0}
    for e in estagios:
        e._escalas_cache = sorted(escalas.get(e.pk, []), key=lambda x: x.vigente_desde, reverse=True)
        e._lote = {"desde": desde, "registros": registros.get(e.pk, {}), "planos": planos.get(e.pk, {}),
                   "feriados": feriados}
        if totais:
            e._lote_totais = soma.get(e.pk, vazio)
    return estagios


def _lote(estagio, inicio):
    lote = getattr(estagio, "_lote", None)
    return lote if lote is not None and inicio >= lote["desde"] else None


def filtro_feriados_do_estagio(estagio):
    """Quais cadastros valem para o estágio: os da escola (do orientador dele), os nacionais/estaduais e os
    municipais do município da concedente."""
    A = DiaSemEstagio.Abrangencia
    filtro = (Q(abrangencia=A.ESCOLA, orientador_id=estagio.orientador_id)
              & (Q(curso__isnull=True) | Q(curso_id=estagio.curso_id))) | Q(abrangencia=A.TODOS)
    chave = chave_municipio(estagio.local.cidade) if estagio.local_id else ""
    if chave:
        filtro |= Q(abrangencia=A.MUNICIPIO, municipio_chave=chave)
    if estagio.local_id:
        filtro |= Q(abrangencia=A.CONCEDENTE, concedente_id=estagio.local_id)
    return filtro


def _feriado_vale(d, estagio, chave):
    """O mesmo critério de filtro_feriados_do_estagio, em Python (para a carga em lote)."""
    A = DiaSemEstagio.Abrangencia
    if d.abrangencia == A.TODOS:
        return True
    if d.abrangencia == A.ESCOLA:
        return d.orientador_id == estagio.orientador_id and d.curso_id in (None, estagio.curso_id)
    if d.abrangencia == A.MUNICIPIO:
        return bool(chave) and d.municipio_chave == chave
    if d.abrangencia == A.CONCEDENTE:
        return bool(estagio.local_id) and d.concedente_id == estagio.local_id
    return False


def dias_sem_estagio(estagio, inicio, fim):
    lote = _lote(estagio, inicio)
    if lote is not None:
        chave = chave_municipio(estagio.local.cidade) if estagio.local_id else ""
        qs = [d for d in lote["feriados"] if _feriado_vale(d, estagio, chave)
              and ((not d.anual and inicio <= d.data <= fim) or (d.anual and d.data <= fim))]
    else:
        qs = DiaSemEstagio.objects.filter(filtro_feriados_do_estagio(estagio)).filter(
            Q(anual=False, data__range=(inicio, fim)) | Q(anual=True, data__lte=fim))
    dias = {}
    # o municipal vem primeiro: em dia com dois cadastros, a folha mostra o nome do feriado da cidade
    A = DiaSemEstagio.Abrangencia
    ordem = {A.MUNICIPIO: 0, A.TODOS: 1, A.CONCEDENTE: 2, A.ESCOLA: 3}
    for d in sorted(qs, key=lambda d: (ordem.get(d.abrangencia, 3), d.pk)):
        for dia in d.ocorrencias(inicio, fim):
            dias.setdefault(dia, d.descricao)
    return dias


def cadastrar_dias(usuario, abrangencia, data, descricao, ate=None, municipio="", anual=False, curso=None,
                   origem="manual", concedente=None):
    """Cadastra um dia (ou um período) sem estágio sem duplicar. Devolve quantos dias novos foram criados."""
    A = DiaSemEstagio.Abrangencia
    municipio = (municipio or "").strip() if abrangencia == A.MUNICIPIO else ""
    chave = chave_municipio(municipio)
    if abrangencia != A.ESCOLA:
        curso = None
    if abrangencia != A.CONCEDENTE:
        concedente = None
    elif concedente is None:
        raise ValueError("Recesso de concedente sem concedente.")
    n, dia = 0, data
    while dia <= (ate or data):
        busca = {"data": dia, "abrangencia": abrangencia, "municipio_chave": chave, "curso": curso,
                 "concedente": concedente}
        if abrangencia == A.ESCOLA:
            busca["orientador"] = usuario
        _, criado = DiaSemEstagio.objects.get_or_create(**busca, defaults={
            "descricao": descricao[:120], "orientador": usuario, "municipio": municipio, "anual": anual,
            "origem": origem})
        n += criado
        dia += timedelta(days=1)
    return n


# ---------------------------------------------------------------- calendário de feriados


def pascoa(ano):
    """Domingo de Páscoa (algoritmo de Meeus/Jones/Butcher, calendário gregoriano)."""
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = (h + l - 7 * m + 114) % 31 + 1
    return date(ano, mes, dia)


def feriados_nacionais(ano):
    """Feriados nacionais e do Ceará, mais os pontos facultativos usuais. (data, nome, tipo, marcado por padrão)

    É uma sugestão: o orientador revisa a lista antes de cadastrar. Feriados municipais não entram aqui.
    """
    p = pascoa(ano)
    lista = [
        (date(ano, 1, 1), "Confraternização Universal", "nacional", True),
        (p - timedelta(days=48), "Carnaval", "ponto facultativo", False),
        (p - timedelta(days=47), "Carnaval", "ponto facultativo", False),
        (date(ano, 3, 19), "São José", "estadual (CE)", True),
        (date(ano, 3, 25), "Data Magna do Ceará", "estadual (CE)", True),
        (p - timedelta(days=2), "Paixão de Cristo", "nacional", True),
        (date(ano, 4, 21), "Tiradentes", "nacional", True),
        (date(ano, 5, 1), "Dia do Trabalho", "nacional", True),
        (p + timedelta(days=60), "Corpus Christi", "ponto facultativo", False),
        (date(ano, 9, 7), "Independência do Brasil", "nacional", True),
        (date(ano, 10, 12), "Nossa Senhora Aparecida", "nacional", True),
        (date(ano, 11, 2), "Finados", "nacional", True),
        (date(ano, 11, 15), "Proclamação da República", "nacional", True),
        (date(ano, 11, 20), "Consciência Negra", "nacional", True),
        (date(ano, 12, 25), "Natal", "nacional", True),
    ]
    return sorted(lista, key=lambda x: x[0])


def agrupar_periodos(dias):
    """Dias seguidos com a mesma descrição viram um período (02/02 a 06/02 — Recesso). `dias` ordenados por data."""
    periodos = []
    for d in dias:
        p = periodos[-1] if periodos else None
        if (p and not d.anual and not p["anual"] and d.descricao == p["descricao"] and d.concedente_id == p["concedente_id"]
                and (d.data - p["fim"]).days == 1):
            p["fim"] = d.data
            p["ids"].append(d.pk)
        else:
            periodos.append({"inicio": d.data, "fim": d.data, "descricao": d.descricao, "anual": d.anual,
                             "concedente_id": d.concedente_id, "ids": [d.pk], "origem": d.origem})
    for p in periodos:
        p["dias"] = (p["fim"] - p["inicio"]).days + 1
        p["ids_txt"] = ",".join(map(str, p["ids"]))
    return periodos


def pessoas_da_concedente(local):
    """Estagiários ativos da concedente, seus supervisores e orientadores (para avisar de um recesso)."""
    pessoas = []
    for e in Estagio.objects.filter(ativo=True, local=local).select_related("estagiario", "supervisor", "orientador"):
        pessoas += [e.estagiario, e.supervisor, e.orientador]
    return pessoas


def municipios_das_concedentes():
    """Municípios das concedentes ativas, com quantos estágios ativos há em cada um."""
    from .models import LocalEstagio

    grupos = {}
    for l in LocalEstagio.objects.filter(ativa=True).exclude(cidade=""):
        chave = chave_municipio(l.cidade)
        if not chave:
            continue
        g = grupos.setdefault(chave, {"chave": chave, "nome": l.cidade.strip(), "uf": l.uf or "", "locais": [], "estagios": 0})
        g["locais"].append(l)
        g["estagios"] += l.estagios.filter(ativo=True).count()
    return sorted(grupos.values(), key=lambda g: (-g["estagios"], g["chave"]))


def estagios_do_municipio(chave):
    from .models import LocalEstagio

    ids = [l.pk for l in LocalEstagio.objects.exclude(cidade="") if chave_municipio(l.cidade) == chave]
    return Estagio.objects.filter(ativo=True, local_id__in=ids).select_related("estagiario", "supervisor")


def status_periodo(estagio, inicio, fim, hoje=None, limite=None):
    """Status de cada dia entre inicio e fim.

    `limite` é o último dia de estágio (normalmente a previsão de término): depois dele os dias
    aparecem como fora do período. A data de término do termo não limita, porque o estágio só
    acaba quando a carga horária é cumprida.
    """
    from django.utils import timezone

    hoje = hoje or timezone.localdate()
    lote = _lote(estagio, inicio)
    if lote is not None:
        registros = {d: r for d, r in lote["registros"].items() if inicio <= d <= fim}
        planos = {d: p for d, p in lote["planos"].items() if inicio <= d <= fim}
    else:
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


def _totais():
    """Agregações de horas e contagens dos registros (numa consulta só; agrupada por estágio no lote)."""
    P, R = Registro.Situacao, Registro.Confirmacao
    return dict(
        confirmadas=Sum("horas", filter=Q(situacao=P.PRESENTE, confirmacao=R.CONFIRMADA)),
        pendentes=Sum("horas", filter=Q(situacao=P.PRESENTE, confirmacao=R.PENDENTE)),
        presencas=Count("pk", filter=Q(situacao=P.PRESENTE)),
        ausencias=Count("pk", filter=Q(situacao=P.AUSENCIA)),
        faltas=Count("pk", filter=Q(situacao=P.FALTA)),
    )


def resumo_horas(estagio):
    t = getattr(estagio, "_lote_totais", None)
    if t is None:
        t = estagio.registros.aggregate(**_totais())
    confirmadas, pendentes = t["confirmadas"] or Decimal(0), t["pendentes"] or Decimal(0)
    total = Decimal(estagio.carga_horaria_total)
    cumpridas = confirmadas + estagio.horas_anteriores
    faltam = max(total - cumpridas - pendentes, Decimal(0))
    pct = float(min(cumpridas / total * 100, 100)) if total else 0
    pct_pend = float(min(pendentes / total * 100, 100 - pct)) if total else 0
    contagem = {"presencas": t["presencas"], "ausencias": t["ausencias"], "faltas": t["faltas"]}
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
    lote = _lote(estagio, inicio)
    if lote is not None:
        ja_registrados = {d for d in lote["registros"] if d >= inicio}
        planos = {d: p.horas for d, p in lote["planos"].items() if d >= inicio}
    else:
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
    return esc.horas_por_dia if esc else None


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


def aprovar_candidatura(cand, usuario, destino="nova", criar_supervisor=False, parecer="", endereco="",
                        criar_responsavel=False):
    """Cadastra (ou atualiza) a concedente, cria o supervisor indicado (e, se pedido, o responsável pela concedente)
    e prepara o aviso para a concedente. O responsável fica em `cand._responsavel`."""
    from django.db import transaction
    from django.urls import reverse
    from django.utils import timezone

    from .models import CAMPOS_CONCEDENTE, AvisoExterno, LocalEstagio, Usuario

    with transaction.atomic():
        if destino == "nova":
            local = LocalEstagio.objects.create(**{c: getattr(cand, c) for c in CAMPOS_CONCEDENTE})
        else:
            local = LocalEstagio.objects.get(pk=destino)
            local.ativa = True  # concedente que volta a receber estagiários
            for campo in CAMPOS_CONCEDENTE:  # completa só o que estava vazio
                if not getattr(local, campo) and getattr(cand, campo):
                    setattr(local, campo, getattr(cand, campo))
            local.save()
        from .seguranca import chave_texto

        supervisor = None
        conta = cand.conta if cand.conta_id and cand.conta.is_active else None
        if criar_supervisor and cand.supervisor_nome:
            if conta and chave_texto(conta.nome_completo) == chave_texto(cand.supervisor_nome):
                supervisor = conta  # quem preencheu é o próprio supervisor: usa a conta que já existe
                conta.concedentes.add(local)
            else:
                supervisor = criar_usuario(cand.supervisor_nome, Usuario.Papel.SUPERVISOR, usuario, concedente=local,
                                           telefone=cand.supervisor_telefone, email=cand.supervisor_email,
                                           cargo=cand.supervisor_cargo)
        cand._responsavel = None
        cand._conta_vinculada = None
        if criar_responsavel and conta:  # a conta criada na candidatura vira responsável
            conta.concedentes.add(local)
            conta.concedentes_geridas.add(local)
            cand._conta_vinculada = conta
        elif criar_responsavel:
            if supervisor and chave_texto(supervisor.nome_completo) == chave_texto(cand.contato_nome):
                responsavel = supervisor
            else:
                responsavel = criar_usuario(cand.contato_nome, Usuario.Papel.SUPERVISOR, usuario, concedente=local,
                                            telefone=cand.contato_telefone, email=cand.contato_email,
                                            cargo=cand.contato_cargo)
            responsavel.concedentes_geridas.add(local)
            cand._responsavel = responsavel
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
        if cand._conta_vinculada:
            linhas += ["", f"A sua conta no sistema ({cand._conta_vinculada.username}) já foi ligada à concedente como "
                           "responsável: entre para cadastrar a equipe e acompanhar os estagiários"
                           f"{f' ({endereco})' if endereco else ''}."]
        if supervisor and supervisor != cand._conta_vinculada:
            linhas += ["", f"O(a) supervisor(a) {supervisor.nome_completo} já tem acesso ao sistema de acompanhamento "
                           f"de estágio{f' ({endereco})' if endereco else ''}, com o usuário {supervisor.username}. "
                           "A escola vai repassar um código de primeiro acesso, com o qual ele(a) cria a própria senha."]
        if cand._responsavel and cand._responsavel != supervisor:
            r = cand._responsavel
            linhas += ["", f"{r.nome_completo} também tem acesso, com o usuário {r.username}, como responsável pela "
                           "concedente: pode cadastrar a equipe e indicar quem confirma as presenças quando o supervisor "
                           "não estiver. O código de primeiro acesso será repassado pela escola."]
        linhas += ["", "Em breve entraremos em contato para combinar os próximos passos.",
                   f"{usuario.nome_completo} — {_nome_escola()}", f"Protocolo {cand.protocolo}"]
        aviso = AvisoExterno.objects.create(
            candidatura=cand, destinatario=cand.contato_nome, email=cand.contato_email or cand.representante_email,
            telefone=cand.contato_telefone, assunto=f"Cadastro de concedente aprovado — {_nome_escola()}",
            mensagem="\n".join(linhas), criado_por=usuario,
        )
        if conta:  # quem tem conta vê a decisão ao entrar (sino e e-mail)
            notificar([conta], f"O cadastro de {cand.nome} foi aprovado pela escola.", reverse("minha_candidatura",
                      args=[cand.pk]), detalhe="\n".join(linhas))
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
    if cand.conta_id and cand.conta.is_active:
        from django.urls import reverse

        notificar([cand.conta], f"A escola analisou o cadastro de {cand.nome}: não foi aprovado desta vez.",
                  reverse("minha_candidatura", args=[cand.pk]), detalhe=mensagem)
    return AvisoExterno.objects.create(
        candidatura=cand, destinatario=cand.contato_nome, email=cand.contato_email or cand.representante_email,
        telefone=cand.contato_telefone, assunto=f"Cadastro de concedente — {_nome_escola()}", mensagem=mensagem,
        criado_por=usuario,
    )


# ---------------------------------------------------------------- check-in com localização

def distancia_metros(lat1, lng1, lat2, lng2):
    """Distância em metros entre dois pontos (fórmula de haversine)."""
    from math import asin, cos, radians, sin, sqrt

    lat1, lng1, lat2, lng2 = map(lambda v: radians(float(v)), (lat1, lng1, lat2, lng2))
    a = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lng2 - lng1) / 2) ** 2
    return round(2 * 6371000 * asin(sqrt(a)))


def coordenadas_do_link(link):
    """Latitude e longitude de um link do Google Maps / OpenStreetMap, se o link trouxer as coordenadas."""
    import re

    padroes = [r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", r"@(-?\d+\.\d+),(-?\d+\.\d+)",
               r"[?&](?:q|query|ll|destination)=(-?\d+\.\d+)(?:,|%2C)\s*(-?\d+\.\d+)",
               r"mlat=(-?\d+\.\d+)&mlon=(-?\d+\.\d+)", r"^\s*(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)\s*$"]
    for p in padroes:
        m = re.search(p, link or "")
        if m:
            lat, lng = float(m.group(1)), float(m.group(2))
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return Decimal(f"{lat:.6f}"), Decimal(f"{lng:.6f}")
    return None


ERROS_GEO = {"negada": "permissão negada", "indisponivel": "GPS indisponível", "tempo": "demorou demais",
             "sem_suporte": "navegador sem localização"}


def ler_localizacao(post, local):
    """Localização enviada pelo celular junto com a marcação. Devolve o dict guardado no registro."""
    erro = post.get("geo_erro", "")
    try:
        lat, lng = float(post.get("geo_lat", "")), float(post.get("geo_lng", ""))
        precisao = round(float(post.get("geo_precisao") or 0))
    except ValueError:
        return {"erro": ERROS_GEO.get(erro, "não enviada")}
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return {"erro": "inválida"}
    geo = {"lat": round(lat, 6), "lng": round(lng, 6), "precisao": precisao, "distancia": None}
    if local and local.latitude is not None and local.longitude is not None:
        geo["distancia"] = distancia_metros(lat, lng, local.latitude, local.longitude)
        geo["raio"] = local.raio_checkin
    return geo


def conferir_localizacao(estagio, post, acao="marcar presença"):
    """(geo, mensagem de bloqueio). Bloqueia só no modo “exigir” e quando a concedente tem ponto no mapa."""
    from .models import Configuracao, descrever_geo

    modo = Configuracao.atual().checkin_localizacao
    if modo == Configuracao.Localizacao.DESLIGADO:
        return None, None
    geo = ler_localizacao(post, estagio.local)
    if modo == Configuracao.Localizacao.EXIGIR and estagio.local and estagio.local.latitude is not None:
        if geo.get("erro"):
            return geo, (f"Para {acao}, permita o acesso à localização do celular e tente de novo "
                         f"({geo['erro']}). Se não conseguir, peça ao supervisor para lançar o dia.")
        info = descrever_geo(geo, estagio.local)
        if info["longe"]:
            return geo, (f"Você parece estar {info['texto']} (limite: {estagio.local.raio_checkin} m). "
                         f"Só é possível {acao} no local do estágio. Se estiver lá, ative o GPS, "
                         "espere alguns segundos e tente de novo, ou peça ao supervisor para lançar o dia.")
    return geo, None


def frequencia_mensal(estagio):
    """Como a “Frequência Detalhada” do SICE: por mês, dias e horas validados e a carga acumulada (com %)."""
    from django.db.models import Count
    from django.db.models.functions import TruncMonth

    total = Decimal(estagio.carga_horaria_total)
    acumulado = Decimal(estagio.horas_anteriores or 0)
    meses = (estagio.registros.filter(situacao=Registro.Situacao.PRESENTE, confirmacao=Registro.Confirmacao.CONFIRMADA)
             .annotate(m=TruncMonth("data")).values("m").annotate(dias=Count("pk"), horas=Sum("horas")).order_by("m"))
    linhas = []
    for item in meses:
        acumulado += item["horas"] or 0
        m = item["m"].date() if hasattr(item["m"], "date") else item["m"]
        linhas.append({"mes": m, "dias": item["dias"], "horas": item["horas"] or Decimal(0), "acumulado": acumulado,
                       "pct": float(min(acumulado / total * 100, 100)) if total else 0})
    return linhas
