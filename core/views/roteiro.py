"""Roteiro de visitas do orientador e busca rápida da gestão."""
import math
from datetime import date, datetime, time, timedelta

from django.contrib import messages
from django.db import transaction
from django.db.models import Max
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import Agendamento, LocalEstagio, Usuario
from ..seguranca import chave_texto
from ..services import estagios_visiveis, notificar, preparar_lote, status_periodo
from .base import orientador_requerido, permissao


def _dia_param(request):
    try:
        return date.fromisoformat(request.GET.get("data", ""))
    except ValueError:
        hoje = timezone.localdate()
        return hoje + timedelta(days={5: 2, 6: 1}.get(hoje.weekday(), 0))  # fim de semana: próxima segunda


def _distancia(a, b):
    """Aproximação em km entre (lat, lng) — basta para ordenar paradas próximas."""
    x = math.radians(b[1] - a[1]) * math.cos(math.radians((a[0] + b[0]) / 2))
    y = math.radians(b[0] - a[0])
    return 6371 * math.hypot(x, y)


def _ordenar(paradas):
    """Com coordenadas: vizinho mais próximo a partir da primeira (por cidade e bairro). Sem: cidade, bairro, nome."""
    paradas.sort(key=lambda p: (chave_texto(p["local"].cidade), chave_texto(p["local"].bairro), chave_texto(p["local"].nome)))
    com = [p for p in paradas if p["coord"]]
    sem = [p for p in paradas if not p["coord"]]
    if len(com) < 3:
        return paradas
    rota = [com.pop(0)]
    while com:
        prox = min(com, key=lambda p: _distancia(rota[-1]["coord"], p["coord"]))
        com.remove(prox)
        rota.append(prox)
    return rota + sem


def _destino_mapa(local):
    if local.latitude is not None and local.longitude is not None:
        return f"{local.latitude},{local.longitude}"
    partes = [local.endereco, local.numero, local.bairro, local.cidade, local.uf]
    return ", ".join(p for p in partes if p) or local.nome


def paradas_do_dia(user, dia):
    """Concedentes com estagiário (visível ao usuário) no local em `dia`, com horário, última visita e visita já
    marcada. Sem ordem definida."""
    estagios = preparar_lote(estagios_visiveis(user).filter(ativo=True, local__isnull=False)
                             .select_related("estagiario", "local", "supervisor"), min(dia, timezone.localdate()),
                             totais=False)
    ultima = dict(Agendamento.objects.filter(estagios__in=estagios, tipo=Agendamento.Tipo.VISITA,
                                             status=Agendamento.Status.REALIZADO)
                  .values_list("estagios").annotate(u=Max("data_hora")))
    marcadas = {}
    for ag in (Agendamento.objects.filter(data_hora__date=dia, status=Agendamento.Status.AGENDADO)
               .prefetch_related("estagios").select_related("local")):
        for e in ag.estagios.all():
            marcadas[e.pk] = ag
    por_local = {}
    for e in estagios:
        st = status_periodo(e, dia, dia, limite=None)[0]
        if not st.previsto or (st.registro and st.registro.situacao != st.registro.Situacao.PRESENTE):
            continue
        esc = st.escala
        p = por_local.setdefault(e.local_id, {"local": e.local, "estagios": [], "inicio": None, "fim": None,
                                              "ultima": None, "agendada": None})
        p["estagios"].append(e)
        e.horario_dia = esc.horario_display if esc else ""
        if esc and esc.horario_entrada:
            p["inicio"] = min(filter(None, [p["inicio"], esc.horario_entrada]))
        if esc and esc.horario_saida:
            p["fim"] = max(filter(None, [p["fim"], esc.horario_saida]))
        u = ultima.get(e.pk)
        if u and (p["ultima"] is None or u > p["ultima"]):
            p["ultima"] = u
        if e.pk in marcadas:
            p["agendada"] = marcadas[e.pk]
    paradas = list(por_local.values())
    hoje = timezone.localdate()
    for p in paradas:
        loc = p["local"]
        p["coord"] = (float(loc.latitude), float(loc.longitude)) if loc.latitude is not None and loc.longitude is not None else None
        p["destino"] = _destino_mapa(loc)
        p["cidade"] = (loc.cidade or "").strip()
        p["dias_sem_visita"] = (hoje - timezone.localtime(p["ultima"]).date()).days if p["ultima"] else None
        ids = ",".join(str(e.pk) for e in p["estagios"])
        hora = p["inicio"].strftime("%H:%M") if p["inicio"] else ""
        p["agendar"] = f"{reverse('novo_agendamento')}?data={dia.isoformat()}&estagios={ids}" + (f"&hora={hora}" if hora else "")
    return paradas


def _cidades(paradas):
    contagem = {}
    for p in paradas:
        if p["cidade"]:
            contagem[p["cidade"]] = contagem.get(p["cidade"], 0) + 1
    return sorted(contagem.items(), key=lambda c: chave_texto(c[0]))


@permissao("agenda")
def roteiro(request):
    dia = _dia_param(request)
    todas = paradas_do_dia(request.user, dia)
    cidade = request.GET.get("cidade", "").strip()
    paradas = [p for p in todas if chave_texto(p["cidade"]) == chave_texto(cidade)] if cidade else todas
    paradas = _ordenar(paradas)
    sugeridas = 0
    for p in paradas:  # já marcadas para o mapa: as que nunca tiveram visita ou estão há mais de 30 dias sem
        p["sugerida"] = not p["agendada"] and (bool(cidade) or (sugeridas < 6 and (
            p["dias_sem_visita"] is None or p["dias_sem_visita"] > 30)))
        sugeridas += p["sugerida"]
    return render(request, "core/roteiro.html", {
        "dia": dia, "paradas": paradas, "anterior": (dia - timedelta(days=1)).isoformat(),
        "proximo": (dia + timedelta(days=1)).isoformat(), "total": sum(len(p["estagios"]) for p in paradas),
        "sem_visita": sum(1 for p in paradas if p["dias_sem_visita"] is None),
        "cidades": _cidades(todas), "cidade": cidade, "hoje": timezone.localdate(),
        "rapido": {"inicio": "08:00", "duracao": 45, "deslocamento": 20},
    })


# ---------------------------------------------------------------- agendamento rápido

ALMOCO = (time(12, 0), time(13, 0))  # sem visitas nesse intervalo
LIMITE_DIA = time(18, 0)


def _ordem_da_agenda(paradas):
    """Manhã antes da tarde (pelo horário dos estagiários) e, em cada turno, a rota de vizinho mais próximo."""
    manha = [p for p in paradas if not p["inicio"] or p["inicio"] < ALMOCO[0]]
    tarde = [p for p in paradas if p["inicio"] and p["inicio"] >= ALMOCO[0]]
    return _ordenar(manha) + _ordenar(tarde)


def _deslocamento(a, b, minimo):
    """Minutos entre duas paradas: o escolhido pelo orientador ou, com as duas localizações, a estimativa pela
    distância em linha reta (30 km/h na cidade + 5 min para estacionar), o que for maior."""
    if a and b and a["coord"] and b["coord"]:
        estimado = _distancia(a["coord"], b["coord"]) / 30 * 60 * 1.3 + 5
        return max(minimo, int(math.ceil(estimado / 5) * 5))
    return minimo


def planejar(paradas, dia, inicio, duracao, deslocamento, ocupados=(), agora=None):
    """Horário de cada visita, na ordem da rota: começa em `inicio`, espera o estagiário chegar, pula o almoço
    (12h–13h) e os compromissos já marcados. Devolve [{parada, inicio, fim, deslocamento, avisos}]."""
    tz = timezone.get_current_timezone()

    def momento(h):
        return timezone.make_aware(datetime.combine(dia, h), tz)

    cursor = momento(inicio)
    agora = timezone.localtime(agora or timezone.now())
    if dia == agora.date() and cursor < agora:  # hoje: a partir dos próximos 15 minutos
        cursor = momento(time(agora.hour)) + timedelta(minutes=(agora.minute // 15 + 1) * 15)
    almoco_ini, almoco_fim = momento(ALMOCO[0]), momento(ALMOCO[1])
    plano, anterior = [], None
    for p in _ordem_da_agenda(paradas):
        desloc = _deslocamento(anterior, p, deslocamento) if anterior else 0
        ini = cursor + timedelta(minutes=desloc)
        avisos = []
        if p["inicio"] and ini < momento(p["inicio"]):
            ini = momento(p["inicio"])  # espera o estagiário chegar
        for _ in range(50):
            fim = ini + timedelta(minutes=duracao)
            if ini < almoco_fim and fim > almoco_ini:
                ini = almoco_fim
                continue
            choque = next((o for o in ocupados if ini < o[1] and fim > o[0]), None)
            if choque:
                ini = choque[1]
                continue
            break
        if p["fim"] and fim > momento(p["fim"]):
            avisos.append(f"termina depois da saída do estagiário ({p['fim']:%H:%M})")
        if fim > momento(LIMITE_DIA):
            avisos.append("termina depois das 18h")
        if not p["local"].endereco_completo:
            avisos.append("concedente sem endereço no cadastro")
        plano.append({"parada": p, "inicio": ini, "fim": fim, "deslocamento": desloc, "avisos": avisos})
        cursor, anterior = fim, p
    return plano


def _numero(valor, padrao, minimo, maximo):
    try:
        return max(minimo, min(maximo, int(valor)))
    except (TypeError, ValueError):
        return padrao


@permissao("agenda")
@require_POST
def agendamento_rapido(request):
    """Roteiro → “Agendar as visitas marcadas”: mostra a agenda proposta e, confirmada, cria um agendamento por
    concedente (visita presencial) e avisa estagiários e supervisores."""
    user = request.user
    try:
        dia = date.fromisoformat(request.POST.get("data", ""))
    except ValueError:
        messages.error(request, "Dia inválido.")
        return redirect("roteiro")
    try:
        inicio = time.fromisoformat(request.POST.get("inicio", "08:00")[:5])
    except ValueError:
        inicio = time(8, 0)
    duracao = _numero(request.POST.get("duracao"), 45, 10, 240)
    deslocamento = _numero(request.POST.get("deslocamento"), 20, 0, 180)
    escolhidos = {int(i) for i in request.POST.getlist("locais") if i.isdigit()}
    paradas = [p for p in paradas_do_dia(user, dia) if p["local"].pk in escolhidos]
    ja_marcadas = [p for p in paradas if p["agendada"]]
    paradas = [p for p in paradas if not p["agendada"]]
    volta = f"{reverse('roteiro')}?data={dia.isoformat()}"
    if not paradas:
        messages.info(request, "Marque pelo menos uma concedente sem visita marcada neste dia.")
        return redirect(volta)
    if dia < timezone.localdate():
        messages.error(request, "Esse dia já passou.")
        return redirect(volta)
    ocupados = [(a.data_hora, a.fim) for a in Agendamento.objects.filter(
        orientador=user, status=Agendamento.Status.AGENDADO, data_hora__date=dia)]
    plano = planejar(paradas, dia, inicio, duracao, deslocamento, ocupados)
    if request.POST.get("acao") == "criar":
        criados = []
        with transaction.atomic():
            for n, item in enumerate(plano, 1):
                p = item["parada"]
                ag = Agendamento.objects.create(
                    tipo=Agendamento.Tipo.VISITA, modalidade=Agendamento.Modalidade.PRESENCIAL,
                    status=Agendamento.Status.AGENDADO, orientador=user, solicitante=user, local=p["local"],
                    data_hora=item["inicio"], duracao=duracao, assunto=f"Visita a {p['local'].nome}"[:160],
                    detalhes=f"Agendamento rápido: parada {n} de {len(plano)} do roteiro de {dia:%d/%m/%Y}.",
                )
                ag.estagios.set(p["estagios"])
                criados.append(ag)
        for ag in criados:
            quando = timezone.localtime(ag.data_hora).strftime("%d/%m às %H:%M")
            notificar(ag.envolvidos(), f"Visita agendada para {quando}: {ag.assunto}", ag.get_absolute_url(),
                      exceto=user)
        messages.success(request, f"{len(criados)} visita(s) agendada(s) para {dia:%d/%m} e estagiários e "
                                  "supervisores avisados.")
        return redirect(f"{reverse('agendamentos')}")
    paradas_mapa = [i["parada"]["destino"] for i in plano][:10]
    mapa = ""
    if paradas_mapa:
        from urllib.parse import urlencode

        dados = {"api": 1, "destination": paradas_mapa[-1], "travelmode": "driving"}
        if len(paradas_mapa) > 1:
            dados["waypoints"] = "|".join(paradas_mapa[:-1])
        mapa = "https://www.google.com/maps/dir/?" + urlencode(dados)
    return render(request, "core/agenda_rapida.html", {
        "dia": dia, "plano": plano, "inicio": inicio, "duracao": duracao, "deslocamento": deslocamento,
        "ja_marcadas": ja_marcadas, "mapa": mapa, "volta": volta, "ocupados": len(ocupados),
        "termina": plano[-1]["fim"] if plano else None,
    })


# ---------------------------------------------------------------- busca rápida (atalho “/” ou Ctrl+K)


def _bate(termo, *textos):
    """Todas as palavras digitadas aparecem (em qualquer ordem): “maria souza” acha “Maria da Silva Souza”."""
    alvo = " ".join(chave_texto(t) for t in textos if t)
    return all(p in alvo for p in termo.split())


@orientador_requerido
def buscar(request):
    termo = chave_texto(request.GET.get("q", ""))[:60]
    if len(termo) < 2:
        return JsonResponse({"grupos": []})
    user = request.user
    grupos = []
    estagiarios = []
    for e in estagios_visiveis(user).select_related("estagiario", "local", "turma").order_by("-ativo", "estagiario__nome_completo"):
        u = e.estagiario
        if _bate(termo, u.nome_completo, u.username, u.matricula):
            estagiarios.append({"titulo": u.nome_completo, "detalhe": " · ".join(filter(None, [
                str(e.local or ""), e.turma.rotulo if e.turma else "", "" if e.ativo else "encerrado"])),
                "url": e.get_absolute_url()})
        if len(estagiarios) >= 8:
            break
    if estagiarios:
        grupos.append({"nome": "Estagiários", "itens": estagiarios})
    if user.pode("cadastros"):
        locais = [{"titulo": l.nome, "detalhe": " · ".join(filter(None, [l.razao_social if l.razao_social != l.nome else "", l.cidade])),
                   "url": reverse("local_editar", args=[l.pk])}
                  for l in LocalEstagio.objects.order_by("-ativa", "nome") if _bate(termo, l.nome, l.razao_social, l.cnpj)][:6]
        if locais:
            grupos.append({"nome": "Concedentes", "itens": locais})
    if user.pode("contas"):
        contas = Usuario.objects.filter(is_active=True).exclude(papel=Usuario.Papel.ESTAGIARIO)
        if not user.is_superuser:  # contas da gestão só o administrador edita
            contas = contas.filter(papel=Usuario.Papel.SUPERVISOR)
        pessoas = [{"titulo": u.nome_completo, "detalhe": f"{u.get_papel_display()} · {u.username}" + (f" · {u.concedentes_txt}" if u.is_supervisor else ""),
                    "url": reverse("editar_usuario", args=[u.pk])}
                   for u in contas.prefetch_related("concedentes") if _bate(termo, u.nome_completo, u.username)][:6]
        if pessoas:
            grupos.append({"nome": "Supervisores e equipe", "itens": pessoas})
    from ..context_processors import menu_gestor
    from ..models import Configuracao

    menu = menu_gestor(user, "", Configuracao.atual())
    paginas = [{"titulo": i["rotulo"], "detalhe": s["rotulo"], "url": i["url"]}
               for s in [{"rotulo": "", "itens": menu["soltos"]}, *menu["secoes"]] for i in s["itens"]
               if _bate(termo, i["rotulo"])][:5]
    if paginas:
        grupos.append({"nome": "Páginas", "itens": paginas})
    return JsonResponse({"grupos": grupos})
