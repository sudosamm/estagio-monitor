"""Ferramentas da troca de banco (SQLite → PostgreSQL): verificação antes da cópia e comparação depois.

Nada aqui imprime dados pessoais: os relatórios mostram só tabela, campo, id da linha e o tipo do problema, e a
comparação usa contagens, o maior id e um resumo (SHA-256) das linhas.

Ver docs/operacao/migracao-postgresql.md.
"""
import datetime as dt
import decimal
import hashlib
import ipaddress
import json
import sqlite3
from collections import defaultdict

from django.apps import apps
from django.db import connections, models

# tabelas recriadas pelo migrate no banco novo (os ids podem mudar; a comparação usa a chave natural)
TABELAS_POR_CHAVE_NATURAL = {"django_content_type", "auth_permission"}
TABELAS_IGNORADAS = {"django_migrations"}
LIMITE_IDS = 20


def modelos_concretos():
    """Todos os modelos com tabela própria, inclusive as tabelas de ligação (ManyToMany)."""
    vistos, saida = set(), []
    for m in apps.get_models(include_auto_created=True):
        meta = m._meta
        if meta.proxy or not meta.managed or meta.db_table in vistos:
            continue
        vistos.add(meta.db_table)
        saida.append(m)
    return sorted(saida, key=lambda m: m._meta.db_table)


# ---------------------------------------------------------------------------------------------------------------
# Verificação do SQLite (antes da cópia)
# ---------------------------------------------------------------------------------------------------------------
LIMITES_INTEIROS = {
    "SmallIntegerField": (-32768, 32767), "PositiveSmallIntegerField": (0, 32767),
    "IntegerField": (-2147483648, 2147483647), "PositiveIntegerField": (0, 2147483647),
    "BigIntegerField": (-(2 ** 63), 2 ** 63 - 1), "PositiveBigIntegerField": (0, 2 ** 63 - 1),
    "AutoField": (1, 2147483647), "BigAutoField": (1, 2 ** 63 - 1),
}
TIPOS_TEXTO = (models.CharField, models.TextField, models.EmailField, models.URLField, models.SlugField,
               models.FileField, models.GenericIPAddressField)


def _tipo_interno(campo):
    return campo.get_internal_type()


def _problema(tabela, campo, pk, tipo):
    return {"tabela": tabela, "campo": campo, "id": pk, "problema": tipo}


def verificar_sqlite(caminho):
    """Lê o arquivo SQLite (só leitura) e devolve (problemas, contagens por tabela)."""
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    con.text_factory = bytes  # lê o texto cru: um byte inválido em UTF-8 vira problema, não exceção
    problemas = []
    try:
        integridade = con.execute("PRAGMA integrity_check").fetchone()[0].decode()
        if integridade != "ok":
            problemas.append(_problema("(banco)", "", None, f"integrity_check: {integridade[:120]}"))
        for linha in con.execute("PRAGMA foreign_key_check").fetchall():
            tabela, rowid, pai = linha[0].decode(), linha[1], linha[2].decode()
            problemas.append(_problema(tabela, "", rowid, f"chave estrangeira sem a linha correspondente em {pai}"))
        existentes = {t.decode() for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        contagens = {}
        for modelo in modelos_concretos():
            meta = modelo._meta
            tabela = meta.db_table
            if tabela not in existentes:
                problemas.append(_problema(tabela, "", None, "tabela ausente (migrations não aplicadas?)"))
                continue
            contagens[tabela] = con.execute(f'SELECT COUNT(*) FROM "{tabela}"').fetchone()[0]
            pk = meta.pk.column
            for campo in meta.concrete_fields:
                problemas += _verificar_coluna(con, tabela, pk, campo)
    finally:
        con.close()
    return problemas, contagens


def _ids(con, sql, *params):
    return [r[0] for r in con.execute(sql + f" LIMIT {LIMITE_IDS}", params).fetchall()]


def _verificar_coluna(con, tabela, pk, campo):
    col = campo.column
    q = f'"{tabela}"'
    c = f'"{col}"'
    saida = []
    tipo = _tipo_interno(campo)
    if not campo.null:
        for i in _ids(con, f"SELECT {pk} FROM {q} WHERE {c} IS NULL"):
            saida.append(_problema(tabela, col, i, "valor vazio (NULL) num campo obrigatório"))
    if isinstance(campo, TIPOS_TEXTO) or tipo in ("JSONField",):
        for i in _ids(con, f"SELECT {pk} FROM {q} WHERE instr(CAST({c} AS BLOB), x'00') > 0"):
            saida.append(_problema(tabela, col, i, "caractere NUL (o PostgreSQL recusa)"))
        for (i, valor) in con.execute(f"SELECT {pk}, CAST({c} AS BLOB) FROM {q} WHERE {c} IS NOT NULL").fetchall():
            if isinstance(valor, bytes):
                try:
                    texto = valor.decode("utf-8")
                except UnicodeDecodeError:
                    saida.append(_problema(tabela, col, i, "texto com bytes inválidos em UTF-8"))
                    continue
                if getattr(campo, "max_length", None) and len(texto) > campo.max_length:
                    saida.append(_problema(tabela, col, i, f"texto com {len(texto)} caracteres; o limite do campo é "
                                                           f"{campo.max_length}"))
                if tipo == "GenericIPAddressField" and texto:
                    try:
                        ipaddress.ip_address(texto)
                    except ValueError:
                        saida.append(_problema(tabela, col, i, "endereço IP inválido"))
                if tipo == "JSONField":
                    try:
                        json.loads(texto)
                    except ValueError:
                        saida.append(_problema(tabela, col, i, "JSON inválido"))
    if tipo in LIMITES_INTEIROS and not campo.is_relation:
        menor, maior = LIMITES_INTEIROS[tipo]
        for i in _ids(con, f"SELECT {pk} FROM {q} WHERE {c} IS NOT NULL AND (typeof({c}) != 'integer' "
                           f"OR {c} < ? OR {c} > ?)", menor, maior):
            saida.append(_problema(tabela, col, i, f"inteiro fora do intervalo {menor}…{maior} ou não numérico"))
    if tipo == "BooleanField":
        for i in _ids(con, f"SELECT {pk} FROM {q} WHERE {c} IS NOT NULL AND {c} NOT IN (0, 1)"):
            saida.append(_problema(tabela, col, i, "booleano diferente de 0/1"))
    if tipo == "DecimalField":
        limite = decimal.Decimal(10) ** (campo.max_digits - campo.decimal_places)
        for (i, valor) in con.execute(f"SELECT {pk}, CAST({c} AS TEXT) FROM {q} WHERE {c} IS NOT NULL").fetchall():
            try:
                d = decimal.Decimal(valor.decode())
                if abs(d) >= limite or not d.is_finite():
                    raise decimal.InvalidOperation
            except (decimal.InvalidOperation, ValueError):
                saida.append(_problema(tabela, col, i, f"decimal fora de {campo.max_digits} dígitos "
                                                       f"({campo.decimal_places} casas)"))
    if tipo in ("DateField", "DateTimeField", "TimeField"):
        conversor = {"DateField": dt.date.fromisoformat, "TimeField": dt.time.fromisoformat,
                     "DateTimeField": dt.datetime.fromisoformat}[tipo]
        for (i, valor) in con.execute(f"SELECT {pk}, CAST({c} AS TEXT) FROM {q} WHERE {c} IS NOT NULL").fetchall():
            try:
                conversor(valor.decode())
            except (ValueError, UnicodeDecodeError):
                saida.append(_problema(tabela, col, i, "data/hora inválida"))
    return saida


# ---------------------------------------------------------------------------------------------------------------
# Comparação entre dois bancos (depois da cópia)
# ---------------------------------------------------------------------------------------------------------------
def configurar_alias(alias, url):
    """Abre um segundo banco (pela URL) com o nome ``alias`` nas conexões do Django."""
    from monitor.banco import config_da_url

    cfg = config_da_url(url, conn_max_age=0)
    if alias in connections.settings:
        connections[alias].close()
        del connections[alias]
    connections.settings[alias] = connections.configure_settings(
        {"default": connections.settings["default"], alias: cfg})[alias]
    return alias


def _normalizar(valor):
    if isinstance(valor, dt.datetime):
        if valor.tzinfo is not None:
            valor = valor.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return "dt:" + valor.isoformat()
    if isinstance(valor, (dt.date, dt.time)):
        return valor.isoformat()
    if isinstance(valor, decimal.Decimal):
        return "dec:" + format(valor.normalize(), "f")
    if isinstance(valor, (dict, list)):
        return json.dumps(valor, sort_keys=True, ensure_ascii=False)
    if isinstance(valor, memoryview):
        return bytes(valor).hex()
    if isinstance(valor, bytes):
        return valor.hex()
    return valor


def _mapas_naturais(alias):
    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType

    tipos = {ct.pk: f"{ct.app_label}.{ct.model}" for ct in ContentType.objects.using(alias).all()}
    perms = {p.pk: f"{tipos.get(p.content_type_id)}.{p.codename}" for p in Permission.objects.using(alias).all()}
    return {"contenttypes.ContentType": tipos, "auth.Permission": perms}


def resumo_banco(alias):
    """{tabela: {"linhas", "maior_id", "resumo"}} usando o ORM (os valores chegam já convertidos pelo Django, então
    SQLite e PostgreSQL são comparáveis)."""
    mapas = _mapas_naturais(alias)
    saida = {}
    for modelo in modelos_concretos():
        meta = modelo._meta
        if meta.db_table in TABELAS_IGNORADAS:
            continue
        campos = [f for f in meta.concrete_fields]
        traduzir = {}
        for f in campos:
            if f.is_relation and f.related_model is not None:
                rotulo = f.related_model._meta.label
                if rotulo in mapas:
                    traduzir[f.attname] = mapas[rotulo]
        nomes = [f.attname for f in campos]
        qs = modelo._base_manager.using(alias).order_by(meta.pk.attname).values_list(*nomes)
        h = hashlib.sha256()
        linhas = 0
        maior = None
        natural = meta.db_table in TABELAS_POR_CHAVE_NATURAL
        chaves_naturais = []
        for linha in qs.iterator(chunk_size=2000):
            linhas += 1
            valores = dict(zip(nomes, linha))
            for nome, mapa in traduzir.items():
                valores[nome] = mapa.get(valores[nome], valores[nome])
            if natural:
                valores.pop(meta.pk.attname)
                chaves_naturais.append(json.dumps({k: _normalizar(v) for k, v in valores.items()}, sort_keys=True,
                                                  default=str))
                continue
            maior = valores[meta.pk.attname]
            h.update(json.dumps([_normalizar(valores[n]) for n in nomes], default=str, ensure_ascii=False).encode())
            h.update(b"\n")
        if natural:
            for k in sorted(chaves_naturais):
                h.update(k.encode())
            maior = None
        saida[meta.db_table] = {"linhas": linhas, "maior_id": maior, "resumo": h.hexdigest()}
    return saida


def comparar(alias_origem, alias_destino):
    """Lista de diferenças (vazia = bancos iguais)."""
    a, b = resumo_banco(alias_origem), resumo_banco(alias_destino)
    diferencas = []
    for tabela in sorted(set(a) | set(b)):
        x, y = a.get(tabela), b.get(tabela)
        if x != y:
            partes = []
            for k in ("linhas", "maior_id", "resumo"):
                if (x or {}).get(k) != (y or {}).get(k):
                    partes.append(k if k == "resumo" else f"{k} {(x or {}).get(k)} → {(y or {}).get(k)}")
            diferencas.append(f"{tabela}: " + ", ".join(partes))
    return diferencas, a


def agrupar(problemas):
    grupos = defaultdict(list)
    for p in problemas:
        grupos[(p["tabela"], p["campo"], p["problema"])].append(p["id"])
    return grupos
