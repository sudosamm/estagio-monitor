"""Multiescola, passo 3 de 3: ``escola`` obrigatória nas entidades da escola e unicidades por escola.

Depende do passo 2 ter associado todos os registros a uma escola. Reversão: as colunas voltam a ser opcionais.
"""
import django.db.models.deletion
import escolas.escopo
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0048_associar_escola_atual'),
    ]

    operations = [
        migrations.AlterField(
            model_name='agendamento',
            name='escola',
            field=models.ForeignKey(default=escolas.escopo.escola_corrente_id, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AlterField(
            model_name='anonimizacao',
            name='escola',
            field=models.ForeignKey(default=escolas.escopo.escola_corrente_id, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AlterField(
            model_name='avisoexterno',
            name='escola',
            field=models.ForeignKey(default=escolas.escopo.escola_corrente_id, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AlterField(
            model_name='candidatura',
            name='escola',
            field=models.ForeignKey(default=escolas.escopo.escola_corrente_id, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AlterField(
            model_name='comunicado',
            name='escola',
            field=models.ForeignKey(default=escolas.escopo.escola_corrente_id, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AlterField(
            model_name='configuracao',
            name='escola',
            field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='configuracao', to='escolas.escola'),
        ),
        migrations.AlterField(
            model_name='curso',
            name='escola',
            field=models.ForeignKey(default=escolas.escopo.escola_corrente_id, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AlterField(
            model_name='diasemestagio',
            name='escola',
            field=models.ForeignKey(default=escolas.escopo.escola_corrente_id, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AlterField(
            model_name='documento',
            name='escola',
            field=models.ForeignKey(default=escolas.escopo.escola_corrente_id, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AlterField(
            model_name='encerramento',
            name='escola',
            field=models.ForeignKey(default=escolas.escopo.escola_corrente_id, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AlterField(
            model_name='estagio',
            name='escola',
            field=models.ForeignKey(default=escolas.escopo.escola_corrente_id, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AlterField(
            model_name='folhaenviada',
            name='escola',
            field=models.ForeignKey(default=escolas.escopo.escola_corrente_id, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AlterField(
            model_name='linkconfirmacao',
            name='escola',
            field=models.ForeignKey(default=escolas.escopo.escola_corrente_id, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AlterField(
            model_name='localestagio',
            name='escola',
            field=models.ForeignKey(default=escolas.escopo.escola_corrente_id, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AlterField(
            model_name='perguntaavaliacao',
            name='escola',
            field=models.ForeignKey(default=escolas.escopo.escola_corrente_id, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AlterField(
            model_name='tipodocumento',
            name='escola',
            field=models.ForeignKey(default=escolas.escopo.escola_corrente_id, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AlterField(
            model_name='vinculoresponsavel',
            name='escola',
            field=models.ForeignKey(default=escolas.escopo.escola_corrente_id, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='escolas.escola'),
        ),
        migrations.AlterField(
            model_name='errosistema',
            name='escola',
            field=models.ForeignKey(blank=True, default=escolas.escopo.escola_corrente_ou_nada, editable=False, help_text='Vazio = da plataforma (sem escola)', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='escolas.escola'),
        ),
        migrations.AlterField(
            model_name='modeloemail',
            name='escola',
            field=models.ForeignKey(blank=True, default=escolas.escopo.escola_corrente_ou_nada, editable=False, help_text='Vazio = da plataforma (sem escola)', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='+', to='escolas.escola'),
        ),
        migrations.AlterField(
            model_name='notificacao',
            name='escola',
            field=models.ForeignKey(blank=True, default=escolas.escopo.escola_corrente_ou_nada, editable=False, help_text='Vazio = da plataforma (sem escola)', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='+', to='escolas.escola'),
        ),
        migrations.AlterField(
            model_name='registroacao',
            name='escola',
            field=models.ForeignKey(blank=True, default=escolas.escopo.escola_corrente_ou_nada, editable=False, help_text='Vazio = da plataforma (sem escola)', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='escolas.escola'),
        ),
        migrations.AlterField(
            model_name='sugestao',
            name='escola',
            field=models.ForeignKey(blank=True, default=escolas.escopo.escola_corrente_ou_nada, editable=False, help_text='Vazio = da plataforma (sem escola)', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='escolas.escola'),
        ),
        migrations.AddConstraint(
            model_name='curso',
            constraint=models.UniqueConstraint(fields=('escola', 'nome'), name='curso_nome_unico_na_escola'),
        ),
        migrations.AddConstraint(
            model_name='modeloemail',
            constraint=models.UniqueConstraint(fields=('escola', 'tipo'), name='modelo_email_unico_na_escola'),
        ),
        migrations.AddConstraint(
            model_name='modeloemail',
            constraint=models.UniqueConstraint(condition=models.Q(('escola__isnull', True)), fields=('tipo',), name='modelo_email_padrao_unico'),
        ),
    ]
