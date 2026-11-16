from django.db import migrations

ANTIGAS = "Realizou Sem Auxílio\nRealizou Com Auxílio\nNão Realizou"
NOVAS = "Observou\nRealizou Com Auxílio\nRealizou Sem Auxílio"


def corrigir(apps, schema_editor):
    """Opções reais da avaliação prática do SICE; a resposta pode ficar em branco (não há “não realizou”)."""
    Pergunta = apps.get_model("core", "PerguntaAvaliacao")
    Pergunta.objects.filter(avaliacao="PRATICA", opcoes=ANTIGAS).update(opcoes=NOVAS, obrigatoria=False)
    # respostas antigas “Não Realizou” viram em branco
    Acomp = apps.get_model("core", "AcompanhamentoVisita")
    for a in Acomp.objects.all():
        respostas = {k: ("" if v == "Não Realizou" else v) for k, v in a.respostas.items()}
        if respostas != a.respostas:
            a.respostas = respostas
            a.save(update_fields=["respostas"])


class Migration(migrations.Migration):
    dependencies = [("core", "0032_perguntas_visita")]
    operations = [migrations.RunPython(corrigir, migrations.RunPython.noop)]
