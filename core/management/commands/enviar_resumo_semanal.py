"""Envia o resumo semanal por e-mail aos orientadores e coordenadores.

Normalmente não é preciso: o sistema envia sozinho no primeiro acesso depois de segunda, 6h.
Use este comando para agendar no cron/Coolify (com RESUMO_AUTOMATICO=0) ou para testar.
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.acompanhamento import destinatarios_resumo, enviar_resumos, mensagem_resumo, resumo_pendente, resumo_semanal
from core.models import Configuracao, Usuario


class Command(BaseCommand):
    help = "Envia o resumo semanal por e-mail (uma vez por semana, a não ser com --forcar)."

    def add_arguments(self, parser):
        parser.add_argument("--forcar", action="store_true", help="Envia mesmo que o desta semana já tenha saído.")
        parser.add_argument("--usuario", help="Envia só para este usuário (não marca a semana como enviada).")
        parser.add_argument("--mostrar", action="store_true", help="Só mostra o texto no terminal, sem enviar.")

    def handle(self, *args, forcar=False, usuario=None, mostrar=False, **opts):
        if usuario:
            pessoas = Usuario.objects.filter(username=usuario)
            if not pessoas:
                raise CommandError(f"Usuário {usuario} não encontrado.")
        else:
            pessoas = destinatarios_resumo()
        if mostrar:
            for u in pessoas:
                assunto, corpo, _, para = mensagem_resumo(u, resumo_semanal(u))
                self.stdout.write(f"Para: {para[0] or '(sem e-mail)'}\nAssunto: {assunto}\n\n{corpo}\n{'=' * 60}")
            return
        if not settings.EMAIL_ATIVO:
            raise CommandError("Servidor de e-mail não configurado (EMAIL_HOST).")
        if not usuario:
            pendente, _ = resumo_pendente()
            if not pendente and not forcar:
                self.stdout.write("O resumo desta semana já foi enviado (ou está desligado). Use --forcar para reenviar.")
                return
            Configuracao.objects.filter(pk=1).update(resumo_enviado_em=timezone.now())
        n = enviar_resumos(usuarios=pessoas)
        self.stdout.write(self.style.SUCCESS(f"Resumo enviado para {n} pessoa(s)."))
