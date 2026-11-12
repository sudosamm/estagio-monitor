"""Atestados e comprovantes: o estagiário envia, o supervisor ou a escola aceita ou recusa."""
import io

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string

from .models import Configuracao, DiaPlanejado, HistoricoRegistro, Justificativa, Registro
from .services import notificar, status_periodo

LADO_MAX = 2000  # px: foto legível e leve


class ArquivoInvalido(ValueError):
    pass


def preparar_arquivo(arquivo):
    """Foto → JPEG sem metadados (tira localização do GPS), girada certo e reduzida; PDF passa como está."""
    if arquivo.size > settings.TAMANHO_MAX_ANEXO_MB * 1024 * 1024:
        raise ArquivoInvalido(f"O arquivo deve ter no máximo {settings.TAMANHO_MAX_ANEXO_MB} MB.")
    inicio = arquivo.read(5)
    arquivo.seek(0)
    if inicio == b"%PDF-":
        return ContentFile(arquivo.read(), name=f"{get_random_string(12)}.pdf")
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        img = Image.open(arquivo)
        img = ImageOps.exif_transpose(img).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise ArquivoInvalido("Formato não reconhecido. Envie uma foto (JPG ou PNG) ou um PDF.") from exc
    img.thumbnail((LADO_MAX, LADO_MAX), Image.Resampling.LANCZOS)
    saida = io.BytesIO()
    img.save(saida, "JPEG", quality=85, optimize=True)
    return ContentFile(saida.getvalue(), name=f"{get_random_string(12)}.jpg")


def dias_cobertos(estagio, inicio, fim):
    """Dias de estágio do período que o documento pode justificar (não mexe em presença nem em ausência já aceita)."""
    dias = []
    for s in status_periodo(estagio, inicio, fim):
        reg = s.registro
        if reg:
            if reg.situacao == Registro.Situacao.PRESENTE:
                continue
            if reg.situacao == Registro.Situacao.AUSENCIA and reg.confirmacao == Registro.Confirmacao.CONFIRMADA:
                continue
            dias.append(s.data)
        elif s.previsto:
            dias.append(s.data)
    return dias


def quem_decide(estagio):
    pessoas = [estagio.orientador]
    if estagio.supervisor and Configuracao.atual().atestados_supervisor:
        pessoas.append(estagio.supervisor)
    return pessoas


@transaction.atomic
def registrar_justificativa(estagio, usuario, tipo, inicio, fim, motivo, arquivo, nome_original, request=None):
    """Cria o atestado e põe os dias em “ausência” aguardando análise. Enviado pela escola já sai aceito."""
    dias = dias_cobertos(estagio, inicio, fim)
    if not dias:
        raise ArquivoInvalido("Nenhum dia de estágio nesse período para justificar (fins de semana, feriados e dias "
                              "com presença ou ausência já aceita ficam de fora).")
    j = Justificativa.objects.create(
        estagio=estagio, tipo=tipo, data_inicio=inicio, data_fim=fim, motivo=motivo, arquivo=arquivo,
        nome_original=nome_original[:255], dias=[d.isoformat() for d in dias], enviado_por=usuario,
    )
    texto = j.get_tipo_display() + (f": {motivo}" if motivo else "")
    existentes = {r.data: r for r in estagio.registros.filter(data__in=dias)}
    for dia in dias:
        reg = existentes.get(dia) or Registro(estagio=estagio, data=dia)
        reg.situacao, reg.horas, reg.motivo = Registro.Situacao.AUSENCIA, 0, texto[:500]
        reg.confirmacao, reg.justificativa, reg.registrado_por = Registro.Confirmacao.PENDENTE, j, usuario
        reg.anotar(usuario, HistoricoRegistro.Acao.AUSENCIA, request).save()
    DiaPlanejado.objects.filter(estagio=estagio, data__in=dias).delete()
    escola = usuario.pk != estagio.estagiario_id and j.pode_decidir(usuario)
    if escola:
        decidir(j, usuario, aceitar=True, parecer="Recebido pela escola.", request=request, avisar=False)
        notificar([estagio.estagiario, estagio.supervisor],
                  f"{usuario.primeiro_nome} registrou {j.get_tipo_display().lower()} de {estagio.estagiario.primeiro_nome}"
                  f" ({j.periodo_display}): {len(dias)} dia(s) justificado(s).", j.get_absolute_url(), exceto=usuario)
    else:
        notificar(quem_decide(estagio),
                  f"{estagio.estagiario} enviou {j.get_tipo_display().lower()} ({j.periodo_display}, {len(dias)} dia"
                  f"{'s' if len(dias) > 1 else ''}) para análise.", j.get_absolute_url(), exceto=usuario)
    return j


@transaction.atomic
def decidir(j, usuario, aceitar, parecer="", request=None, avisar=True):
    """Aceito: os dias viram ausência justificada. Recusado: dias passados viram falta; dias futuros voltam ao normal."""
    hoje = timezone.localdate()
    j.status = Justificativa.Status.ACEITA if aceitar else Justificativa.Status.RECUSADA
    j.decidido_por, j.decidido_em, j.parecer = usuario, timezone.now(), parecer
    j.save()
    for reg in j.registros.all():
        if aceitar:
            reg.confirmar(usuario, Registro.Confirmacao.CONFIRMADA, parecer)
            reg.anotar(usuario, HistoricoRegistro.Acao.VALIDACAO, request).save()
        elif reg.data <= hoje:
            reg.situacao = Registro.Situacao.FALTA
            reg.confirmar(usuario, Registro.Confirmacao.CONFIRMADA, f"Atestado recusado: {parecer}"[:500])
            reg.anotar(usuario, HistoricoRegistro.Acao.VALIDACAO, request).save()
        else:
            reg.anotar(usuario, HistoricoRegistro.Acao.EXCLUIU, request).delete()
    if avisar:
        e = j.estagio
        verbo = "aceitou" if aceitar else "recusou"
        notificar([e.estagiario, e.orientador, e.supervisor if Configuracao.atual().atestados_supervisor else None],
                  f"{usuario.primeiro_nome} {verbo} o {j.get_tipo_display().lower()} de {e.estagiario.primeiro_nome} "
                  f"({j.periodo_display}).{'' if aceitar else ' Motivo: ' + parecer[:80]}",
                  reverse("atestado_detalhe", args=[j.pk]), exceto=usuario)
    return j


def pendentes_para(usuario, estagios):
    """Atestados aguardando análise que a pessoa pode decidir, entre os estágios informados."""
    qs = (Justificativa.objects.filter(estagio__in=estagios, status=Justificativa.Status.PENDENTE)
          .select_related("estagio__estagiario", "estagio__supervisor", "estagio__orientador").order_by("criado_em"))
    return [j for j in qs if j.pode_decidir(usuario)]
