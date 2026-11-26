from django.apps import AppConfig


class EscolasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "escolas"
    verbose_name = "Escolas e redes"

    def ready(self):
        from django.db.models.signals import post_delete, post_save

        from . import escopo
        from .models import Escola

        post_save.connect(escopo.limpar_cache_escola_unica, sender=Escola, dispatch_uid="escola_unica_save")
        post_delete.connect(escopo.limpar_cache_escola_unica, sender=Escola, dispatch_uid="escola_unica_delete")
