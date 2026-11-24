"""Avisos de erro do sistema para os administradores.

Um handler de logging recebe os erros de página (500) e das tarefas em segundo plano (e-mails, resumos,
lembretes). Cada erro vira (ou soma em) um ErroSistema agrupado pela origem, e os administradores recebem um aviso
no sino e por e-mail na primeira vez e, se continuar acontecendo, no máximo a cada 6 horas.
"""
import hashlib
import logging
import os
import threading
import traceback
from datetime import timedelta

INTERVALO_AVISO = timedelta(hours=6)
_local = threading.local()


def _origem(tb_lista):
    """Último trecho do código do próprio sistema (core/ ou monitor/) por onde o erro passou."""
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    escolhido = tb_lista[-1] if tb_lista else None
    for quadro in tb_lista:
        if quadro.filename.startswith(raiz) and "/.venv/" not in quadro.filename and "site-packages" not in quadro.filename:
            escolhido = quadro
    if not escolhido:
        return ""
    arquivo = os.path.relpath(escolhido.filename, raiz) if escolhido.filename.startswith(raiz) else escolhido.filename
    return f"{arquivo}:{escolhido.lineno} em {escolhido.name}"


def registrar_erro(tipo, mensagem, origem, detalhe="", caminho="", metodo="", usuario=None, avisar_email=True):
    from django.db import transaction
    from django.urls import reverse
    from django.utils import timezone

    from .models import ErroSistema, Notificacao, Usuario

    assinatura = hashlib.sha256(f"{tipo}|{origem}|{caminho if not origem else ''}".encode()).hexdigest()
    agora = timezone.now()
    with transaction.atomic():
        erro = ErroSistema.objects.select_for_update().filter(assinatura=assinatura).first()
        if erro:
            erro.ocorrencias += 1
            erro.ultimo_em, erro.mensagem, erro.detalhe = agora, mensagem[:2000], detalhe[-20000:]
            erro.caminho, erro.metodo, erro.usuario = caminho[:255], metodo[:10], usuario
            if erro.resolvido:  # voltou a acontecer depois de marcado como resolvido
                erro.resolvido, erro.avisado_em = False, None
        else:
            erro = ErroSistema(assinatura=assinatura, tipo=tipo[:120], mensagem=mensagem[:2000], origem=origem[:255],
                               detalhe=detalhe[-20000:], caminho=caminho[:255], metodo=metodo[:10], usuario=usuario)
        avisar = erro.avisado_em is None or agora - erro.avisado_em >= INTERVALO_AVISO
        if avisar:
            erro.avisado_em = agora
        erro.save()
    if not avisar:
        return erro
    admins = list(Usuario.objects.filter(is_superuser=True, is_active=True))
    vezes = "" if erro.ocorrencias == 1 else f" ({erro.ocorrencias} vezes)"
    texto = f"Erro no sistema{vezes}: {tipo} em {caminho or origem or 'tarefa em segundo plano'}"
    Notificacao.objects.bulk_create([Notificacao(usuario=u, texto=texto[:255], link=reverse("erros_sistema"))
                                     for u in admins])
    if avisar_email:
        from . import emails

        emails.enviar("ERRO_SISTEMA", [u.email for u in admins if u.email], erro=tipo, mensagem=mensagem[:500],
                      pagina=caminho or "tarefa em segundo plano", origem=origem or "—",
                      ocorrencias=erro.ocorrencias, quando=emails.quando(agora),
                      link=f"{_site()}{reverse('erros_sistema')}")
    return erro


def _site():
    from django.conf import settings

    return settings.SITE_URL or ""


class AlertaErroHandler(logging.Handler):
    """Ligado aos loggers django.request e core (ver LOGGING em settings). Nunca levanta exceção."""

    def emit(self, record):
        if getattr(_local, "ocupado", False):
            return  # erro dentro do próprio aviso: não entra em laço
        _local.ocupado = True
        try:
            from django.apps import apps

            if not apps.ready:
                return
            request = getattr(record, "request", None)
            if record.exc_info and record.exc_info[1] is not None:
                exc = record.exc_info[1]
                tipo = type(exc).__name__
                mensagem = str(exc) or record.getMessage()
                lista = traceback.extract_tb(record.exc_info[2])
                origem = _origem(lista)
                detalhe = "".join(traceback.format_exception(*record.exc_info))
            else:
                tipo, mensagem, origem, detalhe = record.levelname, record.getMessage(), f"{record.name}", ""
            usuario = None
            if request is not None and getattr(request, "user", None) is not None:
                try:
                    usuario = request.user if request.user.is_authenticated else None
                except Exception:  # noqa: BLE001
                    usuario = None
            registrar_erro(
                tipo, mensagem, origem, detalhe=f"{record.getMessage()}\n\n{detalhe}".strip(),
                caminho=getattr(request, "path", "") if request is not None else "",
                metodo=getattr(request, "method", "") if request is not None else "",
                usuario=usuario,
                avisar_email=not record.name.startswith("core.email"),  # e-mail fora do ar não avisa por e-mail
            )
        except Exception:  # noqa: BLE001 — o aviso de erro nunca pode causar outro erro na página
            pass
        finally:
            _local.ocupado = False
