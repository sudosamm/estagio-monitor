import unicodedata

from django.db import migrations

from core.sice import OPCOES_PRATICA, PRATICA_DESENVOLVIMENTO_SISTEMAS


def _chave(texto):
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", texto)
                            if not unicodedata.combining(c)).lower().split())


def criar(apps, schema_editor):
    """Inclui nos cursos de Desenvolvimento de Sistemas as atividades do SICE que ainda faltam.

    Seguro em banco com dados: não altera nem apaga nada; atividades já cadastradas (mesmo texto, sem
    diferenciar maiúsculas/acentos) são mantidas e as novas entram depois delas, na ordem do SICE."""
    Pergunta = apps.get_model("core", "PerguntaAvaliacao")
    Curso = apps.get_model("core", "Curso")
    for curso in Curso.objects.all():
        if "desenvolvimento de sistemas" not in _chave(curso.nome):
            continue
        existentes = Pergunta.objects.filter(avaliacao="PRATICA", curso=curso)
        ja = {_chave(t) for t in existentes.values_list("enunciado", flat=True)}
        ordem = max(existentes.values_list("ordem", flat=True), default=0)
        novas = []
        for texto in PRATICA_DESENVOLVIMENTO_SISTEMAS:
            if _chave(texto) not in ja:
                ordem += 1
                novas.append(Pergunta(avaliacao="PRATICA", curso=curso, enunciado=texto, resposta="ESCOLHA",
                                      opcoes=OPCOES_PRATICA, obrigatoria=False, ordem=ordem))
        Pergunta.objects.bulk_create(novas)


class Migration(migrations.Migration):
    dependencies = [("core", "0035_atitudinal_igual_sice")]
    operations = [migrations.RunPython(criar, migrations.RunPython.noop)]
