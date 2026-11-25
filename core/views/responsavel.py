"""Área do responsável legal: acompanha, só para ler, o estágio dos estudantes de quem é responsável."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import Agendamento, Configuracao, DIAS_ABREV
from ..responsaveis import estagios_do_responsavel, vinculos_de
from ..services import calendario_mes, limite_calendario, preparar_lote, resumo_horas, status_hoje
from .base import permissao


def _so_responsavel(user):
    if not user.is_responsavel:
        raise PermissionDenied


@login_required
def responsavel_inicio(request):
    _so_responsavel(request.user)
    estagios = list(estagios_do_responsavel(request.user).order_by("-ativo", "estagiario__nome_completo", "-data_inicio"))
    ativos = [e for e in estagios if e.ativo]
    if len(ativos) == 1 and len({e.estagiario_id for e in estagios}) == 1:
        return redirect("responsavel_estagio", pk=ativos[0].pk)
    hoje = timezone.localdate()
    preparar_lote(ativos, hoje, totais=True)
    for e in ativos:
        e.st = status_hoje(e)
        e.horas_resumo = resumo_horas(e)
    return render(request, "core/responsavel_inicio.html", {"estagios": estagios, "ativos": ativos})


@login_required
def responsavel_estagio(request, pk):
    from .estagio import _mes_param, _nav_mes

    _so_responsavel(request.user)
    estagio = estagios_do_responsavel(request.user).filter(pk=pk).first()
    if estagio is None:
        raise Http404
    ano, mes = _mes_param(request)
    from datetime import date

    preparar_lote([estagio], min(date(ano, mes, 1), timezone.localdate()))
    horas = resumo_horas(estagio)
    limite = limite_calendario(estagio, horas)
    visitas = Agendamento.objects.filter(estagios=estagio, data_hora__year=ano, data_hora__month=mes).exclude(
        status=Agendamento.Status.CANCELADO)
    vinculo = vinculos_de(estagio.estagiario).filter(responsavel=request.user).first()
    return render(request, "core/responsavel_estagio.html", {
        "estagio": estagio, "hoje": status_hoje(estagio) if estagio.ativo else None, "horas": horas,
        "escala_atual": estagio.escala_em(timezone.localdate()),
        "semanas": calendario_mes(estagio, ano, mes, limite), "nav": _nav_mes(ano, mes), "dias_semana": DIAS_ABREV,
        "dias_visita": {timezone.localtime(v.data_hora).date() for v in visitas if v.data_hora},
        "somente_leitura": True, "vinculo": vinculo, "config": Configuracao.atual(),
        "proximas_visitas": estagio.agendamentos.filter(status=Agendamento.Status.AGENDADO,
                                                        data_hora__gte=timezone.now()).order_by("data_hora")[:3],
        "avisos": request.user.comunicados_recebidos.select_related("autor")[:5],
        "outros": estagios_do_responsavel(request.user).exclude(pk=estagio.pk).filter(ativo=True).exists(),
    })


# ---------------------------------------------------------------- gestão: cadastro e acesso dos responsáveis


def _folha_responsaveis(request, linhas, titulo, voltar):
    from .orientador import _folha

    return _folha(request, linhas, titulo, "Mande a cada responsável só a linha dele (no papel ou pelo botão do WhatsApp).",
                  voltar=voltar)


@permissao("estagiarios")
@require_POST
def responsaveis_estagio(request, pk):
    """Na página do estágio (orientador, coordenador do curso, administrador): cadastrar o responsável, gerar o
    acesso e tirar o acesso."""
    from .. import auditoria
    from ..forms import ResponsavelForm
    from ..models import VinculoResponsavel
    from ..responsaveis import encerrar, vincular
    from ..seguranca import gerar_codigo, liberar_primeiro_acesso
    from .base import eh_orientador_do, pegar_estagio

    estagio = pegar_estagio(request, pk)
    if not eh_orientador_do(request.user, estagio):
        raise PermissionDenied
    aluno = estagio.estagiario
    voltar = estagio.get_absolute_url() + "#responsaveis"
    acao = request.POST.get("acao")
    if acao == "adicionar":
        form = ResponsavelForm(request.POST, prefix="resp")
        if not form.is_valid():
            for campo, erros in form.errors.items():
                messages.error(request, f"{form.fields[campo].label if campo in form.fields else ''}: {' '.join(erros)}".strip(": "))
            return redirect(voltar)
        d = form.cleaned_data
        resp, nova, _ = vincular(aluno, d["nome"], d["cpf"], d["telefone"], d["email"], d["parentesco"], d["origem"],
                                 request.user)
        auditoria.registrar(request, "GESTAO", f"Cadastrou {resp.nome_completo} como responsável de {aluno.nome_completo}",
                            alvo=estagio)
        if resp.deve_trocar_senha:
            return _folha_responsaveis(request, [(resp, gerar_codigo(resp))], f"Acesso de {resp.nome_completo}", voltar)
        messages.success(request, f"{resp.nome_completo} já tinha conta e agora acompanha também {aluno.primeiro_nome}.")
        return redirect(voltar)
    vinculo = VinculoResponsavel.objects.filter(pk=request.POST.get("id") or 0, estagiario=aluno).select_related(
        "responsavel").first()
    if vinculo is None:
        raise Http404
    resp = vinculo.responsavel
    if acao == "acesso":
        codigo = gerar_codigo(resp) if resp.deve_trocar_senha else liberar_primeiro_acesso(resp)
        if not resp.is_active:
            resp.is_active = True
            resp.save(update_fields=["is_active"])
        auditoria.registrar(request, "GESTAO", f"Gerou acesso do responsável {resp.nome_completo}", alvo=estagio)
        return _folha_responsaveis(request, [(resp, codigo)], f"Acesso de {resp.nome_completo}", voltar)
    if acao == "encerrar":
        encerrar(vinculo, request.user)
        auditoria.registrar(request, "GESTAO", f"Tirou o acesso de {resp.nome_completo} ao estágio de {aluno.nome_completo}",
                            alvo=estagio)
        messages.success(request, f"{resp.nome_completo} não acompanha mais o estágio de {aluno.primeiro_nome}.")
        return redirect(voltar)
    raise Http404


COLUNAS_RESPONSAVEIS = [
    ("estagiario_cpf", False, "CPF do estudante (ou use estagiario_nome)"),
    ("estagiario_nome", False, "Nome completo do estudante, como no sistema"),
    ("responsavel_nome", True, "Nome completo do responsável legal"),
    ("responsavel_cpf", False, "CPF do responsável"),
    ("responsavel_telefone", False, "Telefone / WhatsApp"),
    ("responsavel_email", False, "E-mail (opcional)"),
    ("parentesco", False, "mãe, pai, avó…"),
]
CHAVE_SESSAO = "importacao_responsaveis"


def _preparar(linhas, user):
    """Confere cada linha: acha o estudante (CPF ou nome) entre os visíveis e aplica as regras."""
    from ..responsaveis import maior_no_inicio
    from ..seguranca import chave_texto
    from ..services import estagios_visiveis
    from ..validators import cpf_valido, formatar_cpf

    alunos = {e.estagiario for e in estagios_visiveis(user).select_related("estagiario")}
    por_cpf = {a.cpf: a for a in alunos if a.cpf}
    por_nome = {}
    for a in alunos:
        por_nome.setdefault(chave_texto(a.nome_completo), []).append(a)
    ok, ignoradas, erros = [], [], []
    for n, d in linhas:
        cpf_aluno = d.get("estagiario_cpf", "")
        aluno = por_cpf.get(formatar_cpf(cpf_aluno)) if cpf_aluno and cpf_valido(cpf_aluno) else None
        if aluno is None and d.get("estagiario_nome"):
            achados = por_nome.get(chave_texto(d["estagiario_nome"]), [])
            aluno = achados[0] if len(achados) == 1 else None
        nome = " ".join(d.get("responsavel_nome", "").split())
        cpf = d.get("responsavel_cpf", "")
        if aluno is None:
            erros.append((n, f"estudante não encontrado entre os seus ({d.get('estagiario_cpf') or d.get('estagiario_nome') or 'linha sem estudante'})"))
        elif len(nome.split()) < 2:
            erros.append((n, "responsavel_nome: informe nome e sobrenome"))
        elif cpf and not cpf_valido(cpf):
            erros.append((n, f"responsavel_cpf: CPF inválido “{cpf}”"))
        elif maior_no_inicio(aluno):
            ignoradas.append((n, f"{aluno.nome_completo} começou o estágio com 18 anos ou mais: só cadastre o responsável "
                                 "se ele pedir (na página do estágio)"))
        elif aluno.responsaveis_legais.filter(responsavel__cpf=formatar_cpf(cpf) if cpf else "__",
                                               encerrado_em__isnull=True).exists():
            ignoradas.append((n, f"{nome} já acompanha {aluno.nome_completo}"))
        else:
            ok.append({"n": n, "aluno": aluno.pk, "aluno_nome": aluno.nome_completo, "nome": nome, "cpf": cpf,
                       "telefone": d.get("responsavel_telefone", ""), "email": d.get("responsavel_email", ""),
                       "parentesco": d.get("parentesco", "")})
    return ok, ignoradas, erros


@permissao("contas")
def importar_responsaveis(request):
    """Responsáveis legais em lote, a partir dos TCEs: prévia e depois confirmação."""
    from .. import auditoria
    from ..forms import ImportarResponsaveisForm
    from ..importacao import ErroImportacao, ler_csv
    from ..models import Usuario
    from ..responsaveis import vincular
    from ..seguranca import gerar_codigo

    if request.POST.get("etapa") == "confirmar":
        guardado = request.session.pop(CHAVE_SESSAO, None)
        if not guardado:
            messages.error(request, "A prévia expirou. Envie o arquivo de novo.")
            return redirect("importar_responsaveis")
        linhas, novos = 0, []
        for item in guardado:
            aluno = Usuario.objects.get(pk=item["aluno"])
            resp, _, criado = vincular(aluno, item["nome"], item["cpf"], item["telefone"], item["email"],
                                       item["parentesco"], "TCE", request.user)
            linhas += criado
            if resp.deve_trocar_senha and resp not in novos:
                novos.append(resp)
        auditoria.registrar(request, "GESTAO", f"Importou {linhas} responsável(is) legal(is)")
        messages.success(request, f"{linhas} vínculo(s) de responsável criado(s).")
        return _folha_responsaveis(request, [(u, gerar_codigo(u)) for u in novos], "Acesso dos responsáveis",
                                   reverse("importar_responsaveis"))
    form = ImportarResponsaveisForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            linhas = ler_csv(form.cleaned_data["arquivo"].read(), COLUNAS_RESPONSAVEIS)
        except ErroImportacao as exc:
            form.add_error("arquivo", str(exc))
        else:
            ok, ignoradas, erros = _preparar(linhas, request.user)
            request.session[CHAVE_SESSAO] = ok
            return render(request, "core/importar_responsaveis.html", {"ok": ok, "ignoradas": ignoradas, "erros": erros,
                                                                       "previa": True})
    return render(request, "core/importar_responsaveis.html", {"form": form, "colunas": COLUNAS_RESPONSAVEIS})
