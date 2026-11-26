"""Chave dos campos cifrados no banco (CHAVE_DADOS). Ver core/cifragem.py.

    python manage.py chave_dados --nova        # gera uma chave nova (ponha na frente da lista em CHAVE_DADOS)
    python manage.py chave_dados --derivada    # mostra a chave usada hoje sem CHAVE_DADOS (derivada do SECRET_KEY)
    python manage.py chave_dados --recifrar    # regrava os segredos com a primeira chave da lista
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Gera, mostra ou aplica a chave dos campos cifrados (segredo da verificação em duas etapas)."

    def add_arguments(self, parser):
        grupo = parser.add_mutually_exclusive_group(required=True)
        grupo.add_argument("--nova", action="store_true")
        grupo.add_argument("--derivada", action="store_true")
        grupo.add_argument("--recifrar", action="store_true")

    def handle(self, *args, nova=False, derivada=False, recifrar=False, **opts):
        from core import cifragem

        if nova:
            from cryptography.fernet import Fernet

            self.stdout.write(Fernet.generate_key().decode())
        elif derivada:
            self.stdout.write(cifragem._chave_derivada(settings.SECRET_KEY).decode())
        else:
            from core.models import Usuario

            n = 0
            for u in Usuario.objects.exclude(totp_segredo="").only("pk", "totp_segredo"):
                Usuario.objects.filter(pk=u.pk).update(totp_segredo=cifragem.PREFIXO + cifragem._fernet().encrypt(
                    u.totp_segredo.encode()).decode())
                n += 1
            if n and not Usuario.objects.exclude(totp_segredo="").exists():
                raise CommandError("Algo deu errado: os segredos sumiram.")
            self.stdout.write(self.style.SUCCESS(f"{n} segredo(s) regravado(s) com a chave atual."))
