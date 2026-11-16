"""“O que há de novo”: histórico de mudanças, separado por tipo de usuário.

Para publicar uma atualização, acrescente uma versão NO TOPO de VERSOES. Cada item diz para quem vale:
  "todos", "estagiario", "supervisor", "orientador", "coordenador" (o administrador vê tudo).
Quem ainda não viu a versão nova (e não desligou o aviso) recebe o pop-up no próximo acesso.
"""
from dataclasses import dataclass

TODOS = ("estagiario", "supervisor", "orientador", "coordenador")
GESTAO = ("orientador", "coordenador")
ROTULOS = {"estagiario": "Estagiários", "supervisor": "Supervisores", "orientador": "Orientadores",
           "coordenador": "Coordenação"}


@dataclass(frozen=True)
class Versao:
    id: str  # AAAA.MM.DD — dá a ordem
    titulo: str
    itens: tuple  # ((publico, texto), …)


def _p(*publico):
    return TODOS if "todos" in publico else publico


VERSOES = (
    Versao("2026.11.16", "Novidades de novembro", (
        (_p("todos"), "Tema escuro “Noite no sertão”: no menu da sua foto, escolha Auto (segue o celular), Claro ou Escuro."),
        (_p("todos"), "Notificações no celular: ative em Meus dados e receba os avisos mesmo com o app fechado."),
        (_p("todos"), "Sugestões e erros: uma página para mandar ideias, problemas e prints direto para a equipe do sistema."),
        (_p("todos"), "O que há de novo: este aviso, que mostra só o que mudou para você. Veja o histórico em Novidades."),
        (_p("estagiario"), "Avaliações para o SICE: responda a autoavaliação e a avaliação do orientador aqui e copie as "
                           "respostas prontas para o SICE."),
        (_p("estagiario"), "Check-in por QR code: escaneie o QR do supervisor e a presença já sai confirmada."),
        (_p("estagiario"), "Atestados: envie a foto do atestado ou comprovante; aceito, o dia não conta como falta."),
        (_p("estagiario"), "Pasta do estágio: veja quais documentos faltam (TCE, relatório…) e envie pelo sistema."),
        (_p("estagiario"), "Feedback do supervisor: veja as notas e comentários do mês na aba Feedback do seu estágio."),
        (_p("estagiario"), "Marcou presença por engano? Dá para desfazer na página do dia, antes de o supervisor confirmar."),
        (_p("estagiario", "supervisor"), "Avisos da escola: os recados do orientador ficam em Notificações → Avisos da escola."),
        (_p("supervisor"), "QR code de presença: mostre a tela e a chegada do estagiário já sai confirmada por você."),
        (_p("supervisor"), "Feedback mensal: notas e comentários sobre cada estagiário, em uns 2 minutos, pelo seu painel."),
        (_p("supervisor"), "Pasta do estágio: o painel mostra os documentos que a escola precisa de você (ex.: plano de "
                           "atividades)."),
        (_p("supervisor", "orientador", "coordenador"), "Atestados: veja o documento e aceite ou recuse direto pelo sistema."),
        (_p("supervisor", "orientador", "coordenador"), "Revogar presença: desfaça uma presença (mesmo já confirmada) "
                                                        "com motivo, que fica no histórico."),
        (_p("supervisor", "orientador", "coordenador"), "Horas por dia livres (5h, 7h, 5h30…), ou calculadas pelos "
                                                        "horários de entrada e saída."),
        (_p("estagiario", "supervisor", "orientador"), "Visitas no seu calendário: assine a agenda no Google Agenda ou no "
                                                       "celular (Agenda → No meu calendário)."),
        (GESTAO, "Menu reorganizado em seções: Acompanhamento, Comunicação e Cadastros, com o número de pendências."),
        (GESTAO, "Indicadores: frequência semana a semana, situação, e quadros por turma e por concedente."),
        (GESTAO, "Avaliações (SICE): acompanhe quem já respondeu e ajuste as perguntas para ficarem iguais ao SICE."),
        (GESTAO, "Feedback dos supervisores: médias mês a mês e quem ainda não respondeu."),
        (GESTAO, "Pasta de documentos: quadro do que falta, conferência e “entregue em papel” em lote."),
        (GESTAO, "Resumo semanal por e-mail, exportação em PDF e planilha, e declaração de estágio para imprimir."),
        (GESTAO, "Avisos para a turma: recados que chegam no sino, no celular e por e-mail."),
        (("orientador",), "Encerramento do ano letivo (com desfazer por 30 dias) e anonimização de dados antigos (LGPD)."),
    )),
    Versao("2026.11.12", "App no celular e relatórios", (
        (_p("todos"), "Instale o sistema como app no celular: menu da sua foto → Instalar no celular."),
        (_p("todos"), "Avisos também por e-mail, para quem tem e-mail cadastrado."),
        (_p("estagiario", "supervisor", "orientador"), "Check-in com localização (quando a escola liga): a distância "
                                                       "até a concedente fica registrada."),
        (GESTAO, "Planilha modelo para importar estagiários, concedentes e supervisores de uma vez."),
        (GESTAO, "Relatório geral da turma, pronto para salvar em PDF."),
    )),
)


def ultima_versao():
    return VERSOES[0].id


def papel_de(usuario):
    if usuario.is_superuser:
        return None  # vê tudo
    return usuario.papel.lower()


def para(usuario, desde=""):
    """Versões (mais nova primeiro) com os itens que valem para a pessoa, mais novas que `desde`."""
    papel = papel_de(usuario)
    resultado = []
    for v in VERSOES:
        if desde and v.id <= desde:
            continue
        itens = [(publico, texto) for publico, texto in v.itens if papel is None or papel in publico]
        if itens:
            resultado.append({"id": v.id, "titulo": v.titulo, "itens": [
                {"texto": t, "publico": [ROTULOS[p] for p in pub] if papel is None and pub != TODOS else []}
                for pub, t in itens]})
    return resultado


def pendentes(usuario):
    """O que mostrar no pop-up: vazio se a pessoa desligou o aviso ou já viu tudo."""
    if not usuario.novidades_popup or (usuario.novidades_vistas or "") >= ultima_versao():
        return []
    return para(usuario, usuario.novidades_vistas or "")
