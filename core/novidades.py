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
    id: str  # AAAA.MM.DD (ou AAAA.MM.DD.N, se sair mais de uma no mesmo dia) — dá a ordem
    titulo: str
    itens: tuple  # ((publico, texto), …)


def _p(*publico):
    return TODOS if "todos" in publico else publico


VERSOES = (
    Versao("2026.11.24", "Painel com calendário e agendamento mais fácil", (
        (GESTAO, "Painel: calendário do mês com visitas, feriados, fim de termos, previsões de conclusão, aniversários e "
                 "quantos ficaram sem registro em cada dia. Clique num dia para ver tudo e agendar nele."),
        (("orientador",), "Agendar visita: busca de estagiários e, ao escolher, a ficha completa (endereço e mapa, "
                          "supervisor e telefones, horário, próximos dias, horas e pendências). Local, assunto e dias "
                          "em comum são preenchidos sozinhos, com aviso de conflito de horário."),
        (_p("todos"), "Sistema mais rápido: as listas carregam tudo de uma vez e as páginas começam a abrir quando você "
                      "aponta para o link."),
        (("estagiario", "supervisor"), "O sistema está em testes: use o botão “Sua opinião”, no canto da tela, para "
                                       "contar o que achou. Leva 10 segundos."),
    )),
    Versao("2026.11.18", "Senha por e-mail e calendário com nível", (
        (_p("estagiario"), "Calendário: cada horário marcado enche o dia de água (25%, 50%, 75%, 100%). Confirmado pelo "
                           "supervisor sem todos os horários, o dia vira grama."),
        (_p("todos"), "Cadastre e confirme seu e-mail em Meus dados: se esquecer a senha, use “Esqueci minha senha” na "
                      "tela de entrada e crie outra sozinho."),
        (_p("todos"), "Segurança: avisamos por e-mail quando alguém erra sua senha várias vezes, quando o acesso é "
                      "bloqueado e quando a senha muda. Bloqueado? Use “Falar com o administrador” na tela de entrada."),
        (("orientador",), "Administrador: os textos de cada e-mail automático ficam em Configurações → Textos dos e-mails."),
    )),
    Versao("2026.11.17.2", "Primeiro acesso mais protegido", (
        (GESTAO, "Código de acesso de supervisor: só gera quem tem estagiário com ele ou cadastrou a conta (o "
                 "administrador gera para qualquer um). Contas que ainda não entraram não abrem por senha nenhuma."),
    )),
    Versao("2026.11.17.1", "Primeiro acesso sem senha padrão", (
        (_p("todos"), "A senha inicial igual para todos acabou. Quem ainda não entrou cria a senha em “Primeiro acesso”, "
                      "na tela de login."),
        (_p("estagiario"), "No primeiro acesso, informe seu nome completo e sua data de nascimento."),
        (_p("supervisor"), "No primeiro acesso, use o usuário e o código que o orientador enviou. O código vale uma vez."),
        (GESTAO, "Folha de primeiro acesso: em Contas, filtre “Ainda não entraram” para gerar códigos de uso único "
                 "(supervisores e quem não tem data de nascimento). Esqueceu a senha? “Novo primeiro acesso” na conta."),
        (GESTAO, "Importação: novas colunas estagiario_nascimento, presencas_desde (dias já cumpridos entram como presença "
                 "confirmada) e curso_carga_horaria. Reenviar a planilha completa o cadastro de quem já tem estágio."),
        (_p("todos"), "Calendário: a legenda de feriado/recesso agora aparece listrada, igual ao dia no calendário."),
    )),
    Versao("2026.11.17", "Mais segurança no login", (
        (_p("todos"), "Depois de 5 senhas erradas seguidas, o login espera 15 minutos. Esqueceu a senha? Peça ao "
                      "orientador para redefinir."),
        (_p("todos"), "Senha nova: pelo menos 8 caracteres, não pode ser só números nem a senha inicial."),
        (GESTAO, "Arquivos enviados: só PDF, fotos e documentos do Office/LibreOffice; a foto de cada pessoa só aparece "
                 "para quem divide o estágio com ela e para a gestão."),
    )),
    Versao("2026.11.16.1", "Acompanhamento de visita: Desenvolvimento de Sistemas", (
        (("orientador", "coordenador"), "Desenvolvimento de Sistemas: as 162 atividades do “Atividade Sugerida” do SICE "
                                        "já estão cadastradas, com o mesmo texto."),
        (("orientador",), "Acompanhamento de visita: busca nas atividades práticas, contador de incluídas e “Só as "
                          "incluídas”; o “Marcar todos” vale só para as que aparecem na busca."),
    )),
    Versao("2026.11.16", "Novidades de novembro", (
        (_p("todos"), "Tema escuro “Noite no sertão”: no menu da sua foto, escolha Auto (segue o celular), Claro ou Escuro."),
        (_p("todos"), "Notificações no celular: ative em Meus dados e receba os avisos mesmo com o app fechado."),
        (_p("todos"), "Sugestões e erros: uma página para mandar ideias, problemas e prints direto para a equipe do sistema."),
        (_p("todos"), "O que há de novo: este aviso, que mostra só o que mudou para você. Veja o histórico em Novidades."),
        (_p("estagiario"), "Avaliações mensais do SICE: responda a autoavaliação e a avaliação do orientador de cada mês "
                           "aqui e copie as respostas prontas para o SICE."),
        (_p("estagiario"), "Mês a mês: na aba Registros, a sua carga horária no mesmo formato da “Frequência Detalhada” "
                           "do SICE."),
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
        (GESTAO, "Avaliações (SICE): veja, mês a mês, quem já respondeu a autoavaliação e a avaliação do orientador."),
        (GESTAO, "Avaliações sobre mim: as respostas da Avaliação de Orientador chegam juntas e sem nomes."),
        (("orientador",), "Acompanhamento de visita: a avaliação prática e atitudinal do SICE, preenchida na visita "
                          "(até no celular, com “Marcar todos”) e pronta para lançar no SICE."),
        (_p("estagiario"), "Acompanhamento de visita: veja, na aba Visitas, a avaliação que o orientador fez na visita."),
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
