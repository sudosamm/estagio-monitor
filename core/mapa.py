"""Mapa dos estágios: a situação do dia em cada concedente (quem está no local, quem não chegou, faltas) e o que o
estagiário informou sobre o supervisor. Só concedentes; a posição do celular dos estagiários nunca vai para o mapa."""
from datetime import time

from django.db.models import Max
from django.urls import reverse
from django.utils import timezone

from .models import Agendamento
from .services import preparar_lote, status_periodo

# ordem de gravidade da cor do alfinete
CORES = ("vermelho", "ambar", "verde", "cinza")


def _item(e, st, dia, hoje):
    """Situação de um estagiário no dia: {nome, codigo, texto, local (localização conferida?), aguardando}."""
    reg = st.registro
    cod = st.codigo
    item = {"nome": e.estagiario.nome_completo, "url": e.get_absolute_url(), "local_ok": None, "aguardando": False}
    if reg and reg.situacao == reg.Situacao.PRESENTE and cod != "contestado":
        item["aguardando"] = cod == "aguardando"
        if reg.hora_chegada and not reg.hora_saida and dia == hoje:
            item.update(codigo="no_local", texto=f"no local desde {reg.hora_chegada:%H:%M}")
        elif reg.hora_chegada and reg.hora_saida:
            item.update(codigo="saiu", texto=f"esteve das {reg.hora_chegada:%H:%M} às {reg.hora_saida:%H:%M}")
        else:
            item.update(codigo="presente", texto="presença lançada")
        geo = reg.local_entrada
        if geo and geo["longe"] is not None:
            item["local_ok"] = not geo["longe"]
            if geo["longe"]:
                item["texto"] += f" · marcou {geo['texto']}"
    elif cod in ("ausencia", "ausencia_ok"):
        item.update(codigo="ausencia", texto="ausência justificada" if cod == "ausencia_ok" else "ausência informada")
    elif cod in ("falta", "contestado"):
        item.update(codigo="falta", texto="falta" if cod == "falta" else "presença contestada pelo supervisor")
    elif cod == "sem_registro":
        item.update(codigo="falta", texto="sem registro")
    elif cod == "hoje":
        esc = st.escala
        entrada = f" (entrada {esc.horario_entrada:%H:%M})" if esc and esc.horario_entrada else ""
        item.update(codigo="nao_chegou", texto=f"ainda não marcou presença{entrada}")
    elif cod == "previsto":
        item.update(codigo="previsto", texto="dia de estágio")
    else:
        return None  # sem estágio neste dia
    return item


def _supervisor(registros):
    """O que os estagiários informaram ao marcar a entrada (ou o QR code do supervisor, que conta como presente)."""
    sim = [r for r in registros if r.supervisor_presente is True]
    nao = [r for r in registros if r.supervisor_presente is False]
    if sim:
        r = min(sim, key=lambda x: x.hora_chegada or time.max)
        quando = f" às {r.hora_chegada:%H:%M}" if r.hora_chegada else ""
        return {"presente": True, "texto": f"presente (informado por {r.estagio.estagiario.primeiro_nome}{quando})"}
    if nao:
        nomes = ", ".join(sorted({r.estagio.estagiario.primeiro_nome for r in nao}))
        return {"presente": False, "texto": f"não estava no local (informado por {nomes})"}
    return {"presente": None, "texto": "sem informação"}


def situacao(estagios, dia):
    """Uma entrada por concedente com estagiário ativo (das que o usuário pode ver), com coordenadas ou não."""
    hoje = timezone.localdate()
    estagios = preparar_lote(list(estagios), min(dia, hoje), totais=False)
    ultima = dict(Agendamento.objects.filter(estagios__in=estagios, tipo=Agendamento.Tipo.VISITA,
                                             status=Agendamento.Status.REALIZADO)
                  .values_list("estagios").annotate(u=Max("data_hora")))
    marcadas = {}
    for ag in Agendamento.objects.filter(data_hora__date=dia, status=Agendamento.Status.AGENDADO).prefetch_related("estagios"):
        for e in ag.estagios.all():
            marcadas[e.pk] = timezone.localtime(ag.data_hora).strftime("%H:%M")
    locais = {}
    for e in estagios:
        loc = e.local
        p = locais.setdefault(loc.pk, {
            "id": loc.pk, "nome": loc.nome, "endereco": loc.endereco_completo or "", "cidade": (loc.cidade or "").strip(),
            "lat": float(loc.latitude) if loc.latitude is not None else None,
            "lng": float(loc.longitude) if loc.longitude is not None else None,
            "url": reverse("local_editar", args=[loc.pk]), "estagiarios": [], "ultima": None, "visita": "",
            "_registros": [],
        })
        st = status_periodo(e, dia, dia, limite=None)[0]
        item = _item(e, st, dia, hoje)
        if item:
            p["estagiarios"].append(item)
        if st.registro and st.registro.situacao == st.registro.Situacao.PRESENTE:
            p["_registros"].append(st.registro)
        u = ultima.get(e.pk)
        if u and (p["ultima"] is None or u > p["ultima"]):
            p["ultima"] = u
        if e.pk in marcadas:
            p["visita"] = marcadas[e.pk]
    resultado = []
    for p in locais.values():
        itens = p["estagiarios"]
        n = {c: sum(1 for i in itens if i["codigo"] == c) for c in
             ("no_local", "saiu", "presente", "nao_chegou", "ausencia", "falta", "previsto")}
        presentes = n["no_local"] + n["saiu"] + n["presente"]
        if n["falta"]:
            cor = "vermelho"
        elif n["nao_chegou"]:
            cor = "ambar"
        elif presentes:
            cor = "verde"
        else:
            cor = "cinza"
        p.update(
            cor=cor, contagem=n, presentes=presentes, total=len(itens),
            aguardando=sum(1 for i in itens if i["aguardando"]),
            conferidos=sum(1 for i in itens if i["local_ok"]),
            supervisor=_supervisor(p.pop("_registros")),
            dias_sem_visita=(hoje - timezone.localtime(p["ultima"]).date()).days if p["ultima"] else None,
        )
        p.pop("ultima")
        itens.sort(key=lambda i: (["falta", "nao_chegou", "no_local", "saiu", "presente", "ausencia", "previsto"]
                                  .index(i["codigo"]), i["nome"]))
        resultado.append(p)
    resultado.sort(key=lambda p: (CORES.index(p["cor"]), p["nome"]))
    return resultado


def resumo(locais):
    soma = {c: 0 for c in ("no_local", "saiu", "presente", "nao_chegou", "ausencia", "falta")}
    for p in locais:
        for c in soma:
            soma[c] += p["contagem"][c]
    soma["presentes"] = soma["no_local"] + soma["saiu"] + soma["presente"]
    soma["aguardando"] = sum(p["aguardando"] for p in locais)
    return soma
