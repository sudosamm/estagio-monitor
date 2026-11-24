"""Captação de concedentes: página pública de cadastro e análise pelo orientador/coordenador."""
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .. import emails, termos
from ..forms import AprovarCandidaturaForm, CandidaturaForm, RecusarCandidaturaForm
from ..models import AvisoExterno, Candidatura, Configuracao, Curso, LocalEstagio, Usuario, VagaCandidatura
from ..services import aprovar_candidatura, gestores_da_candidatura, notificar, recusar_candidatura
from ..validators import so_digitos
from .base import permissao
from .frequencia import _ip

LIMITE_POR_HORA = 5


def _modo(user):
    if not user.is_authenticated:
        return "publico"
    if user.pode("candidaturas"):
        return "escola"
    if user.is_supervisor:
        return "conta"
    return None  # estagiário: o cadastro é para empresas e órgãos


def candidatura_publica(request):
    """Cadastro da concedente na captação. Sem login, quem preenche cria a própria conta junto; com conta de
    supervisor/responsável, manda pela conta; orientador/coordenador preenche a pedido da concedente."""
    config = Configuracao.atual()
    modo = _modo(request.user)
    if modo is None:
        return render(request, "core/captacao_publica.html", {"config": config, "sem_acesso": True})
    if not config.captacao_disponivel and modo != "escola":
        return render(request, "core/captacao_publica.html", {"config": config, "fechada": True})
    inicial = {}
    if modo == "conta":
        u = request.user
        inicial = {"contato_nome": u.nome_completo, "contato_cargo": u.cargo, "contato_telefone": u.telefone,
                   "contato_email": u.email}
    form = CandidaturaForm(request.POST or None, modo=modo, initial=inicial)
    if request.method == "POST":
        ip = _ip(request)
        recentes = Candidatura.objects.filter(ip=ip, criado_em__gte=timezone.now() - timedelta(hours=1)).count()
        if modo != "escola" and ip and recentes >= LIMITE_POR_HORA:
            messages.error(request, "Muitos envios em pouco tempo. Tente de novo mais tarde.")
        elif form.is_valid():
            with transaction.atomic():
                form.instance.ano, form.instance.ip = config.ano_captacao_efetivo, ip
                if modo == "escola":
                    form.instance.preenchido_por = Candidatura.PreenchidoPor.ESCOLA
                    form.instance.cadastrada_por = request.user
                elif modo == "conta":
                    form.instance.conta = request.user
                cand = form.save()
                conta = None
                if modo == "publico":
                    conta = criar_conta_da_candidatura(cand, form.cleaned_data["senha1"])
            notificar(gestores_da_candidatura(cand), f"Nova concedente na captação {cand.ano}: {cand.nome} "
                      f"({cand.total_vagas} vaga(s)).", cand.get_absolute_url(), exceto=request.user)
            if modo == "escola":
                messages.success(request, f"Cadastro de {cand.nome} registrado (protocolo {cand.protocolo}). "
                                          "Agora é só analisar.")
                return redirect(cand)
            if conta:
                termos.registrar_aceite(conta, request)
                login(request, conta, backend="core.seguranca.BackendComLimite")
                emails.enviar_confirmacao(request, conta)
            return render(request, "core/captacao_publica.html", {"config": config, "enviada": cand, "conta": conta})
    return render(request, "core/captacao_publica.html", {"config": config, "form": form, "modo": modo})


def criar_conta_da_candidatura(cand, senha):
    """Conta de quem preencheu (papel de supervisor, ainda sem concedente: só vê a candidatura até a aprovação)."""
    from ..services import criar_usuario

    conta = criar_usuario(cand.contato_nome, Usuario.Papel.SUPERVISOR, telefone=cand.contato_telefone,
                          email=cand.contato_email, cargo=cand.contato_cargo)
    conta.set_password(senha)
    conta.deve_trocar_senha = False
    conta.save(update_fields=["password", "deve_trocar_senha"])
    cand.conta = conta
    cand.save(update_fields=["conta"])
    return conta


@login_required
def minhas_candidaturas(request):
    """Para quem mandou o cadastro: andamento e decisão da escola."""
    cands = list(Candidatura.objects.filter(conta=request.user).prefetch_related("vagas__curso")
                 .select_related("analisado_por", "local"))
    if len(cands) == 1 and not request.user.vinculado_a_concedente:
        return redirect("minha_candidatura", pk=cands[0].pk)
    config = Configuracao.atual()
    return render(request, "core/minhas_candidaturas.html", {"candidaturas": cands, "config": config})


@login_required
def minha_candidatura(request, pk):
    cand = get_object_or_404(Candidatura.objects.prefetch_related("vagas__curso").select_related("analisado_por", "local"),
                             pk=pk, conta=request.user)
    config = Configuracao.atual()
    return render(request, "core/minha_candidatura.html", {"c": cand, "config": config,
                                                          "outras": Candidatura.objects.filter(conta=request.user).count() > 1})


@login_required
def editar_candidatura(request, pk):
    """Dados e vagas mudam só enquanto a escola não decidiu. Aprovada, as vagas ficam como foram aceitas."""
    cand = get_object_or_404(Candidatura.objects.prefetch_related("vagas__curso"), pk=pk)
    if not (cand.conta_id == request.user.pk or cand.pode_ver(request.user)):
        raise PermissionDenied
    voltar = cand.get_absolute_url() if request.user.pode("candidaturas") else reverse("minha_candidatura", args=[pk])
    if not cand.pode_alterar(request.user):
        messages.info(request, "Este cadastro já foi analisado pela escola: os dados e as vagas não mudam mais. "
                               "Para mudar algo, fale com a escola.")
        return redirect(voltar)
    form = CandidaturaForm(request.POST or None, instance=cand, modo="editar")
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.instance.alterada_em = timezone.now()
            cand = form.save()  # dados e vagas
        if request.user.pk == cand.conta_id:
            notificar(gestores_da_candidatura(cand), f"{cand.nome} alterou o cadastro da captação "
                      f"({cand.total_vagas} vaga(s)).", cand.get_absolute_url())
        messages.success(request, "Cadastro atualizado.")
        return redirect(voltar)
    return render(request, "core/captacao_publica.html", {"config": Configuracao.atual(), "form": form,
                                                          "modo": "editar", "c": cand, "voltar": voltar})


def _candidaturas_de(user):
    qs = Candidatura.objects.all()
    if user.is_coordenador and user.cursos_ids():
        qs = qs.filter(vagas__curso_id__in=user.cursos_ids()).distinct()
    return qs


@permissao("candidaturas")
def captacao_lista(request):
    config = Configuracao.atual()
    anos = sorted(set(Candidatura.objects.values_list("ano", flat=True)) | {config.ano_captacao_efetivo}, reverse=True)
    try:
        ano = int(request.GET.get("ano") or config.ano_captacao_efetivo)
    except ValueError:
        ano = config.ano_captacao_efetivo
    status = request.GET.get("status", "")
    base = _candidaturas_de(request.user).filter(ano=ano)
    qs = base.filter(status=status) if status else base
    candidaturas = qs.prefetch_related("vagas__curso").select_related("analisado_por")

    # resumo de vagas por curso (pendentes e aprovadas)
    cursos = Curso.objects.all()
    if request.user.is_coordenador and request.user.cursos_ids():
        cursos = cursos.filter(pk__in=request.user.cursos_ids())
    vagas = VagaCandidatura.objects.filter(candidatura__in=base)
    resumo = []
    for c in cursos:
        doc = vagas.filter(curso=c)
        resumo.append({
            "curso": c,
            "aprovadas": doc.filter(candidatura__status=Candidatura.Status.APROVADA).aggregate(s=Sum("quantidade"))["s"] or 0,
            "pendentes": doc.filter(candidatura__status=Candidatura.Status.PENDENTE).aggregate(s=Sum("quantidade"))["s"] or 0,
            "concedentes": doc.filter(candidatura__status=Candidatura.Status.APROVADA).count(),
        })
    contagem = {s: base.filter(status=s).count() for s in Candidatura.Status.values}
    return render(request, "core/captacao_lista.html", {
        "config": config, "ano": ano, "anos": anos, "status": status, "candidaturas": candidaturas,
        "resumo": resumo, "contagem": contagem, "status_choices": Candidatura.Status.choices,
        "link_publico": request.build_absolute_uri("/seja-concedente/"),
    })


def _sugestoes(cand):
    """Concedentes já cadastradas que parecem ser a mesma (CNPJ ou nome)."""
    filtro = Q(nome__iexact=cand.nome) | Q(razao_social__iexact=cand.razao_social)
    achadas = list(LocalEstagio.objects.filter(filtro)[:5])
    digitos = so_digitos(cand.cnpj)
    if digitos:
        for l in LocalEstagio.objects.exclude(cnpj=""):
            if so_digitos(l.cnpj) == digitos and l not in achadas:
                achadas.insert(0, l)
    return achadas


@permissao("candidaturas")
def captacao_detalhe(request, pk):
    cand = get_object_or_404(Candidatura.objects.prefetch_related("vagas__curso"), pk=pk)
    if not cand.pode_ver(request.user):
        raise PermissionDenied
    sugestoes = _sugestoes(cand) if cand.status == Candidatura.Status.PENDENTE else []
    aprovar = AprovarCandidaturaForm(prefix="a", candidatura=cand, sugestoes=sugestoes)
    recusar = RecusarCandidaturaForm(prefix="r")
    if request.method == "POST" and cand.status == Candidatura.Status.PENDENTE:
        endereco = request.build_absolute_uri("/")
        if request.POST.get("acao") == "aprovar":
            aprovar = AprovarCandidaturaForm(request.POST, prefix="a", candidatura=cand, sugestoes=sugestoes)
            if aprovar.is_valid():
                d = aprovar.cleaned_data
                local, supervisor, _ = aprovar_candidatura(cand, request.user, d["destino"], d.get("criar_supervisor"),
                                                           d["parecer"], endereco, d.get("criar_responsavel"))
                messages.success(request, f"{cand.nome} aprovada e cadastrada como concedente."
                                 + (f" Conta do supervisor: {supervisor.username}." if supervisor else ""))
                if cand._conta_vinculada:
                    messages.info(request, f"A conta de {cand._conta_vinculada.nome_completo} (quem preencheu) agora é "
                                           "responsável pela concedente e já recebeu o aviso no sistema.")
                messages.info(request, "Agora avise a concedente: a mensagem está pronta na página da candidatura.")
                novos = [u for u in dict.fromkeys([supervisor, cand._responsavel]) if u and u.deve_trocar_senha]
                if cand._responsavel and novos:  # os códigos só aparecem agora: a folha já sai pronta para entregar
                    from .orientador import folha_primeiro_acesso

                    return folha_primeiro_acesso(request, novos, f"Acesso da concedente {local}")
                return redirect(cand)
        elif request.POST.get("acao") == "recusar":
            recusar = RecusarCandidaturaForm(request.POST, prefix="r")
            if recusar.is_valid():
                recusar_candidatura(cand, request.user, recusar.cleaned_data["parecer"])
                messages.success(request, "Candidatura recusada. Se quiser, avise a concedente com a mensagem abaixo.")
                return redirect(cand)
    return render(request, "core/captacao_detalhe.html", {
        "c": cand, "aprovar": aprovar, "recusar": recusar, "sugestoes": sugestoes,
        "avisos": cand.avisos.select_related("enviado_por"),
    })


@permissao("candidaturas")
@require_POST
def aviso_enviado(request, pk):
    """Marca o aviso como enviado (ou descartado), guardando o texto final que foi mandado."""
    aviso = get_object_or_404(AvisoExterno.objects.select_related("candidatura"), pk=pk)
    if aviso.candidatura and not aviso.candidatura.pode_ver(request.user):
        raise PermissionDenied
    canal = request.POST.get("canal", "")
    if canal == "descartar":
        aviso.status = AvisoExterno.Status.DESCARTADO
    elif canal in AvisoExterno.Canal.values:
        aviso.status, aviso.canal = AvisoExterno.Status.ENVIADO, canal
        aviso.enviado_por, aviso.enviado_em = request.user, timezone.now()
    else:
        raise PermissionDenied
    texto = request.POST.get("mensagem", "").strip()
    if texto:
        aviso.mensagem = texto
    aviso.save()
    messages.success(request, "Aviso registrado." if aviso.status == AvisoExterno.Status.ENVIADO else "Aviso descartado.")
    return redirect(aviso.candidatura or "captacao")
