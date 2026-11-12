"""Relatórios: geral da turma (PDF), exportação da lista (PDF/planilha), resumo da semana e declaração de estágio."""
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from ..acompanhamento import (
    LIMITE_FALTAS, LIMITE_SEM_REGISTRO, com_contagens, consolidar, mensagem_resumo, resumo_semanal,
)
from ..exportacao import gerar_planilha
from ..models import Configuracao, Curso, LocalEstagio, Registro, Turma
from ..services import ano_em_uso, enviar_emails, estagios_visiveis, resumo_horas
from .base import eh_orientador_do, orientador_requerido, pegar_estagio
from .orientador import filtrar_lista


def _relatorio(request, qs, titulo, dados, voltar, nome):
    hoje = timezone.localdate()
    estagios = list(com_contagens(qs.select_related("turma__curso").prefetch_related("escalas"))
                    .order_by("-ativo", "estagiario__nome_completo"))
    linhas, atencao, tot = consolidar(estagios, hoje)
    agora = timezone.localtime()
    if request.GET.get("formato") == "xlsx":
        descricao = " · ".join(f"{r}: {v}" for r, v in dados)
        conteudo = gerar_planilha(linhas, tot, descricao, request.user.nome_completo, agora)
        resp = HttpResponse(conteudo, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        resp["Content-Disposition"] = f'attachment; filename="{nome}-{hoje:%Y-%m-%d}.xlsx"'
        return resp
    return render(request, "core/relatorio_turma.html", {
        "titulo": titulo, "dados": dados, "voltar": voltar, "nome": nome,
        "linhas": linhas, "atencao": atencao, "tot": tot, "varias_turmas": len({e.turma_id for e in estagios}) > 1, "hoje": hoje, "agora": agora,
        "config": Configuracao.atual(), "limite_faltas": LIMITE_FALTAS, "limite_sem_registro": LIMITE_SEM_REGISTRO,
        "xlsx": f"{request.path}?{_sem_formato(request)}&formato=xlsx".replace("?&", "?"),
    })


def _sem_formato(request):
    q = request.GET.copy()
    q.pop("formato", None)
    q.pop("imprimir", None)
    return q.urlencode()


def _orientacao(qs):
    nomes = sorted(set(qs.values_list("orientador__nome_completo", flat=True)))
    return ", ".join(nomes) or "—"


@orientador_requerido
def relatorio_turma(request, pk):
    turma = get_object_or_404(Turma.objects.select_related("curso"), pk=pk)
    if request.user.is_coordenador and not request.user.coordena(turma.curso_id):
        raise PermissionDenied
    qs = estagios_visiveis(request.user).filter(turma=turma)
    cfg = Configuracao.atual()
    dados = [("Curso", turma.curso.nome),
             ("Turma", f"{turma.nome or '—'} (ingresso {turma.ano_ingresso}, estágio em {turma.ano_estagio})")]
    if cfg.nome_escola:
        dados.append(("Escola", cfg.nome_escola + (f" — {cfg.municipio_escola}" if cfg.municipio_escola else "")))
    dados += [("Orientação", _orientacao(qs)), ("Carga horária do curso", f"{turma.curso.carga_horaria} h")]
    return _relatorio(request, qs, (turma.nome or turma.curso.nome).upper(), dados, reverse("turmas"),
                      f"relatorio-{(turma.nome or turma.curso.nome)}-{turma.ano_ingresso}".replace(" ", "-").lower())


@orientador_requerido
def exportar_estagios(request):
    """Exporta exatamente o que a lista de estagiários está mostrando (mesmos filtros)."""
    ano = ano_em_uso(request)
    qs, f = filtrar_lista(request, ano)
    dados, partes = [], []
    if f["turma"].isdigit():
        turma = Turma.objects.select_related("curso").filter(pk=f["turma"]).first()
        if turma:
            dados.append(("Turma", turma.rotulo))
            partes.append(turma.nome or turma.curso.nome)
    if f["curso"].isdigit():
        curso = Curso.objects.filter(pk=f["curso"]).first()
        if curso:
            dados.append(("Curso", curso.nome))
            partes.append(curso.nome)
    if f["local"].isdigit():
        local = LocalEstagio.objects.filter(pk=f["local"]).first()
        if local:
            dados.append(("Concedente", local.nome))
            partes.append(local.nome)
    if f["q"]:
        dados.append(("Busca", f["q"]))
    dados.append(("Ano do estágio", str(ano) if ano else "todos"))
    dados.append(("Situação", {"inativos": "encerrados", "todos": "ativos e encerrados"}.get(f["situacao"], "ativos")))
    cfg = Configuracao.atual()
    if cfg.nome_escola:
        dados.append(("Escola", cfg.nome_escola))
    dados.append(("Orientação", _orientacao(qs)))
    titulo = " · ".join(partes).upper() or "ESTAGIÁRIOS"
    voltar = reverse("estagios_lista") + "?" + _sem_formato(request)
    nome = "estagiarios" + ("-" + "-".join(partes) if partes else "") + (f"-{ano}" if ano else "")
    return _relatorio(request, qs, titulo, dados, voltar, nome.replace(" ", "-").lower())


# ---------------------------------------------------------------- resumo da semana


@orientador_requerido
def resumo_semanal_view(request):
    dados = resumo_semanal(request.user)
    pode_enviar = bool(settings.EMAIL_ATIVO and request.user.email)
    if request.method == "POST" and request.POST.get("acao") == "enviar":
        if not pode_enviar:
            messages.error(request, "Para receber por e-mail, cadastre seu e-mail em Meus dados e configure o servidor de e-mail.")
        else:
            enviar_emails([mensagem_resumo(request.user, dados)])
            messages.success(request, f"Resumo enviado para {request.user.email}.")
        return redirect("resumo_semanal")
    return render(request, "core/resumo_semanal.html", {
        "d": dados, "s": dados["secoes"], "pode_enviar": pode_enviar, "config": Configuracao.atual(),
    })


# ---------------------------------------------------------------- declaração


@orientador_requerido
def declaracao_estagio(request, pk):
    """Declaração de conclusão (carga cumprida) ou de estágio em andamento, pronta para imprimir e assinar."""
    estagio = pegar_estagio(request, pk)
    if not eh_orientador_do(request.user, estagio):
        raise PermissionDenied
    r = resumo_horas(estagio)
    if not r["cumpridas"]:
        messages.error(request, "Ainda não há horas validadas para declarar.")
        return redirect(estagio)
    concluido = r["pct"] >= 100
    ultimo = (estagio.registros.filter(situacao=Registro.Situacao.PRESENTE, confirmacao=Registro.Confirmacao.CONFIRMADA)
              .order_by("-data").values_list("data", flat=True).first())
    from ..pasta import pasta_do_estagio

    return render(request, "core/declaracao.html", {
        "docs_faltando": [i for i in pasta_do_estagio(estagio) if i.tipo.obrigatorio and i.codigo != "conferido"],
        "e": estagio, "r": r, "concluido": concluido, "encerrado": not estagio.ativo or concluido,
        "ultimo_dia": ultimo, "hoje": timezone.localdate(), "config": Configuracao.atual(),
    })
