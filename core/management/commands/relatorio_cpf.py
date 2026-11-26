"""Relatório de CPFs repetidos e inválidos nas contas (preparação da conta única por pessoa).

    python manage.py relatorio_cpf

Mostra só ids, papel e situação das contas (abra cada uma pelo id em Contas para decidir). Não mostra o CPF nem o
nome. A regra de CPF único só entra depois desta limpeza (decisão 11 da Etapa 0). Nada é alterado.
"""
from collections import defaultdict

from django.core.management.base import BaseCommand

from core.validators import cpf_valido, so_digitos


def levantar():
    from core.models import Usuario

    grupos, invalidos, sem_cpf = defaultdict(list), [], 0
    for pk, cpf, papel, ativo, anon in Usuario.objects.values_list("pk", "cpf", "papel", "is_active", "anonimizado_em"):
        if anon:
            continue
        digitos = so_digitos(cpf)
        if not digitos:
            sem_cpf += 1
            continue
        if not cpf_valido(digitos):
            invalidos.append((pk, papel, ativo))
            continue
        grupos[digitos].append((pk, papel, ativo))
    repetidos = sorted((v for v in grupos.values() if len(v) > 1), key=lambda v: v[0][0])
    return repetidos, invalidos, sem_cpf


class Command(BaseCommand):
    help = "Lista contas com o mesmo CPF e contas com CPF inválido (só ids; não altera nada)."

    def handle(self, *args, **opts):
        repetidos, invalidos, sem_cpf = levantar()

        def conta(c):
            return f"#{c[0]} {c[1].lower()}{'' if c[2] else ' (inativa)'}"

        self.stdout.write(f"{len(repetidos)} CPF(s) em mais de uma conta:")
        for n, grupo in enumerate(repetidos, 1):
            self.stdout.write(f"  {n}. " + ", ".join(conta(c) for c in grupo))
        self.stdout.write(f"{len(invalidos)} conta(s) com CPF inválido: " + ", ".join(conta(c) for c in invalidos))
        self.stdout.write(f"{sem_cpf} conta(s) sem CPF.")
