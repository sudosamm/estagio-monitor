"""Envio das sugestões e relatos de erro por e-mail (com os anexos)."""
import logging
import threading

from django.conf import settings
from django.core.mail import EmailMessage
from .threads import fechar_conexoes_da_thread
from django.utils import timezone

from .models import Configuracao, Sugestao, Usuario

log = logging.getLogger("core.sugestoes")


def destinatarios():
    cfg = Configuracao.atual()
    if cfg.email_sugestoes:
        return [cfg.email_sugestoes]
    if settings.SUGESTOES_EMAIL:
        return [e.strip() for e in settings.SUGESTOES_EMAIL.split(",") if e.strip()]
    return list(Usuario.objects.filter(is_superuser=True, is_active=True).exclude(email="")
                .values_list("email", flat=True))


def montar_email(s):
    quem = (f"{s.usuario.nome_completo} ({s.usuario.username} · {s.usuario.get_papel_display()})" if s.usuario
            else "visitante (não estava logado)")
    corpo = "\n".join([
        f"Tipo: {s.get_tipo_display()}",
        f"Nome informado: {s.nome}",
        f"E-mail para resposta: {s.email or '—'}",
        f"Conta: {quem}",
        f"Página: {s.pagina or '—'}",
        f"Navegador: {s.navegador or '—'}",
        f"Enviado em: {timezone.localtime(s.criado_em):%d/%m/%Y %H:%M}",
        "",
        "Mensagem:",
        s.mensagem,
        "",
        f"Anexos: {s.anexos.count()}" if s.anexos.exists() else "Sem anexos.",
        "—",
        f"Enviado pela página “Sugestões e erros” do {settings.NOME_SISTEMA}. Responder este e-mail responde a "
        "quem enviou (se informou o e-mail).",
    ])
    resumo = " ".join(s.mensagem.split())[:60]
    msg = EmailMessage(subject=f"[{settings.NOME_SISTEMA}] {s.get_tipo_display()}: {resumo}", body=corpo,
                       from_email=settings.DEFAULT_FROM_EMAIL, to=destinatarios(),
                       reply_to=[s.email] if s.email else None)
    for a in s.anexos.all():
        with a.arquivo.open("rb") as f:
            msg.attach(a.nome_original, f.read())
    return msg


def enviar(sugestao_id, assincrono=None):
    def rodar():
        try:
            s = Sugestao.objects.select_related("usuario").get(pk=sugestao_id)
            msg = montar_email(s)
            if not msg.to:
                log.warning("Sugestão %s guardada, mas sem e-mail de destino configurado", sugestao_id)
                return
            msg.send(fail_silently=False)
            Sugestao.objects.filter(pk=sugestao_id).update(enviada_em=timezone.now())
        except Exception:  # noqa: BLE001 — a mensagem já está guardada no sistema; o e-mail é um extra
            log.exception("Falha ao enviar a sugestão %s por e-mail", sugestao_id)
        finally:
            if assincrono_:
                fechar_conexoes_da_thread()

    assincrono_ = settings.EMAIL_ASSINCRONO if assincrono is None else assincrono
    if not settings.EMAIL_ATIVO:
        return
    if assincrono_:
        threading.Thread(target=rodar, daemon=True).start()
    else:
        rodar()
