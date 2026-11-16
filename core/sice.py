"""Listas do SICE usadas para preencher as perguntas automaticamente."""
import unicodedata

# Avaliação prática do “Acompanhamento de Visita” — Técnico em Informática (relatório do SICE)
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
# No SICE a resposta pode ficar em branco (não há “não realizou”)
OPCOES_PRATICA = "Observou\nRealizou Com Auxílio\nRealizou Sem Auxílio"


def _chave(texto):
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)).lower()


def atividades_padrao(curso):
    """Cria as atividades práticas do SICE para um curso de Informática que ainda não tem nenhuma."""
    from .models import PerguntaAvaliacao

    if "informatica" not in _chave(curso.nome):
        return 0
    if PerguntaAvaliacao.objects.filter(avaliacao=PerguntaAvaliacao.Tipo.PRATICA, curso=curso).exists():
        return 0
    PerguntaAvaliacao.objects.bulk_create([
        PerguntaAvaliacao(avaliacao=PerguntaAvaliacao.Tipo.PRATICA, curso=curso, enunciado=t, resposta="ESCOLHA",
                          opcoes=OPCOES_PRATICA, obrigatoria=False, ordem=i)
        for i, t in enumerate(PRATICA_INFORMATICA, 1)])
    return len(PRATICA_INFORMATICA)
