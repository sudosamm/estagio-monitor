"""Tela de importação em massa (só administrador)."""
from datetime import date, time
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from escolas.pessoas import na_escola

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
        mudanca_desde=date.fromisoformat(dados["mudanca_desde"]) if dados.get("mudanca_desde") else None,
        dias_depois=dados.get("dias_depois") or None,
    )


def _iso(v):
    return v.isoformat() if v else ""


def _escala_tela(opcoes):
    """“Seg, Ter; a partir de 15/11: Segunda a sexta” — para conferir na prévia os dias usados nas linhas sem a coluna."""
    from ..models import Escala

    texto = Escala(dias=",".join(map(str, opcoes["dias"]))).dias_display
    if opcoes.get("mudanca_desde") and opcoes.get("dias_depois"):
        texto += (f"; a partir de {date.fromisoformat(opcoes['mudanca_desde']):%d/%m/%Y}: "
                  f"{Escala(dias=','.join(map(str, opcoes['dias_depois']))).dias_display}")
    return texto


@orientador_requerido
def importar_csv(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    if request.GET.get("modelo") == "xlsx":
        conteudo = gerar_modelo(
            cursos=Curso.objects.values_list("nome", flat=True),
            turmas=Turma.objects.filter(ativa=True).values_list("nome", flat=True),
            orientadores=na_escola(Usuario.objects.filter(papel=Usuario.Papel.ORIENTADOR, is_active=True)).values_list("username", flat=True),
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
                                  f"{len(resultado.supervisores_novos)} supervisor(es) novos"
                                  + (f"; {len(resultado.completados)} cadastro(s) completado(s)" if resultado.completados else "")
                                  + (f"; {resultado.presencas} presença(s) já cumprida(s) lançada(s)." if resultado.presencas else "."))
        from .orientador import folha_primeiro_acesso

        pendentes = [u for _, u, _ in resultado.completados if u.deve_trocar_senha]
        return folha_primeiro_acesso(request, resultado.estagiarios + resultado.supervisores_novos + pendentes,
                                     "Contas criadas pela importação")

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
                "mudanca_desde": _iso(d.get("mudanca_desde")), "dias_depois": sorted(d.get("dias_depois") or []),
            }
            resultado = importar(linhas, _opcoes_de(opcoes), request.user, confirmar=False,
                                 concedentes_extra=concedentes, supervisores_extra=supervisores)
            request.session[CHAVE_SESSAO] = {"linhas": linhas, "concedentes": concedentes, "supervisores": supervisores,
                                             "opcoes": opcoes, "nome": nome}
            return render(request, "core/importar.html", {"resultado": resultado, "nome_arquivo": d["arquivo"].name,
                                                          "escala_tela": _escala_tela(opcoes)})
    return render(request, "core/importar.html", {"form": form, "colunas": COLUNAS})
