from django.db import migrations

# Textos exatos do SICE (telas “AutoAvaliação - Cadastro” e “Avaliação de Orientador - Cadastro”).
AUTO = [
    "O que aprendi",
    "O que foi bom",
    "O que precisa melhorar",
    "Dúvidas",
    "Sugestões",
    "Contribuição do estágio para a formação pessoal",
    "Contribuição do estágio para a formação profissional",
    "Contribuição para melhorar a empresa",
]
ORIENTADOR = [
    "Realizou orientações antes do início do estágio",
    "Faz as anotações e intervenções necessárias",
    "Esclarece as dúvidas",
    "Reconhece o desenvolvimento cognitivo",
    "Reconhece o desenvolvimento socioafetivo",
    "Socializa dificuldades técnicas observadas",
    "Socializa dificuldades interpessoais observadas",
    "Estimula o aperfeiçoamento dos domínios de aprendizagem",
    "Propõe soluções e melhorias",
    "Oportuniza superação e crescimento",
    "Faz acompanhamento individual",
    "Mediação",
]
# Provisórias: a 0030 troca por SIM/NÃO, as opções reais do SICE.
OPCOES_ORIENTADOR = "Sempre\nQuase sempre\nÀs vezes\nRaramente\nNunca"
MODELO_ANTIGO = {"Assiduidade e pontualidade", "Acompanhamento e disponibilidade do orientador"}


def trocar(apps, schema_editor):
    Pergunta = apps.get_model("core", "PerguntaAvaliacao")
    Avaliacao = apps.get_model("core", "Avaliacao")
    existentes = set(Pergunta.objects.values_list("enunciado", flat=True))
    if existentes and not (existentes & MODELO_ANTIGO):
        return  # a escola já editou as perguntas: não mexe
    if Avaliacao.objects.exists():
        return
    Pergunta.objects.all().delete()
    for ordem, texto in enumerate(AUTO, 1):
        Pergunta.objects.create(avaliacao="AUTO", enunciado=texto, resposta="TEXTO", limite=1000, obrigatoria=True,
                                ordem=ordem)
    for ordem, texto in enumerate(ORIENTADOR, 1):
        Pergunta.objects.create(avaliacao="ORIENTADOR", enunciado=texto, resposta="ESCOLHA", opcoes=OPCOES_ORIENTADOR,
                                obrigatoria=True, ordem=ordem)
    Pergunta.objects.create(avaliacao="ORIENTADOR", enunciado="Observações/Sugestões", resposta="TEXTO", limite=1000,
                            obrigatoria=False, ordem=len(ORIENTADOR) + 1)


class Migration(migrations.Migration):
    dependencies = [("core", "0028_avaliacoes_mensais")]
    operations = [migrations.RunPython(trocar, migrations.RunPython.noop)]
