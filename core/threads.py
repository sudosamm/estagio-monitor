"""Tarefas em segundo plano (threads) e o banco de dados."""
from django.db import connections


def fechar_conexoes_da_thread():
    """Fecha as conexões que esta thread abriu. Chame no ``finally`` de toda thread que usa o banco.

    Com PostgreSQL e ``CONN_MAX_AGE > 0``, o ``close_old_connections()`` mantém a conexão aberta (ela ainda não
    “envelheceu”), e cada thread de e-mail ou push deixaria uma conexão parada no servidor até o processo acabar.
    As conexões do Django são por thread, então isto não afeta a requisição que criou a thread.
    """
    connections.close_all()


def iniciar_thread(funcao):
    """Roda ``funcao`` numa thread em segundo plano **com o mesmo contexto** (a escola atual da requisição).

    Threads novas não herdam os contextvars; sem isto, o envio de e-mails e pushes perderia a escola e, num banco
    com várias escolas, as consultas falhariam fechado (EscopoAusente)."""
    import contextvars
    import threading

    contexto = contextvars.copy_context()
    t = threading.Thread(target=contexto.run, args=(funcao,), daemon=True)
    t.start()
    return t
