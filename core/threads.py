"""Tarefas em segundo plano (threads) e o banco de dados.

Regra: **só a thread criada aqui fecha as conexões, e ela mesma, ao terminar** (``iniciar_thread`` envolve a função
num ``try/finally``). O caminho síncrono (``EMAIL_ASSINCRONO=False``, nos testes e onde mais for usado) nunca fecha
nada: ele roda na thread da requisição, do comando ou do teste, e fechar ali derrubaria a conexão de quem chamou
(o SQLite em memória ignora o ``close``; o PostgreSQL fecha de verdade).

As conexões do Django são por thread. Por isso vale também com o Gunicorn em ``gthread``: cada requisição roda numa
thread do pool, com a sua conexão, e a thread de e-mail ou push abre e fecha a dela, sem tocar na da requisição.
"""
import contextvars
import threading
import weakref

from django.db import connections

_ativas = weakref.WeakSet()


def fechar_conexoes_da_thread():
    """Fecha as conexões que a thread atual abriu. Use só no fim de uma thread própria (``iniciar_thread`` já faz).

    Com PostgreSQL e ``CONN_MAX_AGE > 0``, o ``close_old_connections()`` mantém a conexão aberta (ela ainda não
    “envelheceu”), e cada thread de e-mail ou push deixaria uma conexão parada no servidor até o processo acabar.
    """
    connections.close_all()


def iniciar_thread(funcao):
    """Roda ``funcao`` numa thread em segundo plano **com o mesmo contexto** (contextvars) e, ao terminar, fecha as
    conexões com o banco que essa thread abriu — mesmo se ``funcao`` falhar.

    Threads novas não herdam os contextvars; sem a cópia, o que a requisição guardou neles (como a escola atual) se
    perderia no envio de e-mails e pushes."""
    contexto = contextvars.copy_context()

    def rodar():
        try:
            funcao()
        finally:
            fechar_conexoes_da_thread()

    t = threading.Thread(target=contexto.run, args=(rodar,), daemon=True)
    _ativas.add(t)
    t.start()
    return t


def aguardar_threads(limite=120):
    """Espera as threads em segundo plano terminarem (até ``limite`` segundos no total). Devolve quantas ainda
    rodam. Para comandos de vida curta (``tarefas_periodicas``): as threads são daemon e morreriam com o processo,
    levando junto os e-mails que ainda não saíram."""
    import time

    fim = time.monotonic() + limite
    for t in list(_ativas):
        if t is not threading.current_thread():
            t.join(max(0, fim - time.monotonic()))
    return sum(1 for t in list(_ativas) if t.is_alive())
