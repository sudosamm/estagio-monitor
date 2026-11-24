"""Termos de Uso, Aviso de Privacidade, aceite e “Baixar meus dados” (LGPD, art. 18)."""
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache

from .. import auditoria, termos
from ..models import Mensagem, RegistroAcao
from .base import destino_seguro


def privacidade(request):
    return render(request, "core/privacidade.html", termos.contexto())


def termos_de_uso(request):
    return render(request, "core/termos.html", termos.contexto())


@never_cache
@login_required
def aceitar_termos(request):
    if not termos.precisa_aceitar(request.user):
        return redirect(destino_seguro(request, "/"))
    erro = ""
    if request.method == "POST":
        if request.POST.get("aceito") == "1":
            termos.registrar_aceite(request.user, request)
            messages.success(request, "Obrigado! Você pode rever os textos quando quiser, no rodapé de qualquer página.")
            return redirect(destino_seguro(request, "/"))
        erro = "Para continuar, marque que leu e concorda."
    return render(request, "core/aceitar_termos.html", {**termos.contexto(), "erro": erro,
                                                         "proximo": request.GET.get("next", "")})


def _h(t):
    return t.strftime("%H:%M") if t else None


@login_required
def baixar_meus_dados(request):
    """Cópia dos dados pessoais da própria pessoa, em JSON (dá para abrir no navegador ou num editor de texto)."""
    u = request.user
    dados = {
        "gerado_em": timezone.localtime().isoformat(timespec="seconds"),
        "conta": {
            "nome_completo": u.nome_completo, "usuario": u.username, "perfil": u.get_papel_display(),
            "email": u.email, "email_confirmado_em": u.email_confirmado_em.isoformat() if u.email_confirmado_em else None,
            "telefone": u.telefone, "cpf": u.cpf, "data_nascimento": u.data_nascimento.isoformat() if u.data_nascimento else None,
            "matricula": u.matricula, "cargo": u.cargo, "foto": bool(u.foto), "conta_criada_em": u.date_joined.isoformat(),
            "ultimo_acesso": u.last_login.isoformat() if u.last_login else None,
            "verificacao_duas_etapas": bool(u.dois_fatores_ativo),
            "termos_aceitos": {"versao": u.termos_versao, "em": u.termos_aceitos_em.isoformat() if u.termos_aceitos_em else None},
            "concedentes": [str(c) for c in u.concedentes.all()],
            "perfil_profissional": {"sobre_mim": u.apresentacao, "habilidades": u.habilidades,
                                    "curriculo": bool(u.curriculo), "visivel_concedentes": u.perfil_visivel},
            "preferencias": {"avisos_email": u.avisos_email, "lembrete_expediente": u.lembrete_expediente,
                             "tema": u.tema},
        },
        "estagios": [],
        "mensagens_escritas": [
            {"em": m.criado_em.isoformat(timespec="seconds"), "estagio": m.estagio_id, "texto": m.texto}
            for m in Mensagem.objects.filter(autor=u).order_by("criado_em")
        ],
        "acessos_e_acoes": [
            {"quando": a.quando.isoformat(timespec="seconds"), "o_que": a.descricao, "ip": a.ip, "aparelho": a.aparelho}
            for a in RegistroAcao.objects.filter(usuario=u)[:500]
        ],
    }
    for e in u.estagios.select_related("curso", "turma", "local", "supervisor", "orientador"):
        dados["estagios"].append({
            "curso": str(e.curso), "turma": e.turma.rotulo if e.turma else None, "concedente": str(e.local or ""),
            "supervisor": str(e.supervisor or ""), "orientador": str(e.orientador), "inicio": e.data_inicio.isoformat(),
            "termino_previsto": e.data_fim.isoformat() if e.data_fim else None, "ativo": e.ativo,
            "registros": [
                {"data": r.data.isoformat(), "situacao": r.get_situacao_display(), "entrada": _h(r.hora_chegada),
                 "saida_intervalo": _h(r.saida_intervalo), "volta_intervalo": _h(r.volta_intervalo),
                 "saida": _h(r.hora_saida), "horas": str(r.horas), "confirmacao": r.get_confirmacao_display(),
                 "motivo": r.motivo, "como_foi_o_dia": r.diario, "localizacao_entrada": r.geo_entrada,
                 "localizacao_saida": r.geo_saida}
                for r in e.registros.order_by("data")
            ],
            "atestados": [{"enviado_em": j.criado_em.isoformat(timespec="seconds"), "tipo": j.get_tipo_display(),
                           "de": j.data_inicio.isoformat(), "ate": j.data_fim.isoformat(),
                           "situacao": j.get_status_display()}
                          for j in e.justificativas.all()],
        })
    auditoria.registrar(request, "DADOS", "Baixou uma cópia dos próprios dados")
    resposta = HttpResponse(json.dumps(dados, ensure_ascii=False, indent=2), content_type="application/json; charset=utf-8")
    resposta["Content-Disposition"] = f'attachment; filename="meus-dados-{u.username}.json"'
    resposta["Cache-Control"] = "no-store"
    return resposta
