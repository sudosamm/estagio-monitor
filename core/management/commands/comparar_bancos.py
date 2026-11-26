"""Compara dois bancos depois da cópia: linhas, maior id e um resumo (SHA-256) das linhas de cada tabela.

    python manage.py comparar_bancos --origem sqlite:////data/migracao/db-antes-postgres.sqlite3 --destino "$DATABASE_URL"

Sem --destino, compara com o banco em uso. Sai com código de erro 1 se algo diferir. Não imprime dados pessoais.
"""
from django.core.management.base import BaseCommand, CommandError

from core.migracao_banco import comparar, configurar_alias


class Command(BaseCommand):
    help = "Compara tabela a tabela dois bancos do sistema (SQLite ou PostgreSQL)."

    def add_arguments(self, parser):
        parser.add_argument("--origem", required=True, help="URL do banco de origem (sqlite:////… ou postgres://…).")
        parser.add_argument("--destino", help="URL do banco de destino (padrão: o banco em uso).")

    def handle(self, *args, origem, destino=None, **opts):
        a = configurar_alias("origem_comparacao", origem)
        b = configurar_alias("destino_comparacao", destino) if destino else "default"
        diferencas, resumo = comparar(a, b)
        self.stdout.write(f"{len(resumo)} tabelas comparadas, {sum(t['linhas'] for t in resumo.values())} linhas "
                          f"na origem.")
        if diferencas:
            for d in diferencas:
                self.stdout.write(f"- {d}")
            raise CommandError(f"{len(diferencas)} tabela(s) diferente(s). Não troque o banco: veja a reversão.")
        self.stdout.write(self.style.SUCCESS("Os dois bancos são iguais."))
