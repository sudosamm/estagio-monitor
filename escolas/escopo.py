"""Escopo por escola: o mecanismo único que separa os dados de cada escola (ADR 0002).

- A **escola atual** fica num contextvar. Numa requisição, o ``EscolaAtualMiddleware`` a define pela conta (vínculos)
  e pela escolha no seletor. Em comandos e tarefas, ``escola_ativa(escola)`` define a escola de um trecho de código.
- Os modelos com escola usam ``EscopoEscolaManager`` como gerenciador padrão (``objects``): toda consulta sai
  filtrada pela escola atual, inclusive as das telas, buscas, exportações, formulários (listas de escolha) e
  ``get_object_or_404`` — um id de outra escola dá 404.
- **Falha fechada:** sem escola definida e com duas ou mais escolas no banco, a consulta levanta ``EscopoAusente``
  em vez de devolver tudo. Com uma escola só (a instalação de hoje), ela é usada sem precisar de nada: o sistema
  continua funcionando igual, e o código não depende de existir mais de uma escola.
- Ver todas as escolas exige um pedido explícito: ``Modelo.objects.todas_as_escolas()`` (administrador da plataforma e
  tarefas que percorrem as escolas) ou o bloco ``with todas_as_escolas():``.
- ``_base_manager`` (usado pelo Django para seguir relações, salvar e apagar) não tem filtro: ``estagio.curso`` sempre
  funciona. O que passa por ``objects`` (e pelos gerenciadores reversos, como ``curso.estagios``) é filtrado.
"""
import contextvars
from contextlib import contextmanager

from django.db import models

ESCOLA_ATUAL = contextvars.ContextVar("escola_atual", default=None)


class _Todas:
    """Marca de "todas as escolas" (só por pedido explícito)."""

    pk = None

    def __repr__(self):
        return "<todas as escolas>"

    def __bool__(self):
        return False


TODAS = _Todas()


class EscopoAusente(Exception):
    """Consulta a dados de escola sem escola definida, num banco com mais de uma escola."""


_cache = {}


def limpar_cache_escola_unica(*args, **kwargs):
    _cache.clear()


def escola_unica():
    """A escola, se houver exatamente uma no banco; senão None. Só o caso "uma escola" fica guardado (até uma escola
    ser criada ou apagada); com várias, consulta de novo a cada vez (e as consultas sem escola falham fechado)."""
    if "unica" in _cache:
        return _cache["unica"]
    from .models import Escola

    primeiras = list(Escola.objects.select_related("rede").order_by("pk")[:2])
    if len(primeiras) != 1:
        return None  # nunca guardado: uma escola criada e desfeita numa transação não deixa o cache errado
    _cache["unica"] = primeiras[0]
    return primeiras[0]


def escola_corrente(obrigatoria=True):
    """A escola em uso: a do contexto; senão a única do banco. ``TODAS`` quando liberado explicitamente.

    Sem escola definida num banco com várias escolas: ``EscopoAusente`` (ou None, com ``obrigatoria=False``).
    """
    atual = ESCOLA_ATUAL.get()
    if atual is not None:
        return atual
    unica = escola_unica()
    if unica is None and obrigatoria:
        raise EscopoAusente("Nenhuma escola definida para esta consulta (há mais de uma escola no sistema).")
    return unica


def escola_corrente_id():
    """Para o ``default`` das colunas ``escola``: o id da escola em uso (None se for "todas")."""
    escola = escola_corrente()
    return escola.pk


def escola_corrente_ou_nada():
    """Para colunas ``escola`` opcionais (avisos, erros, registro de ações): a escola em uso, se houver."""
    escola = escola_corrente(obrigatoria=False)
    return escola.pk if escola else None


@contextmanager
def escola_ativa(escola):
    """Define a escola de um trecho de código (comandos, tarefas, testes)."""
    token = ESCOLA_ATUAL.set(escola)
    try:
        yield escola
    finally:
        ESCOLA_ATUAL.reset(token)


@contextmanager
def todas_as_escolas():
    """Libera o acesso a todas as escolas neste trecho (administrador da plataforma, tarefas, migração de banco)."""
    with escola_ativa(TODAS):
        yield


class EscolaDaConsulta(models.Expression):
    """O id da escola em uso, lido **na hora de executar** a consulta (não quando o queryset é criado).

    Assim um queryset criado no carregamento de um módulo (ex.: ``queryset=Estagio.objects.none()`` num formulário)
    ou numa escola e avaliado depois usa a escola do momento da execução."""

    output_field = models.BigIntegerField()

    def as_sql(self, compiler, connection):
        escola = escola_corrente()
        if escola is TODAS:
            raise EscopoAusente("Consulta com escopo de escola executada em modo 'todas as escolas'; use "
                                "Modelo.objects.todas_as_escolas().")
        return "%s", [escola.pk]

    def __eq__(self, other):
        return isinstance(other, EscolaDaConsulta)

    def __hash__(self):
        return hash(EscolaDaConsulta)


class EscopoEscolaQuerySet(models.QuerySet):
    def da_escola(self, escola):
        return self.filter(**{self.model._caminho_escola: escola})


class EscopoEscolaManager(models.Manager.from_queryset(EscopoEscolaQuerySet)):
    """Gerenciador padrão dos modelos com escola. O modelo define ``_caminho_escola`` ("escola", "estagio__escola"…)."""

    def get_queryset(self):
        qs = super().get_queryset()
        if ESCOLA_ATUAL.get() is TODAS:
            return qs
        return qs.filter(**{self.model._caminho_escola: EscolaDaConsulta()})

    def todas_as_escolas(self):
        return super().get_queryset()

    def da_escola(self, escola):
        return super().get_queryset().filter(**{self.model._caminho_escola: escola})
