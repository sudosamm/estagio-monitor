"""Confere o banco SQLite antes de copiá-lo para o PostgreSQL. Só lê; não imprime dados pessoais.

    python manage.py verificar_para_postgres                       # o banco em uso (SQLite)
    python manage.py verificar_para_postgres --banco /data/migracao/db-antes-postgres.sqlite3 --json contagens.json

Sai com código de erro 1 se encontrar problema. Os avisos (dados que o PostgreSQL trata diferente, como usuários ou
e-mails que só diferem por maiúsculas) aparecem, mas não impedem a cópia. Ver docs/operacao/migracao-postgresql.md.
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.migracao_banco import agrupar, avisos_sqlite, verificar_sqlite


class Command(BaseCommand):
    help = ("Procura no SQLite o que o PostgreSQL recusaria (textos longos, NUL, IPs, decimais, datas, chaves) e "
            "avisa do que ele trataria diferente (maiúsculas, acentos e ordem alfabética).")

    def add_arguments(self, parser):
        parser.add_argument("--banco", help="Arquivo SQLite (padrão: o banco configurado, se for SQLite).")
        parser.add_argument("--json", dest="arquivo_json", help="Grava as contagens por tabela e os problemas neste arquivo JSON.")

    def handle(self, *args, banco=None, arquivo_json=None, **opts):
        if not banco:
            cfg = settings.DATABASES["default"]
            if not cfg["ENGINE"].endswith("sqlite3"):
                raise CommandError("O banco em uso não é SQLite. Informe o arquivo com --banco.")
            banco = cfg["NAME"]
        if not Path(banco).exists():
            raise CommandError(f"Arquivo não encontrado: {banco}")
        problemas, contagens = verificar_sqlite(banco)
        avisos = avisos_sqlite(banco)
        self.stdout.write(f"{len(contagens)} tabelas, {sum(contagens.values())} linhas.")
        if arquivo_json:
            Path(arquivo_json).write_text(json.dumps({"contagens": contagens, "problemas": problemas,
                                                      "avisos": avisos}, indent=1))
            self.stdout.write(f"Contagens, problemas e avisos gravados em {arquivo_json}.")
        if avisos:
            self.stdout.write(self.style.WARNING(
                "Avisos (não impedem a cópia; o PostgreSQL trata estes dados diferente do SQLite — ver "
                "docs/operacao/migracao-postgresql.md):"))
            for a in avisos:
                grupos = " | ".join(", ".join(map(str, g)) for g in a["grupos"])
                self.stdout.write(f"- {a['tabela']}.{a['campo']}: {a['aviso']} ({len(a['grupos'])} grupo(s); "
                                  f"ids: {grupos})")
        if not problemas:
            self.stdout.write(self.style.SUCCESS("Nenhum problema: o banco pode ser copiado para o PostgreSQL."))
            return
        for (tabela, campo, problema), ids in sorted(agrupar(problemas).items(), key=lambda x: x[0]):
            mostrar = ", ".join(str(i) for i in ids if i is not None)
            self.stdout.write(f"- {tabela}{'.' + campo if campo else ''}: {problema}"
                              f"{' (ids: ' + mostrar + (' …' if len(ids) >= 20 else '') + ')' if mostrar else ''}")
        raise CommandError(f"{len(problemas)} problema(s). Corrija e rode de novo antes de copiar.")
