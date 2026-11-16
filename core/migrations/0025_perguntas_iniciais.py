from django.db import migrations

# Modelo inicial: ajuste em “Avaliações → Perguntas” para ficar igual ao formulário do SICE.
PERGUNTAS = {
    "AUTO": [
        ("Assiduidade e pontualidade", "NOTA", ""),
        ("Responsabilidade e compromisso com as atividades", "NOTA", ""),
        ("Relacionamento com a equipe e com o público", "NOTA", ""),
        ("Iniciativa e disposição para aprender", "NOTA", ""),
        ("Aplicação dos conhecimentos do curso", "NOTA", ""),
        ("Principais atividades que você realizou no estágio", "TEXTO", "Conte o que fazia no dia a dia, com exemplos."),
        ("O que você aprendeu de mais importante", "TEXTO", ""),
        ("Dificuldades que encontrou e como lidou com elas", "TEXTO", ""),
    ],
    "ORIENTADOR": [
        ("Acompanhamento e disponibilidade do orientador", "NOTA", ""),
        ("Clareza das orientações recebidas", "NOTA", ""),
        ("Visitas e contato durante o estágio", "NOTA", ""),
        ("Apoio para resolver problemas no estágio", "NOTA", ""),
        ("Comentários e sugestões sobre a orientação", "TEXTO", "Opcional."),
    ],
}


def criar(apps, schema_editor):
    Pergunta = apps.get_model("core", "PerguntaAvaliacao")
    if Pergunta.objects.exists():
        return
    for tipo, itens in PERGUNTAS.items():
        for ordem, (enunciado, resposta, ajuda) in enumerate(itens, 1):
            Pergunta.objects.create(avaliacao=tipo, enunciado=enunciado, resposta=resposta, ajuda=ajuda, ordem=ordem,
                                    obrigatoria=not ajuda.startswith("Opcional"))


class Migration(migrations.Migration):
    dependencies = [("core", "0024_avaliacoes")]
    operations = [migrations.RunPython(criar, migrations.RunPython.noop)]
