from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        from django.db.models.signals import post_save

        from .models import Curso

        def curso_criado(sender, instance, created, raw=False, **kw):
            """Curso de Informática novo já recebe as atividades práticas do SICE (editáveis em Perguntas)."""
            if created and not raw:
                from .sice import atividades_padrao

                atividades_padrao(instance)

        post_save.connect(curso_criado, sender=Curso, dispatch_uid="atividades_sice_do_curso")
