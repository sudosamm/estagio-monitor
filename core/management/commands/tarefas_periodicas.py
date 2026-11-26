"""Roda as tarefas com hora marcada de todas as escolas (para as Scheduled Tasks do Coolify).

    python manage.py tarefas_periodicas

Agende a cada 10 ou 15 minutos. Cada tarefa só envia quando chegou a hora e uma vez por período, então rodar mais
vezes não repete nada. O disparo pelo movimento do sistema (RESUMO_AUTOMATICO=1) continua como reserva.
"""
from django.core.management.base import BaseCommand, CommandError

from core.tarefas import rodar_tarefas


class Command(BaseCommand):
    help = "Roda as tarefas periódicas (resumos, lembretes, confirmações, limpezas) de todas as escolas."

    def handle(self, *args, **opts):
        from core.threads import aguardar_threads

        falhas = rodar_tarefas()
        # e-mails e pushes saem em threads daemon: sem esperar, morreriam com o processo (e a semana já foi reservada)
        if restantes := aguardar_threads():
            self.stderr.write(f"{restantes} envio(s) em segundo plano ainda não terminaram após 120 s.")
        com_falha = {k: v for k, v in falhas.items() if v}
        self.stdout.write(f"Tarefas rodadas: {len(falhas) - 1} escola(s) e a plataforma.")
        if com_falha:
            raise CommandError("Falhas: " + "; ".join(f"{k}: {', '.join(v)}" for k, v in com_falha.items()))
        self.stdout.write(self.style.SUCCESS("Sem falhas."))
