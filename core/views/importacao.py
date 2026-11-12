"""Tela de importação em massa (só administrador)."""
from datetime import date, time
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from ..forms import ImportarCSVForm
from ..importacao import COLUNAS, ErroImportacao, Opcoes, importar, ler_csv, modelo_csv
from ..models import Curso, Turma, Usuario
from ..planilha import eh_planilha, gerar_modelo, ler_planilha
from .base import orientador_requerido

CHAVE_SESSAO = "importacao_csv"


def _opcoes_de(dados):
    return Opcoes(
        orientador=Usuario.objects.get(pk=dados["orientador"]), dias=dados["dias"],
        horas_por_dia=Decimal(dados["horas_por_dia"]) if dados.get("horas_por_dia") else None,
        entrada=time.fromisoformat(dados["entrada"]) if dados["entrada"] else None,
        saida_intervalo=time.fromisoformat(dados["saida_intervalo"]) if dados["saida_intervalo"] else None,
        volta_intervalo=time.fromisoformat(dados["volta_intervalo"]) if dados["volta_intervalo"] else None,
        saida=time.fromisoformat(dados["saida"]) if dados["saida"] else None,
        acompanhamento_desde=date.fromisoformat(dados["acompanhamento_desde"]) if dados["acompanhamento_desde"] else None,
        carga_cursos_novos=dados["carga_cursos_novos"], completar_concedentes=dados["completar_concedentes"],
    )


def _iso(v):
    return v.isoformat() if v else ""


@orientador_requerido
def importar_csv(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    if request.GET.get("modelo") == "xlsx":
        conteudo = gerar_modelo(
            cursos=Curso.objects.values_list("nome", flat=True),
            turmas=Turma.objects.filter(ativa=True).values_list("nome", flat=True),
            orientadores=Usuario.objects.filter(papel=Usuario.Papel.ORIENTADOR, is_active=True).values_list("username", flat=True),
        )
        resposta = HttpResponse(conteudo, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        resposta["Content-Disposition"] = 'attachment; filename="planilha-cadastro-estagio.xlsx"'
        return resposta
    if request.GET.get("modelo"):
        resposta = HttpResponse(modelo_csv(), content_type="text/csv; charset=utf-8")
        resposta["Content-Disposition"] = 'attachment; filename="modelo-importacao.csv"'
        return resposta

    etapa = request.POST.get("etapa")
    if etapa == "confirmar":
        guardado = request.session.get(CHAVE_SESSAO)
        if not guardado:
            messages.error(request, "A prévia expirou. Envie o arquivo de novo.")
            return redirect("importar_csv")
        linhas = [(n, d) for n, d in guardado["linhas"]]
        resultado = importar(linhas, _opcoes_de(guardado["opcoes"]), request.user, confirmar=True,
                             concedentes_extra=[(n, d) for n, d in guardado.get("concedentes", [])],
                             supervisores_extra=[(n, d) for n, d in guardado.get("supervisores", [])])
        if not resultado.confirmado:
            messages.error(request, "Os dados mudaram desde a prévia e surgiram erros. Confira abaixo.")
            return render(request, "core/importar.html", {"resultado": resultado, "nome_arquivo": guardado["nome"]})
        del request.session[CHAVE_SESSAO]
        messages.success(request, f"Importação concluída: {len(resultado.linhas_ok)} estágio(s), "
                                  f"{len(resultado.concedentes_novas)} concedente(s) e "
                                  f"{len(resultado.supervisores_novos)} supervisor(es) novos.")
        from django.conf import settings

        return render(request, "core/contas_criadas.html", {
            "usuarios": resultado.estagiarios + resultado.supervisores_novos, "titulo": "Contas criadas pela importação",
            "senha": settings.SENHA_PADRAO, "endereco": request.build_absolute_uri("/"),
        })

    form = ImportarCSVForm(request.POST or None, request.FILES or None, initial={
        "orientador": request.user if request.user.is_orientador else None,
        "acompanhamento_desde": timezone.localdate(), "dias": [0, 1, 2, 3, 4],
    })
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        conteudo, nome = d["arquivo"].read(), d["arquivo"].name
        concedentes, supervisores = [], []
        try:
            if eh_planilha(conteudo, nome):
                linhas, concedentes, supervisores = ler_planilha(conteudo)
            else:
                linhas = ler_csv(conteudo)
        except ErroImportacao as exc:
            form.add_error("arquivo", str(exc))
        else:
            opcoes = {
                "orientador": d["orientador"].pk, "dias": sorted(d["dias"]), "horas_por_dia": str(d["horas_por_dia"]) if d.get("horas_por_dia") else "",
                "entrada": _iso(d.get("horario_entrada")), "saida_intervalo": _iso(d.get("saida_intervalo")),
                "volta_intervalo": _iso(d.get("volta_intervalo")), "saida": _iso(d.get("horario_saida")),
                "acompanhamento_desde": _iso(d.get("acompanhamento_desde")),
                "carga_cursos_novos": d["carga_cursos_novos"], "completar_concedentes": d["completar_concedentes"],
            }
            resultado = importar(linhas, _opcoes_de(opcoes), request.user, confirmar=False,
                                 concedentes_extra=concedentes, supervisores_extra=supervisores)
            request.session[CHAVE_SESSAO] = {"linhas": linhas, "concedentes": concedentes, "supervisores": supervisores,
                                             "opcoes": opcoes, "nome": nome}
            return render(request, "core/importar.html", {"resultado": resultado, "nome_arquivo": d["arquivo"].name})
    return render(request, "core/importar.html", {"form": form, "colunas": COLUNAS})
