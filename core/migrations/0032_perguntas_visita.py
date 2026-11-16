import unicodedata

from django.db import migrations

# Textos do relatório “Acompanhamento de Visita” do SICE.
ATITUDINAL = [
    "ACEITA CRÍTICAS/INTERVENÇÕES",
    "APRESENTA CONDUTA DE RESPEITO E COOPERAÇÃO COM O PROFESSOR",
    "APRESENTA CONDUTA DE RESPEITO E COOPERAÇÃO COM O PÚBLICO (PACIENTE/CLIENTE/USUÁRIO)",
    "APRESENTA CONDUTA DE RESPEITO E COOPERAÇÃO COM OS COLEGAS",
    "APRESENTA CONDUTA DE RESPEITO E COOPERAÇÃO COM OUTROS PROFISSIONAIS",
    "APRESENTA EQUILIBRIO EMOCIONAL",
    "BUSCA AUXÍLIO PARA ESCLARECER DÚVIDAS",
    "BUSCA CRESCIMENTO PROFISSIONAL SEM PREJUDICAR OS COLEGAS",
    "COMUNICA-SE DE FORMA CLARA",
    "COMUNICA-SE DE FORMA RESPEITOSA",
    "CUMPRE HORÁRIOS",
    "DEMONSTRA INTERESSE EM APRENDER",
    "DIVULGA CONHECIMENTO PARA MELHORAR O DESEMPENHO DAS ATIVIDADES REALIZADAS NA CONCEDENTE",
    "É ASSÍDUO",
    "É CRIATIVO",
    "ESTÁ ATENTO ÀS NECESSIDADES DA EQUIPE",
    "FAVORECE UM CLIMA ORGANIZACIONAL AGRADÁVEL E POSITIVO",
    "PLANEJA E EXECUTA AÇÕES EM EQUIPE",
    "PROPÕE E REALIZA AÇÕES E SOLUÇÕES VIÁVEIS",
    "RESPEITA A OPINIÃO DE OUTROS",
    "RESPEITA AS NORMAS E REGRAS DA CONCEDENTE",
    "RESPEITA HIERARQUIA",
    "VESTE-SE DE FORMA ADEQUADA",
]
PRATICA_INFORMATICA = [
    "REALIZAR A INSTALAÇÃO DOS DRIVERS",
    "REALIZAR DESMONTAGEM DE COMPUTADORES",
    "REALIZAR ESCOLHA DE SISTEMA OPERACIONAL DE ACORDO COM ARQUITETURA COMPUTACIONAL",
    "REALIZAR FORMATAÇÃO DE TEXTOS",
    "REALIZAR GERENCIAMENTO DO SISTEMA OPERACIONAL",
    "REALIZAR INSTALAÇÃO DE SISTEMA OPERACIONAL",
    "REALIZAR LIMPEZA INTERNA NO GABINETE",
    "REALIZAR MANUSEIO DE CHAVES DE FENDA",
    "REALIZAR MANUSEIO DE CHAVES PHILIPS",
    "REALIZAR MANUTENÇÃO CORRETIVA EM MICROCOMPUTADORES",
    "REALIZAR MONTAGEM DE COMPUTADORES",
    "EMITIR LAUDOS TÉCNICOS DE COMPUTADORES",
    "INSTALAR SOFTWARES ESSENCIAIS",
]
# Só “Realizou Sem Auxílio” e “Sempre (100%)” apareciam no relatório: confira as demais opções no SICE.
OPCOES_PRATICA = "Realizou Sem Auxílio\nRealizou Com Auxílio\nNão Realizou"
OPCOES_ATITUDINAL = "Sempre (100%)\nQuase Sempre (75%)\nÀs Vezes (50%)\nRaramente (25%)\nNunca (0%)"


def _chave(texto):
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)).lower()


def criar(apps, schema_editor):
    Pergunta = apps.get_model("core", "PerguntaAvaliacao")
    Curso = apps.get_model("core", "Curso")
    if not Pergunta.objects.filter(avaliacao="ATITUDINAL").exists():
        for ordem, texto in enumerate(ATITUDINAL, 1):
            Pergunta.objects.create(avaliacao="ATITUDINAL", enunciado=texto, resposta="ESCOLHA",
                                    opcoes=OPCOES_ATITUDINAL, obrigatoria=True, ordem=ordem)
    for curso in Curso.objects.all():
        if "informatica" in _chave(curso.nome) and not Pergunta.objects.filter(avaliacao="PRATICA", curso=curso).exists():
            for ordem, texto in enumerate(PRATICA_INFORMATICA, 1):
                Pergunta.objects.create(avaliacao="PRATICA", curso=curso, enunciado=texto, resposta="ESCOLHA",
                                        opcoes=OPCOES_PRATICA, obrigatoria=True, ordem=ordem)


class Migration(migrations.Migration):
    dependencies = [("core", "0031_acompanhamento_visita")]
    operations = [migrations.RunPython(criar, migrations.RunPython.noop)]
