from django.core.management.base import BaseCommand

from core.models import Usuario
from core.seguranca import gerar_codigo
from core.services import criar_usuario


class Command(BaseCommand):
    help = 'Cria uma conta de orientador. Ex.: python manage.py criar_orientador "Maria Souza" --admin'

    def add_arguments(self, parser):
        parser.add_argument("nome")
        parser.add_argument("--email", default="")
        parser.add_argument("--admin", action="store_true", help="Dá acesso total (vê todos os orientadores e /admin)")
        parser.add_argument("--se-nao-houver-admin", action="store_true", help="Só cria se ainda não existir administrador")

    def handle(self, nome, email, admin, se_nao_houver_admin, **_):
        if se_nao_houver_admin and Usuario.objects.filter(is_superuser=True).exists():
            return
        user = criar_usuario(nome, Usuario.Papel.ORIENTADOR, email=email)
        if admin:
            user.is_superuser = user.is_staff = True
            user.save()
        codigo = gerar_codigo(user)
        self.stdout.write(self.style.SUCCESS(
            f"Orientador criado: usuário '{user.username}', código de primeiro acesso '{codigo}' (vale 30 dias). "
            "Abra /primeiro-acesso/, escolha “Tenho um código” e crie a senha."
        ))
