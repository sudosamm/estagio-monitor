from django.db import migrations

TIPOS = [
    ("Termo de Compromisso de Estágio (TCE) assinado", "INICIO", 15, "ESTAGIARIO", True,
     "Foto ou PDF do termo com as assinaturas do estudante, da escola e da concedente."),
    ("Plano de atividades", "INICIO", 30, "SUPERVISOR", True,
     "Atividades que o estagiário vai realizar, combinadas entre a concedente e a escola."),
    ("Relatório final de estágio", "FIM", 15, "ESTAGIARIO", True,
     "Relatório escrito pelo estagiário sobre o que fez e aprendeu."),
    ("Avaliação do estagiário pelo supervisor", "FIM", 15, "SUPERVISOR", True,
     "Ficha de avaliação preenchida e assinada pelo supervisor."),
    ("Termo de realização de estágio", "FIM", 30, "SUPERVISOR", False,
     "Declaração da concedente com o período e a carga horária realizada."),
]


def criar(apps, schema_editor):
    Tipo = apps.get_model("core", "TipoDocumento")
    if Tipo.objects.exists():
        return
    for ordem, (nome, momento, prazo, quem, obrig, desc) in enumerate(TIPOS, 1):
        Tipo.objects.create(nome=nome, momento=momento, prazo_dias=prazo, quem_envia=quem, obrigatorio=obrig,
                            descricao=desc, ordem=ordem)


class Migration(migrations.Migration):
    dependencies = [("core", "0016_pasta_documentos")]
    operations = [migrations.RunPython(criar, migrations.RunPython.noop)]
