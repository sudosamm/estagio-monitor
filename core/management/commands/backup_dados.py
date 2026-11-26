"""Backup cifrado do volume de dados (banco SQLite, anexos e chave VAPID) para o Cloudflare R2 (S3 compatível).

Agende no Coolify (Scheduled Tasks do recurso da aplicação), por exemplo todo dia às 3h:
    python manage.py backup_dados

Teste de restauração (mensal, ou depois de mudar a configuração):
    python manage.py backup_dados --testar-restauracao

Ver docs/operacao/backup.md.
"""
import logging

from django.core.management.base import BaseCommand, CommandError

from core import backup

log = logging.getLogger("core.backup")


class Command(BaseCommand):
    help = "Faz o backup cifrado de /data para o armazenamento S3/R2, aplica a retenção 7/4/6 e testa a restauração."

    def add_arguments(self, parser):
        parser.add_argument("--gerar-chave", action="store_true",
                            help="Só mostra uma BACKUP_CHAVE nova (guarde-a fora do servidor; sem ela o backup não abre).")
        parser.add_argument("--testar-restauracao", action="store_true",
                            help="Baixa o backup mais recente (ou --objeto), decifra, extrai numa pasta temporária, "
                                 "confere com o manifesto e apaga a pasta.")
        parser.add_argument("--restaurar-em", metavar="PASTA",
                            help="Baixa, decifra e extrai o backup nesta pasta (nova e vazia), sem tocar em /data.")
        parser.add_argument("--objeto", help="Chave de um backup específico (padrão: o mais recente).")
        parser.add_argument("--listar", action="store_true", help="Lista os backups guardados.")
        parser.add_argument("--sem-retencao", action="store_true", help="Não apaga backups antigos nesta execução.")

    def handle(self, *args, gerar_chave=False, testar_restauracao=False, restaurar_em=None, objeto=None,
               listar=False, sem_retencao=False, **opts):
        if gerar_chave:
            self.stdout.write(backup.gerar_chave())
            return
        try:
            if listar:
                from django.conf import settings

                prefixo = settings.BACKUP_PREFIXO.strip("/")
                objetos = backup.armazenamento_padrao().listar(prefixo + "/" if prefixo else "")
                for o in sorted(objetos, key=lambda o: o.chave):
                    self.stdout.write(f"{o.chave}  {o.tamanho / 1024 / 1024:.1f} MB")
                self.stdout.write(f"{len(objetos)} objeto(s).")
                return
            if testar_restauracao or restaurar_em:
                r = backup.restaurar(chave_objeto=objeto, destino=restaurar_em)
                if not r["ok"]:
                    log.error("Teste de restauração do backup %s FALHOU: %s", r["chave"], "; ".join(r["problemas"]))
                    raise CommandError(f"Restauração de {r['chave']} com problemas:\n- " + "\n- ".join(r["problemas"]))
                destino = f" em {r['destino']}" if r["destino"] else " (pasta temporária já apagada)"
                self.stdout.write(self.style.SUCCESS(
                    f"Restauração conferida: {r['chave']} (criado em {r['criado_em']}){destino}."))
                return
            r = backup.fazer_backup(aplicar_retencao=not sem_retencao)
        except backup.ErroBackup as exc:
            log.error("Backup dos dados falhou: %s", exc)
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f"Backup enviado: {r['chave']} ({r['bytes'] / 1024 / 1024:.1f} MB; {r['tabelas']} tabelas, "
            f"{r['linhas']} linhas, {r['anexos']} anexo(s)). Retenção: {len(r['apagados'])} antigo(s) apagado(s)."))
