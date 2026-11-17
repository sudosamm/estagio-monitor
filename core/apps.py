from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        from django.db.models.signals import post_save

        from .models import Curso

        def curso_criado(sender, instance, created, raw=False, **kw):
            """Curso novo com lista conhecida (Informática, Desenvolvimento de Sistemas) já recebe as atividades práticas do SICE (editáveis em Perguntas)."""
            if created and not raw:
                from .sice import atividades_padrao

                atividades_padrao(instance)

        post_save.connect(curso_criado, sender=Curso, dispatch_uid="atividades_sice_do_curso")

        from django.contrib.auth.signals import user_logged_in, user_login_failed

        from .seguranca import ao_entrar, ao_falhar

        user_login_failed.connect(ao_falhar, dispatch_uid="limite_login_falha")
        user_logged_in.connect(ao_entrar, dispatch_uid="limite_login_ok")
