from django.db import migrations

# Do HTML do formulário “Acompanhamento de Visita” do SICE (orientador).
ANTIGAS = "Sempre (100%)\nQuase Sempre (75%)\nÀs Vezes (50%)\nRaramente (25%)\nNunca (0%)"
NOVAS = "Sempre (100%)\nFrequentemente (70-90%)\nAlgumas Vezes (40-60%)\nRaramente (10-30%)\nNunca (0%)"
TROCA_RESPOSTA = {"Quase Sempre (75%)": "Frequentemente (70-90%)", "Às Vezes (50%)": "Algumas Vezes (40-60%)",
                  "Raramente (25%)": "Raramente (10-30%)"}
# os textos do SICE, exatamente como estão lá (inclusive o parêntese aberto e o “EMOCIAL”)
TEXTOS = {
    "APRESENTA CONDUTA DE RESPEITO E COOPERAÇÃO COM O PÚBLICO (PACIENTE/CLIENTE/USUÁRIO)":
        "APRESENTA CONDUTA DE RESPEITO E COOPERAÇÃO COM O PÚBLICO (PACIENTE/CLIENTE/USUÁRIO",
    "APRESENTA EQUILIBRIO EMOCIONAL": "APRESENTA EQUILIBRIO EMOCIAL",
}


def igualar(apps, schema_editor):
    Pergunta = apps.get_model("core", "PerguntaAvaliacao")
    # no SICE cada critério tem a borracha “Limpar”: pode ficar sem resposta
    Pergunta.objects.filter(avaliacao="ATITUDINAL", opcoes=ANTIGAS).update(opcoes=NOVAS, obrigatoria=False)
    for antigo, novo in TEXTOS.items():
        Pergunta.objects.filter(avaliacao="ATITUDINAL", enunciado=antigo).update(enunciado=novo)
    for a in apps.get_model("core", "AcompanhamentoVisita").objects.all():
        respostas = {k: TROCA_RESPOSTA.get(v, v) for k, v in a.respostas.items()}
        if respostas != a.respostas:
            a.respostas = respostas
            a.save(update_fields=["respostas"])


class Migration(migrations.Migration):
    dependencies = [("core", "0034_observacoes_por_parte")]
    operations = [migrations.RunPython(igualar, migrations.RunPython.noop)]
