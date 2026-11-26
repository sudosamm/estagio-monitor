"""Tarefas em segundo plano (threads) e o banco de dados."""
from django.db import connections


def fechar_conexoes_da_thread():
    """Fecha as conexões que esta thread abriu. Chame no ``finally`` de toda thread que usa o banco.

    Com PostgreSQL e ``CONN_MAX_AGE > 0``, o ``close_old_connections()`` mantém a conexão aberta (ela ainda não
    “envelheceu”), e cada thread de e-mail ou push deixaria uma conexão parada no servidor até o processo acabar.
    As conexões do Django são por thread, então isto não afeta a requisição que criou a thread.
    """
    connections.close_all()

