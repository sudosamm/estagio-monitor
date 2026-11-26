"""Lê a configuração do banco a partir de uma URL (``DATABASE_URL``), sem dependência externa.

Formatos aceitos:
- ``postgres://usuario:senha@host:5432/nome?sslmode=require`` (também ``postgresql://``);
- ``sqlite:////caminho/absoluto/db.sqlite3`` (usado pelos comandos de migração para apontar o banco antigo).

Sem ``DATABASE_URL`` o sistema continua no SQLite em ``DATA_DIR`` (ver settings.py).
"""
from urllib.parse import parse_qsl, unquote, urlsplit

OPCOES_SQLITE = {
    "transaction_mode": "IMMEDIATE",
    "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=5000;",
}


def config_sqlite(caminho):
    return {"ENGINE": "django.db.backends.sqlite3", "NAME": caminho, "OPTIONS": dict(OPCOES_SQLITE)}


def config_da_url(url, conn_max_age=60):
    partes = urlsplit(url.strip())
    esquema = partes.scheme.lower()
    if esquema == "sqlite":
        caminho = unquote(partes.path)
        if partes.netloc:  # sqlite://relativo/arquivo — não aceito, para não gravar no lugar errado
            raise ValueError("Use sqlite:////caminho/absoluto (quatro barras).")
        if caminho.startswith("//"):
            caminho = caminho[1:]
        return config_sqlite(caminho)
    if esquema not in ("postgres", "postgresql", "pgsql"):
        raise ValueError(f"Banco não suportado em DATABASE_URL: {esquema or '(vazio)'}")
    nome = unquote(partes.path.lstrip("/"))
    if not nome:
        raise ValueError("DATABASE_URL sem o nome do banco (…/nome_do_banco).")
    opcoes = dict(parse_qsl(partes.query))
    teste = {"TEMPLATE": "template0"} if opcoes.pop("teste_template0", "") == "1" else {}
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": nome,
        "USER": unquote(partes.username or ""),
        "PASSWORD": unquote(partes.password or ""),
        "HOST": partes.hostname or "",
        "PORT": str(partes.port or ""),
        "CONN_MAX_AGE": conn_max_age,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": opcoes,
        "TEST": teste,
    }
