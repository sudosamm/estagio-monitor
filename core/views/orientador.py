"""Telas exclusivas do orientador: painel geral, contas, cadastros e alterações em lote."""
from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..forms import (
    ConfiguracaoForm, CoordenadorForm, CursoForm, DiaSemEstagioForm, DocumentoGeralForm, EscalaLoteForm, EstagiariosLoteForm, LocalForm,
    OrientadorForm, SupervisoresLoteForm, UsuarioEditForm,
)
from ..models import (
    Agendamento, Configuracao, Curso, DiaSemEstagio, Documento, Escala, Estagio, LocalEstagio, Registro, Usuario,
)
from ..services import (
    criar_usuario, estagios_visiveis, notificar, redefinir_senha_padrao, resumo_horas, status_hoje, status_periodo,
)
from .base import orientador_requerido, permissao


def _meus_estagios(request, ativos=True):
    qs = estagios_visiveis(request.user).prefetch_related("escalas")
    return qs.filter(ativo=True) if ativos else qs


@orientador_requerido
def painel(request):
    hoje = timezone.localdate()
    estagios = list(_meus_estagios(request))
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
        "grupos": grupos, "total": len(estagios), "alertas": alertas,
        "previstos_hoje": len(estagios) - len(grupos["nao_previstos"]),
        "pendentes_validacao": pendentes_validacao, "solicitacoes": solicitacoes, "proximas": proximas,
    })


@orientador_requerido
def estagios_lista(request):
    qs = _meus_estagios(request, ativos=False)
    f = {k: request.GET.get(k, "") for k in ("q", "curso", "local", "turma", "situacao")}
    if f["q"]:
        qs = qs.filter(Q(estagiario__nome_completo__icontains=f["q"]) | Q(estagiario__username__icontains=f["q"]))
    if f["curso"]:
        qs = qs.filter(curso_id=f["curso"])
    if f["local"]:
        qs = qs.filter(local_id=f["local"])
    if f["turma"]:
        qs = qs.filter(turma=f["turma"])
    qs = qs.filter(ativo=f["situacao"] != "inativos")
    estagios = list(qs)
    for e in estagios:
        e.st = status_hoje(e)
        e.h = resumo_horas(e)
    return render(request, "core/estagios_lista.html", {
        "estagios": estagios, "f": f, "cursos": Curso.objects.all(), "locais": LocalEstagio.objects.all(),
        "turmas": sorted(set(_meus_estagios(request, False).exclude(turma="").values_list("turma", flat=True))),
    })


# ----------------------------------------------------------------- contas


@permissao("estagiarios")
def criar_estagiarios(request):
    form = EstagiariosLoteForm(request.POST or None, usuario=request.user, initial={"data_inicio": timezone.localdate(), "dias": [0, 1, 2, 3, 4],
                                                              "horario_entrada": "07:00", "saida_intervalo": "11:00",
                                                              "volta_intervalo": "13:00", "horario_saida": "17:00"})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        criados = []
        with transaction.atomic():
            for nome, matricula in d["nomes"]:
                user = criar_usuario(nome, Usuario.Papel.ESTAGIARIO, request.user, matricula=matricula)
                estagio = Estagio.objects.create(
                    estagiario=user, orientador=d.get("orientador") or request.user, supervisor=d["supervisor"],
                    curso=d["curso"],
                    turma=d["turma"], local=d["local"], setor=d["setor"], data_inicio=d["data_inicio"],
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
            criados = [criar_usuario(nome, Usuario.Papel.SUPERVISOR, request.user, telefone=tel, local=d["local"],
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
    if q:
        qs = qs.filter(Q(nome_completo__icontains=q) | Q(username__icontains=q))
    qs = qs.select_related("local").annotate(n_supervisionados=Count("estagios_supervisionados", distinct=True))
    return render(request, "core/usuarios.html", {
        "usuarios": qs.distinct(), "papel": papel, "q": q, "papeis": Usuario.Papel.choices,
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
        del form.fields["local"], form.fields["cargo"]
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
def locais(request):
    q = request.GET.get("q", "").strip()
    itens = LocalEstagio.objects.annotate(
        n=Count("estagios", filter=Q(estagios__ativo=True), distinct=True),
        n_sup=Count("supervisores", distinct=True),
    )
    if q:
        itens = itens.filter(Q(nome__icontains=q) | Q(razao_social__icontains=q) | Q(cnpj__icontains=q)
                             | Q(cidade__icontains=q))
    return render(request, "core/locais.html", {"itens": itens, "q": q})


@permissao("cadastros")
def local_editar(request, pk=None):
    """Ficha da concedente (dados gerais, endereço, representante legal) + cadastro rápido de supervisores."""
    obj = get_object_or_404(LocalEstagio, pk=pk) if pk else None
    form = LocalForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            local = form.save()
            criados = [criar_usuario(nome, Usuario.Papel.SUPERVISOR, request.user, telefone=tel, local=local)
                       for nome, tel in form.cleaned_data["novos_supervisores"]]
        messages.success(request, f"Concedente “{local}” salva.")
        if criados:
            return _resultado_contas(request, criados, f"Supervisores de {local}")
        return redirect("locais")
    supervisores = obj.supervisores.order_by("nome_completo") if obj else []
    return render(request, "core/concedente_form.html", {"form": form, "obj": obj, "supervisores": supervisores})


@orientador_requerido
def configuracoes(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    config = Configuracao.atual()
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
    })



@permissao("feriados")
def dias_sem_estagio(request):
    form = DiaSemEstagioForm(request.POST or None)
    if request.method == "POST":
        if "excluir" in request.POST:
            DiaSemEstagio.objects.filter(pk=request.POST["excluir"], orientador=request.user).delete()
            messages.success(request, "Data removida.")
            return redirect("dias_sem_estagio")
        if form.is_valid():
            d = form.cleaned_data
            dia, ate = d["data"], d.get("ate") or d["data"]
            n = 0
            while dia <= ate:
                DiaSemEstagio.objects.get_or_create(
                    data=dia, orientador=request.user, curso=d["curso"], defaults={"descricao": d["descricao"]}
                )
                dia += timedelta(days=1)
                n += 1
            estagios = _meus_estagios(request)
            if d["curso"]:
                estagios = estagios.filter(curso=d["curso"])
            pessoas = [p for e in estagios for p in (e.estagiario, e.supervisor)]
            periodo = f"{d['data']:%d/%m}" + (f" a {ate:%d/%m}" if ate != d["data"] else "")
            notificar(pessoas, f"Sem estágio em {periodo}: {d['descricao']}.", reverse("inicio"))
            messages.success(request, f"{n} dia(s) marcados como sem estágio.")
            return redirect("dias_sem_estagio")
    hoje = timezone.localdate()
    itens = DiaSemEstagio.objects.filter(orientador=request.user).select_related("curso")
    return render(request, "core/dias_sem_estagio.html", {
        "form": form, "futuros": itens.filter(data__gte=hoje), "passados": itens.filter(data__lt=hoje).reverse()[:30],
    })


# ----------------------------------------------------------------- alterações em lote


@permissao("escalas")
def escala_lote(request):
    qs = _meus_estagios(request)
    filtro_curso = request.GET.get("curso", "")
    filtro_turma = request.GET.get("turma", "")
    if filtro_curso:
        qs = qs.filter(curso_id=filtro_curso)
    if filtro_turma:
        qs = qs.filter(turma=filtro_turma)
    form = EscalaLoteForm(request.POST or None, estagios_qs=qs, initial={"dias": [0, 1, 2, 3, 4]})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        with transaction.atomic():
            for e in d["estagios"]:
                Escala.objects.update_or_create(
                    estagio=e, vigente_desde=d["vigente_desde"],
                    defaults={**form.dados_escala(), "criado_por": request.user},
                )
        exemplo = Escala(dias=form.dados_escala()["dias"])
        pessoas = [p for e in d["estagios"] for p in (e.estagiario, e.supervisor)]
        notificar(pessoas, f"Mudança nos dias de estágio a partir de {d['vigente_desde']:%d/%m}: "
                  f"{exemplo.dias_display}.", reverse("inicio"))
        messages.success(request, f"Nova escala aplicada a {len(d['estagios'])} estagiário(s) a partir de "
                                  f"{d['vigente_desde']:%d/%m/%Y}.")
        return redirect("estagios_lista")
    turmas = sorted(set(_meus_estagios(request).exclude(turma="").values_list("turma", flat=True)))
    return render(request, "core/escala_lote.html", {
        "form": form, "cursos": Curso.objects.all(), "turmas": turmas,
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
