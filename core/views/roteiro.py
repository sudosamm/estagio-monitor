"""Roteiro de visitas do orientador e busca rápida da gestão."""
import math
from datetime import date, timedelta

from django.db.models import Max
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from ..models import Agendamento, LocalEstagio, Usuario
from ..seguranca import chave_texto
from ..services import estagios_visiveis, preparar_lote, status_periodo
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


@permissao("agenda")
def roteiro(request):
    user = request.user
    dia = _dia_param(request)
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
        p["dias_sem_visita"] = (hoje - timezone.localtime(p["ultima"]).date()).days if p["ultima"] else None
        ids = ",".join(str(e.pk) for e in p["estagios"])
        hora = p["inicio"].strftime("%H:%M") if p["inicio"] else ""
        p["agendar"] = f"{reverse('novo_agendamento')}?data={dia.isoformat()}&estagios={ids}" + (f"&hora={hora}" if hora else "")
    paradas = _ordenar(paradas)
    sugeridas = 0
    for p in paradas:  # já marcadas para o mapa: as que nunca tiveram visita ou estão há mais de 30 dias sem
        p["sugerida"] = (not p["agendada"] and sugeridas < 6
                         and (p["dias_sem_visita"] is None or p["dias_sem_visita"] > 30))
        sugeridas += p["sugerida"]
    return render(request, "core/roteiro.html", {
        "dia": dia, "paradas": paradas, "anterior": (dia - timedelta(days=1)).isoformat(),
        "proximo": (dia + timedelta(days=1)).isoformat(), "total": sum(len(p["estagios"]) for p in paradas),
        "sem_visita": sum(1 for p in paradas if p["dias_sem_visita"] is None),
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
