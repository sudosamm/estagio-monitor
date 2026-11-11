"""Validação e formatação de CPF, CNPJ e CEP."""
import re

from django.core.exceptions import ValidationError


def so_digitos(texto):
    return re.sub(r"\D", "", texto or "")


def _dv(digitos, pesos):
    soma = sum(int(d) * p for d, p in zip(digitos, pesos))
    resto = soma % 11
    return "0" if resto < 2 else str(11 - resto)


def cpf_valido(cpf):
    d = so_digitos(cpf)
    if len(d) != 11 or d == d[0] * 11:
        return False
    return d[9] == _dv(d[:9], range(10, 1, -1)) and d[10] == _dv(d[:10], range(11, 1, -1))


def cnpj_valido(cnpj):
    d = so_digitos(cnpj)
    if len(d) != 14 or d == d[0] * 14:
        return False
    p1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    p2 = [6] + p1
    return d[12] == _dv(d[:12], p1) and d[13] == _dv(d[:13], p2)


def formatar_cpf(cpf):
    d = so_digitos(cpf)
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}" if len(d) == 11 else cpf


def formatar_cnpj(cnpj):
    d = so_digitos(cnpj)
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}" if len(d) == 14 else cnpj


def limpar_cpf(valor):
    """Para usar no clean_ de formulários: aceita vazio, devolve formatado ou levanta erro."""
    if not valor:
        return ""
    if not cpf_valido(valor):
        raise ValidationError("CPF inválido. Confira os números.")
    return formatar_cpf(valor)


def limpar_cnpj_ou_cpf(valor):
    if not valor:
        return ""
    d = so_digitos(valor)
    if len(d) == 11:
        return limpar_cpf(valor)
    if not cnpj_valido(valor):
        raise ValidationError("CNPJ inválido. Confira os números.")
    return formatar_cnpj(valor)


def limpar_cep(valor):
    if not valor:
        return ""
    d = so_digitos(valor)
    if len(d) != 8:
        raise ValidationError("O CEP deve ter 8 números.")
    return f"{d[:5]}-{d[5:]}"
