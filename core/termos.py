"""Termos de Uso e Aviso de Privacidade (LGPD).

Os textos ficam em templates/core/termos.html e templates/core/privacidade.html. Ao mudar algo importante neles,
troque VERSAO: todo mundo vê a tela de aceite de novo no próximo acesso.
"""
from django.conf import settings
from django.utils import timezone

VERSAO = "2026.11.25"
ATUALIZADO_EM = "25/11/2026"


def precisa_aceitar(user):
    return (getattr(settings, "EXIGIR_ACEITE_TERMOS", True) and user.is_authenticated
            and user.termos_versao != VERSAO)


def registrar_aceite(user, request=None):
    from . import auditoria

    user.termos_versao, user.termos_aceitos_em = VERSAO, timezone.now()
    user.save(update_fields=["termos_versao", "termos_aceitos_em"])
    auditoria.registrar(request, "TERMOS", f"Aceitou os Termos de Uso e o Aviso de Privacidade (versão {VERSAO})",
                        usuario=user)


def contexto():
    """O que os textos precisam: escola, contato, prazos e o que está ligado no sistema."""
    from .models import Configuracao

    c = Configuracao.atual()
    return {
        "escola": c.nome_escola or "a escola",
        "instituicao": settings.NOME_INSTITUICAO,
        "contato": c.contato_privacidade or c.email_sugestoes or settings.SUGESTOES_EMAIL,
        "retencao": c.retencao_anos,
        "localizacao": c.checkin_localizacao,
        "talentos": c.banco_talentos_habilitado or c.curriculos_habilitados,
        "versao": VERSAO,
        "atualizado_em": ATUALIZADO_EM,
        "guardar_acessos": "1 ano",
        "atestados_supervisor": c.atestados_supervisor,
        "periodo_testes": c.periodo_testes,
    }
