"""Telas exclusivas do orientador: painel geral, contas, cadastros e alterações em lote."""
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..forms import (
    AnoReferenciaForm, ImportarCalendarioForm, RecessoForm, ConfiguracaoForm, CoordenadorForm, CursoForm, DiaSemEstagioForm, DocumentoGeralForm, EscalaLoteForm,
    EstagiariosLoteForm, LocalForm, OrientadorForm, SubstitutosForm, SupervisoresLoteForm, TurmaForm, UsuarioEditForm,
)
from ..models import (
    Agendamento, Configuracao, Curso, DiaSemEstagio, Documento, Escala, Estagio, LocalEstagio, Registro, Turma, Usuario,
    chave_municipio,
)
from ..services import (
    agrupar_periodos, ano_em_uso, ano_referencia, anos_disponiveis, cadastrar_dias, pessoas_da_concedente, criar_usuario, estagios_do_municipio, estagios_visiveis,
    feriados_nacionais, filtrar_ano, municipios_das_concedentes, notificar, redefinir_senha_padrao, resumo_horas, status_hoje, status_periodo, trocar_supervisor,
)
from .base import destino_seguro, orientador_requerido, permissao


def _meus_estagios(request, ativos=True):
    qs = estagios_visiveis(request.user).select_related("turma").prefetch_related("escalas")
    return qs.filter(ativo=True) if ativos else qs


def turmas_do_ano(user, ano):
    qs = Turma.objects.select_related("curso")
    if ano is not None:
        qs = qs.filter(ano_estagio=ano)
    if user.is_coordenador and user.cursos_ids():
        qs = qs.filter(curso_id__in=user.cursos_ids())
    return qs


def contexto_ano(request, ano):
    return {"ano": ano, "anos": anos_disponiveis(), "ano_ref": ano_referencia()}


@orientador_requerido
def painel(request):
    hoje = timezone.localdate()
    ano = ano_em_uso(request)
    todos_ativos = _meus_estagios(request)
    estagios = list(filtrar_ano(todos_ativos, ano))
    grupos = {"presentes": [], "ausentes": [], "pendentes": [], "nao_previstos": []}
    alertas = []
    semana_atras = hoje - timedelta(days=7)
    for e in estagios:
        st = status_hoje(e)
        e.st = st
        if st.codigo in ("confirmado", "aguardando", "contestado"):
            grupos["presentes"].append(e)
        elif st.codigo in ("ausencia", "ausencia_ok", "falta"):
            grupos["ausentes"].append(e)
        elif st.codigo == "hoje":
            grupos["pendentes"].append(e)
        else:
            grupos["nao_previstos"].append(e)
        if semana_atras < hoje:
            sem_reg = [s for s in status_periodo(e, semana_atras, hoje - timedelta(days=1)) if s.codigo == "sem_registro"]
            if sem_reg:
                alertas.append((e, sem_reg))

    pendentes_validacao = Registro.objects.filter(
        estagio__in=estagios, confirmacao=Registro.Confirmacao.PENDENTE, data__lt=hoje - timedelta(days=2),
    ).select_related("estagio__estagiario", "estagio__supervisor").order_by("data")[:20]
    solicitacoes = Agendamento.objects.filter(
        orientador=request.user, status=Agendamento.Status.SOLICITADO
    ).select_related("solicitante").prefetch_related("estagios__estagiario")
    if request.user.is_superuser:
        solicitacoes = Agendamento.objects.filter(status=Agendamento.Status.SOLICITADO)
    proximas = Agendamento.objects.filter(
        orientador=request.user, status=Agendamento.Status.AGENDADO, data_hora__gte=timezone.now() - timedelta(hours=2)
    ).prefetch_related("estagios__estagiario").select_related("local").order_by("data_hora")[:8]

    return render(request, "core/painel_orientador.html", {
        **contexto_ano(request, ano), "outros_anos": todos_ativos.count() - len(estagios),
        "grupos": grupos, "total": len(estagios), "alertas": alertas,
        "previstos_hoje": len(estagios) - len(grupos["nao_previstos"]),
        "pendentes_validacao": pendentes_validacao, "solicitacoes": solicitacoes, "proximas": proximas,
    })


@orientador_requerido
def estagios_lista(request):
    ano = ano_em_uso(request)
    qs = filtrar_ano(_meus_estagios(request, ativos=False), ano)
    f = {k: request.GET.get(k, "") for k in ("q", "curso", "local", "turma", "situacao")}
    if f["q"]:
        qs = qs.filter(Q(estagiario__nome_completo__icontains=f["q"]) | Q(estagiario__username__icontains=f["q"]))
    if f["curso"]:
        qs = qs.filter(curso_id=f["curso"])
    if f["local"]:
        qs = qs.filter(local_id=f["local"])
    if f["turma"].isdigit():
        qs = qs.filter(turma_id=f["turma"])
    qs = qs.filter(ativo=f["situacao"] != "inativos")
    estagios = list(qs)
    for e in estagios:
        e.st = status_hoje(e)
        e.h = resumo_horas(e)
    return render(request, "core/estagios_lista.html", {
        **contexto_ano(request, ano),
        "estagios": estagios, "f": f, "cursos": Curso.objects.all(), "locais": LocalEstagio.objects.all(),
        "turmas": turmas_do_ano(request.user, ano),
    })


# ----------------------------------------------------------------- contas


@permissao("estagiarios")
def criar_estagiarios(request):
    form = EstagiariosLoteForm(request.POST or None, usuario=request.user,
                               initial={"data_inicio": timezone.localdate(), "dias": [0, 1, 2, 3, 4]})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        criados = []
        with transaction.atomic():
            for nome, matricula in d["nomes"]:
                user = criar_usuario(nome, Usuario.Papel.ESTAGIARIO, request.user, matricula=matricula)
                estagio = Estagio.objects.create(
                    estagiario=user, orientador=d.get("orientador") or request.user, supervisor=d["supervisor"],
                    curso=d["turma"].curso, turma=d["turma"], local=d["local"], setor=d["setor"], data_inicio=d["data_inicio"],
                    data_fim=d["data_fim"],
                )
                Escala.objects.create(estagio=estagio, vigente_desde=d["data_inicio"], criado_por=request.user,
                                      **form.dados_escala())
                criados.append(user)
        if d["supervisor"]:
            notificar([d["supervisor"]], f"{len(criados)} estagiário(s) foram vinculados a você.",
                      reverse("painel_supervisor"))
        return _resultado_contas(request, criados, "Estagiários criados")
    return render(request, "core/form_pagina.html", {
        "form": form, "titulo": "Cadastrar estagiários em lote", "voltar": reverse("estagios_lista"),
        "ajuda": "O usuário de cada pessoa é gerado como primeiro.ultimo nome (sem acentos). "
                 "Todos recebem a senha padrão e precisam trocá-la no primeiro acesso.",
        "botao": "Criar contas",
    })


@permissao("contas")
def criar_supervisores(request):
    form = SupervisoresLoteForm(request.POST or None, initial={"local": request.GET.get("local")})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        with transaction.atomic():
            criados = [criar_usuario(nome, Usuario.Papel.SUPERVISOR, request.user, telefone=tel, concedente=d["local"],
                                     cargo=d["cargo"]) for nome, tel in d["nomes"]]
        return _resultado_contas(request, criados, "Supervisores criados")
    return render(request, "core/form_pagina.html", {
        "form": form, "titulo": "Cadastrar supervisores", "voltar": reverse("usuarios"),
        "ajuda": "Basta o nome completo e o telefone: o próprio supervisor completa o resto no perfil. "
                 "Depois, vincule o supervisor aos estagiários na edição de cada estágio ou no cadastro em lote.",
        "botao": "Criar contas",
    })


@permissao("contas")
def criar_orientador(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    form = OrientadorForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = criar_usuario(form.cleaned_data["nome"], Usuario.Papel.ORIENTADOR, request.user,
                             email=form.cleaned_data["email"])
        return _resultado_contas(request, [user], "Orientador criado")
    return render(request, "core/form_pagina.html", {
        "form": form, "titulo": "Cadastrar orientador(a)", "voltar": reverse("usuarios"), "botao": "Criar conta",
    })


@permissao("contas")
def criar_coordenador(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    form = CoordenadorForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        user = criar_usuario(d["nome"], Usuario.Papel.COORDENADOR, request.user, email=d["email"], telefone=d["telefone"])
        user.cursos_coordenados.set(d["cursos"])
        return _resultado_contas(request, [user], "Coordenador(a) criado(a)")
    return render(request, "core/form_pagina.html", {
        "form": form, "titulo": "Cadastrar coordenador(a) de curso", "voltar": reverse("usuarios"), "botao": "Criar conta",
        "ajuda": "O coordenador acompanha os estágios dos seus cursos e analisa a captação de concedentes. "
                 "Não agenda visitas nem muda dias e horários de estágio.",
    })


def _resultado_contas(request, usuarios, titulo):
    from django.conf import settings

    messages.success(request, f"{len(usuarios)} conta(s) criada(s).")
    return render(request, "core/contas_criadas.html", {
        "usuarios": usuarios, "titulo": titulo, "senha": settings.SENHA_PADRAO,
        "endereco": request.build_absolute_uri("/"),
    })


@permissao("contas")
def usuarios(request):
    papel = request.GET.get("papel", "")
    q = request.GET.get("q", "")
    situacao = request.GET.get("situacao", "")
    if request.user.is_superuser:
        qs = Usuario.objects.all()
    else:
        meus = estagios_visiveis(request.user)
        qs = Usuario.objects.filter(
            Q(pk__in=meus.values("estagiario")) | Q(pk__in=meus.values("supervisor"))
            | Q(criado_por=request.user) | Q(papel=Usuario.Papel.SUPERVISOR) | Q(pk=request.user.pk)
        )
    if papel:
        qs = qs.filter(papel=papel)
    if situacao != "todas":
        qs = qs.filter(is_active=situacao != "inativas")
    if q:
        qs = qs.filter(Q(nome_completo__icontains=q) | Q(username__icontains=q))
    qs = qs.prefetch_related("concedentes").annotate(
        n_supervisionados=Count("estagios_supervisionados", filter=Q(estagios_supervisionados__ativo=True), distinct=True))
    return render(request, "core/usuarios.html", {
        "usuarios": qs.distinct(), "papel": papel, "q": q, "papeis": Usuario.Papel.choices, "situacao": situacao,
    })


def _pode_gerir(request, alvo):
    if request.user.is_superuser or alvo.pk == request.user.pk:
        return True
    if alvo.is_superuser or alvo.is_gestor:
        return False
    if alvo.is_supervisor:
        return True
    return estagios_visiveis(request.user).filter(estagiario=alvo).exists() or alvo.criado_por_id == request.user.pk


@permissao("contas")
def editar_usuario(request, pk):
    alvo = get_object_or_404(Usuario, pk=pk)
    if not _pode_gerir(request, alvo):
        raise PermissionDenied
    form = UsuarioEditForm(request.POST or None, instance=alvo)
    if not alvo.is_supervisor:
        del form.fields["concedentes"], form.fields["cargo"]
    if not alvo.is_estagiario:
        del form.fields["cpf"]
    if not (alvo.is_coordenador and request.user.is_superuser):
        del form.fields["cursos_coordenados"]
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Usuário atualizado.")
        return redirect("usuarios")
    return render(request, "core/form_pagina.html", {
        "form": form, "titulo": f"Editar {alvo} ({alvo.username})", "voltar": reverse("usuarios"),
        "extra_template": "core/_redefinir_senha.html", "alvo": alvo,
    })


@permissao("contas")
@require_POST
def redefinir_senha(request, pk):
    from django.conf import settings

    alvo = get_object_or_404(Usuario, pk=pk)
    if not _pode_gerir(request, alvo) or alvo.pk == request.user.pk:
        raise PermissionDenied
    redefinir_senha_padrao(alvo)
    messages.success(request, f"A senha de {alvo.username} voltou para a senha padrão ({settings.SENHA_PADRAO}).")
    return redirect(request.POST.get("next") or "usuarios")


@permissao("contas")
def ativacao_usuario(request, pk):
    """Desativar ou reativar uma conta. Supervisor com estagiários ativos só sai com um substituto para cada um."""
    alvo = get_object_or_404(Usuario, pk=pk)
    if not _pode_gerir(request, alvo) or alvo.pk == request.user.pk or alvo.is_superuser:
        raise PermissionDenied
    desativar = alvo.is_active
    estagios = list(alvo.estagios_supervisionados.filter(ativo=True).select_related("estagiario", "local")
                    ) if desativar and alvo.is_supervisor else []
    orientados = alvo.estagios_orientados.filter(ativo=True).count() if desativar and alvo.is_orientador else 0
    form = SubstitutosForm(request.POST if request.method == "POST" else None, estagios=estagios, sair=alvo)
    ultimo_estagio = alvo.estagios.order_by("-data_inicio").first() if alvo.is_estagiario else None
    if request.method == "POST" and not orientados and form.is_valid():
        with transaction.atomic():
            if desativar:
                for e, novo in form.trocas():
                    trocar_supervisor(e, novo, request.user, motivo=f"{alvo} foi desativado(a)")
                n = alvo.estagios.filter(ativo=True).update(ativo=False) if alvo.is_estagiario else 0
                alvo.is_active = False
                alvo.save(update_fields=["is_active"])
                messages.success(request, f"Conta de {alvo} desativada: não consegue mais entrar no sistema."
                                 + (f" {len(estagios)} estagiário(s) passaram para os novos supervisores." if estagios else "")
                                 + (" O estágio foi encerrado." if n else ""))
            else:
                alvo.is_active = True
                alvo.save(update_fields=["is_active"])
                if ultimo_estagio and request.POST.get("reativar_estagio") and not ultimo_estagio.ativo:
                    ultimo_estagio.ativo = True
                    ultimo_estagio.save(update_fields=["ativo"])
                messages.success(request, f"Conta de {alvo} reativada.")
        return redirect(destino_seguro(request, reverse("usuarios")))
    return render(request, "core/ativacao_usuario.html", {
        "alvo": alvo, "desativar": desativar, "form": form, "estagios": estagios, "orientados": orientados,
        "ultimo_estagio": ultimo_estagio,
    })


# ----------------------------------------------------------------- cadastros simples


def _crud_simples(request, modelo, form_cls, titulo, template, pk=None, extra=None):
    obj = get_object_or_404(modelo, pk=pk) if pk else None
    form = form_cls(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"{titulo} salvo.")
        return redirect(request.path if not pk else reverse(template.split("/")[-1].removesuffix(".html")))
    ctx = {"form": form, "itens": modelo.objects.all(), "editando": obj, "titulo": titulo}
    ctx.update(extra or {})
    return render(request, template, ctx)


@permissao("cadastros")
def cursos(request, pk=None):
    return _crud_simples(request, Curso, CursoForm, "Curso", "core/cursos.html", pk, {
        "itens": Curso.objects.annotate(n=Count("estagios", filter=Q(estagios__ativo=True)))
    })


@permissao("cadastros")
def turmas(request, pk=None):
    """Turmas por ano: a turma de 2024 estagia em 2026, a de 2025 em 2027… O nome pode se repetir todo ano."""
    config = Configuracao.atual()
    obj = get_object_or_404(Turma, pk=pk) if pk else None
    if obj and request.user.is_coordenador and not request.user.coordena(obj.curso_id):
        raise PermissionDenied
    ref = config.ano_referencia_efetivo
    inicial = {} if obj else {"ano_estagio": ref, "ano_ingresso": ref - 2}
    form = TurmaForm(request.POST if request.POST.get("acao") == "turma" else None, instance=obj, usuario=request.user,
                     initial=inicial)
    form_ano = AnoReferenciaForm(request.POST if request.POST.get("acao") == "ano" else None, instance=config)
    pode_ano = request.user.is_superuser or request.user.is_orientador
    if request.method == "POST":
        acao = request.POST.get("acao")
        if acao == "turma" and form.is_valid():
            t = form.save()
            messages.success(request, f"Turma “{t}” salva.")
            return redirect("turmas")
        if acao == "ano" and pode_ano and form_ano.is_valid():
            form_ano.save()
            request.session.pop("ano_lista", None)
            messages.success(request, f"Ano de referência: {Configuracao.atual().ano_referencia_efetivo}.")
            return redirect("turmas")
        if acao == "repetir":
            try:
                de = int(request.POST.get("de", ""))
            except ValueError:
                de = ref
            criadas = 0
            for t in turmas_do_ano(request.user, de):
                _, nova = Turma.objects.get_or_create(
                    curso=t.curso, nome=t.nome, ano_ingresso=t.ano_ingresso + 1, defaults={"ano_estagio": t.ano_estagio + 1})
                criadas += nova
            messages.success(request, f"{criadas} turma(s) criada(s) para {de + 1}, com os mesmos nomes de {de}."
                             if criadas else f"As turmas de {de + 1} já existiam.")
            return redirect("turmas")
    itens = turmas_do_ano(request.user, None).annotate(
        n=Count("estagios", filter=Q(estagios__ativo=True), distinct=True),
        n_total=Count("estagios", distinct=True))
    grupos = {}
    for t in itens:
        grupos.setdefault(t.ano_estagio, []).append(t)
    return render(request, "core/turmas.html", {
        "form": form, "form_ano": form_ano, "pode_ano": pode_ano, "editando": obj, "ref": ref,
        "grupos": sorted(grupos.items(), reverse=True), "proximo": max(grupos, default=ref),
    })


@permissao("cadastros")
def locais(request):
    q = request.GET.get("q", "").strip()
    situacao = request.GET.get("situacao", "")
    itens = LocalEstagio.objects.annotate(
        n=Count("estagios", filter=Q(estagios__ativo=True), distinct=True),
        n_sup=Count("supervisores", distinct=True),
    )
    if q:
        itens = itens.filter(Q(nome__icontains=q) | Q(razao_social__icontains=q) | Q(cnpj__icontains=q)
                             | Q(cidade__icontains=q))
    if situacao != "todas":
        itens = itens.filter(ativa=situacao != "inativas")
    return render(request, "core/locais.html", {"itens": itens, "q": q, "situacao": situacao,
                                                "n_inativas": LocalEstagio.objects.filter(ativa=False).count()})


def _sozinhos(local, sup_qs):
    """Supervisores da concedente que não têm outra concedente ativa."""
    return [s for s in sup_qs.prefetch_related("concedentes")
            if not any(c.ativa and c.pk != local.pk for c in s.concedentes.all())]


@permissao("cadastros")
def ativacao_local(request, pk):
    """Desativar ou reativar uma concedente (e, se quiser, as contas dos supervisores que só atuam nela)."""
    local = get_object_or_404(LocalEstagio, pk=pk)
    desativar = local.ativa
    ativos = list(local.estagios.filter(ativo=True).select_related("estagiario")) if desativar else []
    supervisores = _sozinhos(local, local.supervisores.filter(is_active=desativar))
    if request.method == "POST" and not ativos:
        with transaction.atomic():
            local.ativa = not desativar
            local.save(update_fields=["ativa"])
            contas = 0
            if request.POST.get("contas"):
                for s in supervisores:
                    if desativar and s.estagios_supervisionados.filter(ativo=True).exists():
                        continue
                    s.is_active = not desativar
                    s.save(update_fields=["is_active"])
                    contas += 1
        messages.success(request, f"Concedente “{local}” {'desativada' if desativar else 'reativada'}."
                         + (f" {contas} conta(s) de supervisor {'desativada' if desativar else 'reativada'}(s)." if contas else ""))
        return redirect("locais")
    return render(request, "core/ativacao_local.html", {
        "local": local, "desativar": desativar, "ativos": ativos, "supervisores": supervisores,
    })


@permissao("cadastros")
def local_editar(request, pk=None):
    """Ficha da concedente (dados gerais, endereço, representante legal) + cadastro rápido de supervisores."""
    obj = get_object_or_404(LocalEstagio, pk=pk) if pk else None
    form = LocalForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            local = form.save()
            criados = [criar_usuario(nome, Usuario.Papel.SUPERVISOR, request.user, telefone=tel, concedente=local)
                       for nome, tel in form.cleaned_data["novos_supervisores"]]
            for sup in form.cleaned_data["vincular_supervisores"]:
                sup.concedentes.add(local)
        messages.success(request, f"Concedente “{local}” salva.")
        if criados:
            return _resultado_contas(request, criados, f"Supervisores de {local}")
        return redirect("locais")
    supervisores = obj.supervisores.order_by("nome_completo") if obj else []
    recessos_futuros = agrupar_periodos(obj.recessos.filter(data__gte=timezone.localdate()).order_by("data")) if obj else []
    return render(request, "core/concedente_form.html", {"form": form, "obj": obj, "supervisores": supervisores,
                                                         "recessos": recessos_futuros})


@orientador_requerido
def configuracoes(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    config = Configuracao.atual()
    if request.POST.get("acao") == "teste_email":
        from django.conf import settings
        from django.core.mail import send_mass_mail

        from ..services import mensagem_aviso

        if not settings.EMAIL_ATIVO:
            messages.error(request, "O servidor de e-mail não está configurado (variável EMAIL_HOST).")
        elif not request.user.email:
            messages.error(request, "Cadastre o seu e-mail em Meus dados para receber o teste.")
        else:
            # o teste envia na hora (sem segundo plano) para mostrar o erro do servidor, se houver
            try:
                send_mass_mail([mensagem_aviso(request.user, "Teste de e-mail: os avisos do sistema estão chegando.",
                                               reverse("notificacoes"))], fail_silently=False)
                messages.success(request, f"E-mail de teste enviado para {request.user.email}. Confira também o spam.")
            except Exception as exc:  # noqa: BLE001
                messages.error(request, f"O servidor de e-mail recusou o envio: {exc}")
        return redirect("configuracoes")
    logo_antigo = config.logo_folha.name if config.logo_folha else ""
    form = ConfiguracaoForm(request.POST or None, request.FILES or None, instance=config)
    if request.method == "POST" and form.is_valid():
        config = form.save()
        if logo_antigo and (not config.logo_folha or config.logo_folha.name != logo_antigo):
            config.logo_folha.storage.delete(logo_antigo)
        messages.success(request, "Configurações salvas.")
        return redirect("configuracoes")
    return render(request, "core/form_pagina.html", {
        "form": form, "titulo": "Configurações do sistema", "voltar": reverse("painel"),
        "ajuda": "Os dados da escola e o logotipo aparecem no cabeçalho da folha de frequência de todos os estagiários. "
                 "O banco de talentos só mostra estagiários que autorizarem no próprio perfil.",
        "extra_template": "core/_config_email.html",
    })



def _ano_param(request):
    try:
        ano = int(request.GET.get("ano") or request.POST.get("ano") or timezone.localdate().year)
        return ano if 2000 <= ano <= 2100 else timezone.localdate().year
    except ValueError:
        return timezone.localdate().year


def _pode_excluir_feriado(user, dia):
    return user.is_superuser or dia.abrangencia != DiaSemEstagio.Abrangencia.ESCOLA or dia.orientador_id == user.pk


def _ids_post(request, nome="excluir"):
    """Aceita “12” ou “12,13,14” (um período inteiro)."""
    return [int(x) for v in request.POST.getlist(nome) for x in v.split(",") if x.strip().isdigit()]


@permissao("feriados")
def dias_sem_estagio(request):
    """Feriados nacionais/estaduais (todos), municipais (pelo município da concedente) e eventos da escola."""
    A = DiaSemEstagio.Abrangencia
    aba = request.GET.get("aba", "municipais")
    ano = _ano_param(request)
    inicial = {"abrangencia": A.MUNICIPIO if aba == "municipais" else A.TODOS if aba == "nacionais" else A.ESCOLA,
               "anual": aba == "municipais", "municipio": request.GET.get("municipio", "")}
    form = DiaSemEstagioForm(request.POST if request.POST.get("acao") == "adicionar" else None, initial=inicial)
    if request.method == "POST":
        acao = request.POST.get("acao")
        if "excluir" in request.POST:
            dias = list(DiaSemEstagio.objects.filter(pk__in=_ids_post(request)))
            if not dias or not all(_pode_excluir_feriado(request.user, d) for d in dias):
                raise PermissionDenied
            for d in dias:
                d.delete()
            messages.success(request, f"{len(dias)} dia(s) removido(s).")
            return redirect(request.get_full_path())
        if acao == "nacionais":
            escolhidos = set(request.POST.getlist("f"))
            n = 0
            for data, nome, tipo, _ in feriados_nacionais(ano):
                if f"{data:%Y-%m-%d}" in escolhidos:
                    _, criado = DiaSemEstagio.objects.get_or_create(
                        data=data, abrangencia=A.TODOS,
                        defaults={"descricao": nome, "orientador": request.user, "origem": "calendario"})
                    n += criado
            messages.success(request, f"{n} feriado(s) de {ano} cadastrado(s) para todos os estagiários.")
            return redirect(f"{reverse('dias_sem_estagio')}?aba=nacionais&ano={ano}")
        if acao == "adicionar" and form.is_valid():
            d = form.cleaned_data
            dia, ate = d["data"], d.get("ate") or d["data"]
            chave = chave_municipio(d["municipio"]) if d["abrangencia"] == A.MUNICIPIO else ""
            n = cadastrar_dias(request.user, d["abrangencia"], dia, d["descricao"], ate, d["municipio"], d["anual"],
                               d["curso"], concedente=d.get("concedente"))
            if d["abrangencia"] == A.ESCOLA:
                estagios = _meus_estagios(request)
                if d["curso"]:
                    estagios = estagios.filter(curso=d["curso"])
            elif d["abrangencia"] == A.MUNICIPIO:
                estagios = estagios_do_municipio(chave)
            elif d["abrangencia"] == A.CONCEDENTE:
                estagios = Estagio.objects.filter(ativo=True, local=d["concedente"]).select_related("estagiario", "supervisor")
            else:
                estagios = Estagio.objects.filter(ativo=True).select_related("estagiario", "supervisor")
            pessoas = [p for e in estagios for p in (e.estagiario, e.supervisor)]
            periodo = f"{d['data']:%d/%m}" + (f" a {ate:%d/%m}" if ate != d["data"] else "")
            onde = f" ({d['municipio'].strip()})" if chave else f" ({d['concedente']})" if d.get("concedente") else ""
            notificar(pessoas, f"Sem estágio em {periodo}{onde}: {d['descricao']}.", reverse("inicio"))
            messages.success(request, f"{n} dia(s) cadastrado(s)" + (f"; {len(estagios)} estágio(s) neste município" if chave else "")
                             + ".")
            if d["abrangencia"] == A.CONCEDENTE:
                return redirect(f"{reverse('recessos')}?concedente={d['concedente'].pk}")
            destino = {A.MUNICIPIO: "municipais", A.TODOS: "nacionais"}.get(d["abrangencia"], "escola")
            return redirect(f"{reverse('dias_sem_estagio')}?aba={destino}")

    hoje = timezone.localdate()
    ctx = {"form": form, "aba": aba, "ano": ano, "anos": [ano - 1, ano, ano + 1], "hoje": hoje,
           "municipios": municipios_das_concedentes()}
    if aba == "municipais":
        municipais = list(DiaSemEstagio.objects.filter(abrangencia=A.MUNICIPIO).order_by("municipio_chave", "data"))
        por_chave = {}
        for d in municipais:
            por_chave.setdefault(d.municipio_chave, []).append(d)
        for m in ctx["municipios"]:
            m["feriados"] = por_chave.pop(m["chave"], [])
        ctx["sem_concedente"] = sorted(por_chave.values(), key=lambda l: l[0].municipio_chave)  # municípios sem concedente ativa
        ctx["faltando"] = [m for m in ctx["municipios"] if not m["feriados"] and m["estagios"]]
    elif aba == "nacionais":
        cadastrados = {d.data: d for d in DiaSemEstagio.objects.filter(abrangencia=A.TODOS, data__year=ano)}
        sugestoes = feriados_nacionais(ano)
        ctx["sugestoes"] = [{"data": dt, "nome": nome, "tipo": tipo, "marcado": marcado, "ja": cadastrados.get(dt)}
                            for dt, nome, tipo, marcado in sugestoes]
        datas_sugeridas = {dt for dt, *_ in sugestoes}
        ctx["nacionais"] = sorted(cadastrados.values(), key=lambda d: d.data)
        ctx["outros_nacionais"] = [d for d in ctx["nacionais"] if d.data not in datas_sugeridas]
    else:
        itens = DiaSemEstagio.objects.filter(abrangencia=A.ESCOLA, orientador=request.user).select_related("curso")
        ctx.update(futuros=itens.filter(data__gte=hoje), passados=itens.filter(data__lt=hoje).reverse()[:30])
    return render(request, "core/dias_sem_estagio.html", ctx)


def _concedentes_dos_recessos(user):
    """Concedentes cujos recessos a pessoa pode ver e cadastrar."""
    if user.is_supervisor:
        return user.concedentes.filter(ativa=True)
    if user.pode("feriados") or user.pode("cadastros"):
        return LocalEstagio.objects.filter(ativa=True)
    raise PermissionDenied


@login_required
def recessos(request):
    """Recessos de cada concedente: períodos em que ela não recebe os estagiários.

    O orientador/coordenador cadastra para qualquer concedente; o supervisor, para as concedentes em que atua.
    """
    A = DiaSemEstagio.Abrangencia
    permitidas = _concedentes_dos_recessos(request.user)
    filtro = request.GET.get("concedente", "")
    form = RecessoForm(request.POST if request.POST.get("acao") == "adicionar" else None, concedentes=permitidas,
                       initial={"concedente": filtro} if filtro.isdigit() else {})
    if request.method == "POST":
        if "excluir" in request.POST:
            dias = list(DiaSemEstagio.objects.filter(pk__in=_ids_post(request), abrangencia=A.CONCEDENTE,
                                                     concedente__in=permitidas))
            for d in dias:
                d.delete()
            messages.success(request, f"Recesso removido ({len(dias)} dia(s)).")
            return redirect(request.get_full_path())
        if form.is_valid():
            d = form.cleaned_data
            local = d["concedente"]
            n = cadastrar_dias(request.user, A.CONCEDENTE, d["data"], d["descricao"], d.get("ate"), concedente=local)
            periodo = f"{d['data']:%d/%m}" + (f" a {d['ate']:%d/%m}" if d.get("ate") and d["ate"] != d["data"] else "")
            notificar(pessoas_da_concedente(local), f"{local} em recesso em {periodo}: {d['descricao']}. "
                      "Nesses dias não há estágio.", reverse("inicio"), exceto=request.user)
            messages.success(request, f"Recesso de {local} cadastrado: {periodo} ({n} dia(s) novo(s)). "
                             "Estagiários, supervisores e orientadores foram avisados.")
            return redirect(f"{reverse('recessos')}?concedente={local.pk}")
    hoje = timezone.localdate()
    qs = DiaSemEstagio.objects.filter(abrangencia=A.CONCEDENTE, concedente__in=permitidas).select_related("concedente")
    if filtro.isdigit():
        qs = qs.filter(concedente_id=filtro)
    grupos = {}
    for d in qs.order_by("concedente__nome", "data"):
        grupos.setdefault(d.concedente, []).append(d)
    lista = []
    for local, dias in grupos.items():
        periodos = agrupar_periodos(dias)
        lista.append({"local": local, "futuros": [p for p in periodos if p["fim"] >= hoje],
                      "passados": [p for p in periodos if p["fim"] < hoje][-5:]})
    lista.sort(key=lambda g: (not g["futuros"], g["local"].nome))
    return render(request, "core/recessos.html", {
        "form": form, "grupos": lista, "filtro": filtro, "concedentes": permitidas,
        "local_filtrado": permitidas.filter(pk=filtro).first() if filtro.isdigit() else None,
    })


CHAVE_CALENDARIO = "importacao_calendario"


@permissao("feriados")
def importar_feriados(request):
    """Importa feriados municipais/nacionais e o calendário letivo de um CSV ou ICS, com prévia antes de gravar."""
    from ..calendarios import ErroCalendario, Item, Padrao, ler_calendario, modelo_csv

    A = DiaSemEstagio.Abrangencia
    if request.GET.get("modelo"):
        resposta = HttpResponse(modelo_csv(), content_type="text/csv; charset=utf-8")
        resposta["Content-Disposition"] = 'attachment; filename="modelo-calendario.csv"'
        return resposta
    ctx = {"municipios": municipios_das_concedentes()}
    if request.POST.get("etapa") == "confirmar":
        guardado = request.session.get(CHAVE_CALENDARIO)
        if not guardado:
            messages.error(request, "A prévia expirou. Envie o arquivo de novo.")
            return redirect("importar_feriados")
        itens = [Item.da_sessao(d) for d in guardado["itens"]]
        escolhidos = [itens[int(i)] for i in request.POST.getlist("i") if i.isdigit() and int(i) < len(itens)]
        removidos = criados = 0
        with transaction.atomic():
            if guardado["substituir"] and escolhidos:
                anos = {i.data.year for i in escolhidos} | {i.ate.year for i in escolhidos if i.ate}
                grupos = {(i.abrangencia, chave_municipio(i.municipio), i.concedente_id) for i in escolhidos}
                for abr, chave, conc in grupos:
                    antigos = DiaSemEstagio.objects.filter(origem="importado", abrangencia=abr, municipio_chave=chave,
                                                           concedente_id=conc).filter(
                        Q(data__year__in=anos) | Q(anual=True))
                    if abr == A.ESCOLA:
                        antigos = antigos.filter(orientador=request.user)
                    removidos += antigos.delete()[0]
            cursos = {c.pk: c for c in Curso.objects.all()}
            locais = LocalEstagio.objects.in_bulk({i.concedente_id for i in escolhidos if i.concedente_id})
            for i in escolhidos:
                if i.abrangencia == A.CONCEDENTE and i.concedente_id not in locais:
                    continue  # concedente removida entre a prévia e a confirmação
                criados += cadastrar_dias(request.user, i.abrangencia, i.data, i.descricao, i.ate, i.municipio, i.anual,
                                          cursos.get(i.curso_id), origem="importado",
                                          concedente=locais.get(i.concedente_id))
        del request.session[CHAVE_CALENDARIO]
        messages.success(request, f"Calendário importado: {criados} dia(s) cadastrado(s)"
                         + (f", {removidos} da importação anterior substituído(s)" if removidos else "") + ".")
        abas = {i.abrangencia for i in escolhidos}
        if abas == {A.CONCEDENTE}:
            return redirect("recessos")
        destino = "municipais" if A.MUNICIPIO in abas else "nacionais" if A.TODOS in abas else "escola"
        return redirect(f"{reverse('dias_sem_estagio')}?aba={destino}")

    form = ImportarCalendarioForm(request.POST or None, request.FILES or None, initial={
        "ano": timezone.localdate().year, "municipio": request.GET.get("municipio", ""),
        "abrangencia": request.GET.get("abrangencia") or A.MUNICIPIO})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        padrao = Padrao(d["abrangencia"], d["municipio"].strip(), d["ano"], d.get("concedente"))
        try:
            itens, erros = ler_calendario(d["arquivo"].read(), d["arquivo"].name, padrao)
        except ErroCalendario as exc:
            form.add_error("arquivo", str(exc))
        else:
            for i in itens:  # já cadastrados (todos os dias do item)
                existentes = DiaSemEstagio.objects.filter(
                    abrangencia=i.abrangencia, municipio_chave=chave_municipio(i.municipio),
                    concedente_id=i.concedente_id, data__range=(i.data, i.ate or i.data))
                if i.abrangencia == A.ESCOLA:
                    existentes = existentes.filter(orientador=request.user, curso_id=i.curso_id)
                i.ja = existentes.count() >= i.dias
            request.session[CHAVE_CALENDARIO] = {"itens": [i.para_sessao() for i in itens],
                                                  "substituir": d["substituir"], "nome": d["arquivo"].name}
            ctx.update(itens=itens, erros=erros, nome=d["arquivo"].name, substituir=d["substituir"],
                       por_tipo={a: sum(1 for i in itens if i.abrangencia == a) for a in A.values},
                       rotulos=dict(A.choices))
            return render(request, "core/importar_feriados.html", ctx)
    ctx.update(form=form)
    from ..calendarios import COLUNAS

    ctx["colunas"] = COLUNAS
    return render(request, "core/importar_feriados.html", ctx)


# ----------------------------------------------------------------- alterações em lote


@login_required
def escala_lote(request):
    """Supervisor: dias e horários de vários estagiários. Orientador: só os dias (cada um mantém seus horários)."""
    user = request.user
    supervisor = user.is_supervisor
    if not (supervisor or user.pode("escalas")):
        raise PermissionDenied
    qs = estagios_visiveis(user).filter(ativo=True).select_related("turma").prefetch_related("escalas")
    ano = None if supervisor else ano_em_uso(request)
    qs = filtrar_ano(qs, ano)
    filtro_curso = request.GET.get("curso", "")
    filtro_turma = request.GET.get("turma", "")
    if filtro_curso:
        qs = qs.filter(curso_id=filtro_curso)
    if filtro_turma.isdigit():
        qs = qs.filter(turma_id=filtro_turma)
    inicial = {"dias": [0, 1, 2, 3, 4], "vigente_desde": timezone.localdate()}
    if request.GET.get("estagio"):
        inicial["estagios"] = qs.filter(pk=request.GET["estagio"])
    form = EscalaLoteForm(request.POST or None, estagios_qs=qs, com_horarios=supervisor, initial=inicial)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        dados = form.dados_escala()
        with transaction.atomic():
            for e in d["estagios"]:
                if not supervisor:  # mantém horas e horários que a concedente definiu
                    atual = e.escala_em(d["vigente_desde"]) or e.escalas.order_by("vigente_desde").first()
                    dados = {**form.dados_escala(), **({
                        "horas_por_dia": atual.horas_por_dia, "horario_entrada": atual.horario_entrada,
                        "saida_intervalo": atual.saida_intervalo, "volta_intervalo": atual.volta_intervalo,
                        "horario_saida": atual.horario_saida,
                    } if atual else {"horas_por_dia": e.curso.horas_por_dia_padrao})}
                Escala.objects.update_or_create(
                    estagio=e, vigente_desde=d["vigente_desde"], defaults={**dados, "criado_por": user},
                )
        exemplo = Escala(**{k: v for k, v in dados.items() if k != "horas_por_dia"})
        o_que = f"{exemplo.dias_display}" + (f" · {exemplo.horario_display}" if supervisor and exemplo.horario_display else "")
        pessoas = [p for e in d["estagios"] for p in (e.estagiario, e.supervisor, e.orientador)]
        notificar(pessoas, f"{user.primeiro_nome} mudou os dias de estágio a partir de {d['vigente_desde']:%d/%m}: {o_que}.",
                  reverse("inicio"), exceto=user)
        messages.success(request, f"Aplicado a {len(d['estagios'])} estagiário(s) a partir de {d['vigente_desde']:%d/%m/%Y}.")
        return redirect("painel_supervisor" if supervisor else "estagios_lista")
    turmas = Turma.objects.filter(pk__in=estagios_visiveis(user).filter(ativo=True).values("turma")).select_related("curso")
    if ano is not None:
        turmas = turmas.filter(ano_estagio=ano)
    return render(request, "core/escala_lote.html", {
        **(contexto_ano(request, ano) if not supervisor else {}),
        "form": form, "cursos": Curso.objects.all(), "turmas": turmas, "supervisor": supervisor,
        "filtro_curso": filtro_curso, "filtro_turma": filtro_turma,
    })


@permissao("arquivos")
def documentos_gerais(request):
    estagios = _meus_estagios(request)
    form = DocumentoGeralForm(request.POST or None, request.FILES or None, estagios_qs=estagios)
    if request.method == "POST" and form.is_valid():
        doc = form.save(commit=False)
        doc.orientador = doc.enviado_por = request.user
        doc.nome_original = request.FILES["arquivo"].name[:255]
        doc.save()
        if doc.estagio:
            alvo = doc.estagio.participantes()
        else:
            alvos = estagios.filter(curso=doc.curso) if doc.curso else estagios
            alvo = [e.estagiario for e in alvos]
        notificar(alvo, f"Novo arquivo disponível: {doc.titulo}.", reverse("baixar_documento", args=[doc.pk]),
                  exceto=request.user)
        messages.success(request, "Arquivo publicado.")
        return redirect("documentos_gerais")
    docs = Documento.objects.filter(orientador=request.user).select_related("estagio__estagiario", "curso", "enviado_por")
    return render(request, "core/documentos.html", {"form": form, "documentos": docs[:200]})
