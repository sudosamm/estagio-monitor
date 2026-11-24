"""Captação de concedentes: página pública de cadastro e análise pelo orientador/coordenador."""
from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..forms import AprovarCandidaturaForm, CandidaturaForm, RecusarCandidaturaForm
from ..models import AvisoExterno, Candidatura, Configuracao, Curso, LocalEstagio, VagaCandidatura
from ..services import aprovar_candidatura, gestores_da_candidatura, notificar, recusar_candidatura
from ..validators import so_digitos
from .base import permissao
from .frequencia import _ip

LIMITE_POR_HORA = 5


def candidatura_publica(request):
    """Aberta, sem login: a concedente se candidata para o ano letivo da captação."""
    config = Configuracao.atual()
    if not config.captacao_disponivel:
        return render(request, "core/captacao_publica.html", {"config": config, "fechada": True})
    form = CandidaturaForm(request.POST or None)
    if request.method == "POST":
        ip = _ip(request)
        recentes = Candidatura.objects.filter(ip=ip, criado_em__gte=timezone.now() - timedelta(hours=1)).count()
        if ip and recentes >= LIMITE_POR_HORA:
            messages.error(request, "Muitos envios em pouco tempo. Tente de novo mais tarde.")
        elif form.is_valid():
            form.instance.ano, form.instance.ip = config.ano_captacao_efetivo, ip
            cand = form.save()
            notificar(gestores_da_candidatura(cand), f"Nova concedente na captação {cand.ano}: {cand.nome} "
                      f"({cand.total_vagas} vaga(s)).", cand.get_absolute_url())
            return render(request, "core/captacao_publica.html", {"config": config, "enviada": cand})
    return render(request, "core/captacao_publica.html", {"config": config, "form": form})


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
                messages.info(request, "Agora avise a concedente: a mensagem está pronta na página da candidatura.")
                novos = [u for u in dict.fromkeys([supervisor, cand._responsavel]) if u]
                if cand._responsavel:  # os códigos só aparecem agora: a folha já sai pronta para entregar
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
