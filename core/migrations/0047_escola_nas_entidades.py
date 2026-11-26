"""Multiescola, passo 1 de 3: a coluna ``escola`` (ainda opcional) nas entidades da escola.

Tira também a unicidade global de ``Curso.nome`` e ``ModeloEmail.tipo``; as unicidades por escola entram no passo 3.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0046_segredo_2fa_cifrado'),
        ('escolas', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='agendamento',
            name='escola',
            field=models.ForeignKey(null=True, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AddField(
            model_name='anonimizacao',
            name='escola',
            field=models.ForeignKey(null=True, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AddField(
            model_name='avisoexterno',
            name='escola',
            field=models.ForeignKey(null=True, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AddField(
            model_name='candidatura',
            name='escola',
            field=models.ForeignKey(null=True, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AddField(
            model_name='comunicado',
            name='escola',
            field=models.ForeignKey(null=True, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AddField(
            model_name='configuracao',
            name='escola',
            field=models.OneToOneField(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='configuracao', to='escolas.escola'),
        ),
        migrations.AddField(
            model_name='curso',
            name='escola',
            field=models.ForeignKey(null=True, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AddField(
            model_name='diasemestagio',
            name='escola',
            field=models.ForeignKey(null=True, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AddField(
            model_name='documento',
            name='escola',
            field=models.ForeignKey(null=True, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AddField(
            model_name='encerramento',
            name='escola',
            field=models.ForeignKey(null=True, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AddField(
            model_name='errosistema',
            name='escola',
            field=models.ForeignKey(blank=True, editable=False, help_text='Vazio = da plataforma (sem escola)', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='escolas.escola'),
        ),
        migrations.AddField(
            model_name='estagio',
            name='escola',
            field=models.ForeignKey(null=True, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AddField(
            model_name='folhaenviada',
            name='escola',
            field=models.ForeignKey(null=True, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AddField(
            model_name='linkconfirmacao',
            name='escola',
            field=models.ForeignKey(null=True, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AddField(
            model_name='localestagio',
            name='escola',
            field=models.ForeignKey(null=True, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AddField(
            model_name='modeloemail',
            name='escola',
            field=models.ForeignKey(blank=True, editable=False, help_text='Vazio = da plataforma (sem escola)', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='+', to='escolas.escola'),
        ),
        migrations.AddField(
            model_name='notificacao',
            name='escola',
            field=models.ForeignKey(blank=True, editable=False, help_text='Vazio = da plataforma (sem escola)', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='+', to='escolas.escola'),
        ),
        migrations.AddField(
            model_name='perguntaavaliacao',
            name='escola',
            field=models.ForeignKey(null=True, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AddField(
            model_name='registroacao',
            name='escola',
            field=models.ForeignKey(blank=True, editable=False, help_text='Vazio = da plataforma (sem escola)', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='escolas.escola'),
        ),
        migrations.AddField(
            model_name='sugestao',
            name='escola',
            field=models.ForeignKey(blank=True, editable=False, help_text='Vazio = da plataforma (sem escola)', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='escolas.escola'),
        ),
        migrations.AddField(
            model_name='tipodocumento',
            name='escola',
            field=models.ForeignKey(null=True, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AddField(
            model_name='vinculoresponsavel',
            name='escola',
            field=models.ForeignKey(null=True, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AlterField(
            model_name='curso',
            name='nome',
            field=models.CharField(max_length=120),
        ),
        migrations.AlterField(
            model_name='modeloemail',
            name='tipo',
            field=models.CharField(max_length=30),
        ),
    ]
