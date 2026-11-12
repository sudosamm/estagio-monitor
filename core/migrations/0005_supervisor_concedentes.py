"""Supervisor passa a poder estar em mais de uma concedente (antes: uma só)."""
import django.db.models.deletion
from django.db import migrations, models


def copiar_vinculos(apps, schema_editor):
    Usuario = apps.get_model("core", "Usuario")
    Estagio = apps.get_model("core", "Estagio")
    Vinculo = Usuario.concedentes.through
    pares = set(Usuario.objects.exclude(local=None).values_list("pk", "local_id"))
    # estágios cujo supervisor era de outra concedente: o supervisor passa a constar também nela
    pares |= set(Estagio.objects.exclude(supervisor=None).exclude(local=None).values_list("supervisor_id", "local_id"))
    Vinculo.objects.bulk_create([Vinculo(usuario_id=u, localestagio_id=l) for u, l in sorted(pares)])


class Migration(migrations.Migration):
    dependencies = [("core", "0004_acompanhamento_desde")]

    operations = [
        migrations.AlterField(
            model_name="usuario", name="local",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name="+", to="core.localestagio"),
        ),
        migrations.AddField(
            model_name="usuario", name="concedentes",
            field=models.ManyToManyField(
                blank=True, related_name="supervisores", to="core.localestagio", verbose_name="Concedentes",
                help_text="Concedentes em que a pessoa é supervisora. Só pode supervisionar estagiários dessas concedentes.",
            ),
        ),
        migrations.RunPython(copiar_vinculos, migrations.RunPython.noop),
        migrations.RemoveField(model_name="usuario", name="local"),
    ]
