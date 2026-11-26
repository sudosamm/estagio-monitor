"""Cifragem de campos sensíveis em repouso (hoje: o segredo da verificação em duas etapas).

A chave fica fora do banco, na variável ``CHAVE_DADOS`` (uma ou mais chaves Fernet separadas por vírgula; a primeira
cifra, todas decifram, o que permite trocar a chave sem perder nada). Sem ``CHAVE_DADOS``, a chave é derivada do
``SECRET_KEY`` (também fora do banco), para o sistema funcionar sem configuração nova; nesse caso, trocar o
``SECRET_KEY`` exige pôr a chave derivada antiga em ``CHAVE_DADOS`` (``python manage.py chave_dados --derivada``).

Uma cópia do banco (backup, dump, arquivo esquecido) não revela mais o segredo: é preciso a chave também.
"""
import base64
import hashlib

from django.conf import settings
from django.db import models

PREFIXO = "f1:"


def _chave_derivada(segredo):
    return base64.urlsafe_b64encode(hashlib.sha256(("estagio-monitor/cifragem/" + segredo).encode()).digest())


def chaves():
    texto = getattr(settings, "CHAVE_DADOS", "") or ""
    lista = [c.strip().encode() for c in texto.split(",") if c.strip()]
    return lista or [_chave_derivada(settings.SECRET_KEY)]


def _fernet():
    from cryptography.fernet import Fernet, MultiFernet

    return MultiFernet([Fernet(c) for c in chaves()])


def cifrar(texto):
    if not texto or texto.startswith(PREFIXO):
        return texto
    return PREFIXO + _fernet().encrypt(texto.encode()).decode()


def decifrar(texto):
    """Texto sem o prefixo é um valor antigo, ainda em claro: volta como está (a migration 0046 cifra todos)."""
    if not texto or not texto.startswith(PREFIXO):
        return texto
    from cryptography.fernet import InvalidToken

    try:
        return _fernet().decrypt(texto[len(PREFIXO):].encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Não foi possível decifrar um campo: CHAVE_DADOS (ou SECRET_KEY) mudou?") from exc


class CampoCifrado(models.CharField):
    """CharField guardado cifrado. No Python o valor é sempre o texto em claro."""

    def from_db_value(self, value, expression, connection):
        return decifrar(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return cifrar(value) if value else value

    def deconstruct(self):
        nome, caminho, args, kwargs = super().deconstruct()
        return nome, "core.cifragem.CampoCifrado", args, kwargs
