"""Notificações no celular (Web Push): chaves VAPID, inscrição de cada aparelho e envio.

Funciona no app instalado (Android e iPhone com iOS 16.4+, adicionado à tela de início) e em navegadores de
computador. Não usa serviço pago: o próprio navegador entrega pela infraestrutura do Google, Apple ou Mozilla.
"""
import base64
import json
import logging
import threading

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from .models import InscricaoPush

log = logging.getLogger("core.push")
_trava = threading.Lock()
_vapid = None


def _chave():
    """Chave privada VAPID: criada na primeira vez e guardada no volume de dados."""
    global _vapid
    if _vapid is not None:
        return _vapid
    from py_vapid import Vapid02

    with _trava:
        if _vapid is None:
            arquivo = settings.VAPID_ARQUIVO
            if arquivo.exists():
                v = Vapid02.from_file(str(arquivo))
            else:
                v = Vapid02()
                v.generate_keys()
                arquivo.parent.mkdir(parents=True, exist_ok=True)
                v.save_key(str(arquivo))
                arquivo.chmod(0o600)
            _vapid = v
    return _vapid


def chave_publica():
    """applicationServerKey para o navegador (ponto não comprimido, base64url sem “=”)."""
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    bruto = _chave().public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(bruto).rstrip(b"=").decode()


def push_ativo():
    return settings.PUSH_ATIVO


def _enviar_agora(itens):
    """itens: [(inscricao_pk, dados_inscricao, payload_json)]."""
    from pywebpush import WebPushException, webpush

    vapid = _chave()
    mortas, ok = [], []
    for pk, dados, payload in itens:
        try:
            webpush(dados, data=payload, vapid_private_key=vapid, vapid_claims={"sub": settings.VAPID_CONTATO},
                    ttl=24 * 3600, timeout=10)
            ok.append(pk)
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):  # o celular cancelou ou a inscrição expirou
                mortas.append(pk)
            else:
                log.warning("Push falhou (%s): %s", status, exc)
        except Exception:  # noqa: BLE001 — rede fora do ar não pode derrubar nada
            log.exception("Push falhou")
    if mortas:
        InscricaoPush.objects.filter(pk__in=mortas).delete()
    if ok:
        InscricaoPush.objects.filter(pk__in=ok).update(ultimo_envio=timezone.now())
    return len(ok)


def enviar(notificacoes, assincrono=None):
    """Envia cada notificação (objetos Notificacao já salvos) aos celulares do destinatário."""
    if not push_ativo() or not notificacoes:
        return 0
    from django.urls import reverse

    por_usuario = {}
    for n in notificacoes:
        por_usuario.setdefault(n.usuario_id, []).append(n)
    itens = []
    for insc in InscricaoPush.objects.filter(usuario_id__in=por_usuario):
        for n in por_usuario[insc.usuario_id]:
            payload = json.dumps({
                "titulo": settings.NOME_SISTEMA, "texto": n.texto,
                "url": reverse("notificacao_abrir", args=[n.pk]) if n.pk else (n.link or "/"),
                "tag": f"n{n.pk}",
            }, ensure_ascii=False)
            itens.append((insc.pk, insc.dados, payload))
    if not itens:
        return 0
    assincrono = settings.EMAIL_ASSINCRONO if assincrono is None else assincrono
    if not assincrono:
        return _enviar_agora(itens)

    def rodar():
        try:
            _enviar_agora(itens)
        finally:
            close_old_connections()

    threading.Thread(target=rodar, daemon=True).start()
    return len(itens)
