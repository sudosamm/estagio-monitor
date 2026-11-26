"""E-mails automáticos de conta (confirmação, senha, segurança), com texto editável pelo administrador.

Cada tipo tem um texto padrão aqui. Se o administrador editar em Configurações → E-mails, vale o texto salvo
(ModeloEmail). As variáveis entram entre chaves: {nome}, {link}… Uma variável desconhecida fica como está.
Os e-mails de segurança não dependem da opção “avisos por e-mail”: só de haver servidor de e-mail configurado.
"""
import re
from dataclasses import dataclass

from django.conf import settings
from django.core import signing
from django.urls import reverse
from django.utils import timezone

VALIDADE_CONFIRMACAO = 3 * 24 * 3600  # segundos
SAL_CONFIRMACAO = "core.confirmar_email"


@dataclass(frozen=True)
class Tipo:
    nome: str
    quando: str  # quando é enviado (aparece na tela do administrador)
    variaveis: tuple
    assunto: str
    corpo: str


COMUNS = ("sistema", "escola", "site")

TIPOS = {
    "CONFIRMAR_EMAIL": Tipo(
        "Confirmação de e-mail", "Quando a pessoa cadastra ou troca o e-mail em Meus dados.",
        ("nome", "usuario", "link", "validade"),
        "[{sistema}] Confirme seu e-mail",
        "Olá, {nome}.\n\nVocê cadastrou este e-mail no {sistema} (usuário {usuario}). Para confirmar, abra o link "
        "abaixo:\n\n{link}\n\nO link vale por {validade}. Com o e-mail confirmado, você consegue criar uma senha nova "
        "sozinho se esquecer a sua.\n\nSe não foi você, ignore esta mensagem.\n\n— {escola}",
    ),
    "CONFIRMAR_CADASTRO": Tipo(
        "Confirmação de cadastro (enviada pela escola)", "Quando a escola envia, em Contas, o pedido de confirmação "
        "para quem já tem e-mail cadastrado. Também para a conta criada na candidatura da concedente e para quem o "
        "responsável cadastra na equipe.",
        ("nome", "usuario", "papel", "link", "validade", "proximo_passo"),
        "[{sistema}] Confirme seu cadastro",
        "Olá, {nome}.\n\nVocê tem uma conta no {sistema} da {escola} como {papel} (usuário {usuario}). Para "
        "confirmar que este e-mail é seu, abra o link:\n\n{link}\n\n{proximo_passo}\n\nO link vale por {validade}. "
        "Se você não conhece esta escola, ignore esta mensagem.\n\n— {escola}",
    ),
    "EMAIL_CONFIRMADO": Tipo(
        "E-mail cadastrado", "Logo depois que a pessoa confirma o e-mail pelo link.",
        ("nome", "usuario"),
        "[{sistema}] E-mail cadastrado",
        "Olá, {nome}.\n\nSeu e-mail foi confirmado no {sistema} (usuário {usuario}). Se um dia esquecer a senha, "
        "use “Esqueci minha senha” na tela de entrada: {site}\n\n— {escola}",
    ),
    "REDEFINIR_SENHA": Tipo(
        "Redefinição de senha", "Quando alguém pede “Esqueci minha senha” para uma conta com e-mail confirmado.",
        ("nome", "usuario", "link", "validade", "quando", "ip"),
        "[{sistema}] Redefinição de senha",
        "Olá, {nome}.\n\nRecebemos um pedido para criar uma senha nova para o usuário {usuario}. Abra o link:\n\n"
        "{link}\n\nO link vale por {validade} e só funciona uma vez. Se não foi você, ignore: sua senha continua a "
        "mesma.\n\nPedido feito em {quando} (IP {ip}).\n\n— {escola}",
    ),
    "SENHA_ALTERADA": Tipo(
        "Senha alterada", "Sempre que a senha muda (em Meus dados ou pelo link de redefinição).",
        ("nome", "usuario", "quando", "ip"),
        "[{sistema}] Sua senha foi alterada",
        "Olá, {nome}.\n\nA senha do usuário {usuario} foi alterada em {quando} (IP {ip}).\n\nSe não foi você, "
        "avise a escola imediatamente.\n\n— {escola}",
    ),
    "TENTATIVAS": Tipo(
        "Alguém tentou acessar a conta", "Na 3ª senha errada seguida para o mesmo usuário (no máximo uma vez a cada "
        "15 minutos).",
        ("nome", "usuario", "tentativas", "quando", "ip"),
        "[{sistema}] Tentativas de entrar na sua conta",
        "Olá, {nome}.\n\nHouve {tentativas} tentativas de entrar com o usuário {usuario} usando uma senha errada "
        "(a última em {quando}, IP {ip}).\n\nSe foi você, está tudo bem. Se não foi, troque sua senha em Meus dados: "
        "{site}\n\n— {escola}",
    ),
    "BLOQUEIO": Tipo(
        "Acesso bloqueado", "Quando o login daquele usuário fica bloqueado por excesso de senhas erradas.",
        ("nome", "usuario", "minutos", "quando", "ip", "link"),
        "[{sistema}] Seu acesso foi bloqueado por {minutos} minutos",
        "Olá, {nome}.\n\nDepois de várias senhas erradas, o acesso do usuário {usuario} ficou bloqueado por "
        "{minutos} minutos (último erro em {quando}, IP {ip}).\n\nSe foi você e esqueceu a senha, crie outra em: "
        "{link}\nSe não foi você, avise a escola.\n\n— {escola}",
    ),
    "PEDIDO_AJUDA": Tipo(
        "Pedido de ajuda (para o administrador)", "Quando alguém bloqueado ou sem acesso pede ajuda na tela de "
        "entrada. Vai para os administradores.",
        ("usuario", "nome", "contato", "mensagem", "quando", "ip", "link"),
        "[{sistema}] Pedido de ajuda com o acesso: {usuario}",
        "Pedido enviado pela tela de entrada em {quando} (IP {ip}).\n\nUsuário informado: {usuario}\nNome: {nome}\n"
        "Contato: {contato}\n\nMensagem:\n{mensagem}\n\nContas no sistema: {link}",
    ),
    "CONFIRMAR_PRESENCAS": Tipo(
        "Confirmar presenças (para o supervisor)", "Uma vez por semana (dia escolhido em Configurações), para cada "
        "supervisor com presenças esperando confirmação. Também quando a escola pede pelo painel.",
        ("nome", "quantidade", "lista", "link", "validade"),
        "[{sistema}] {quantidade} presença(s) esperando sua confirmação",
        "Olá, {nome}.\n\nEstas presenças dos seus estagiários estão esperando a sua confirmação:\n\n{lista}\n\n"
        "Para confirmar todas de uma vez, sem precisar entrar no sistema, abra o link e toque em “Confirmar”:\n\n"
        "{link}\n\nO link vale por {validade} e só funciona uma vez. Se algum dia estiver errado, não use o link: "
        "entre no sistema e conteste só aquele dia.\n\n— {escola}",
    ),
    "RESUMO_MENSAL_SUPERVISOR": Tipo(
        "Resumo do mês (para o supervisor)", "No dia 1º de cada mês, para cada supervisor com estagiários ativos.",
        ("nome", "mes", "lista", "link"),
        "[{sistema}] Resumo de {mes} dos seus estagiários",
        "Olá, {nome}.\n\nComo foi {mes} dos estagiários que você supervisiona:\n\n{lista}\n\n"
        "Detalhes, presenças para confirmar e o feedback do mês: {link}\n\nObrigado pela parceria!\n\n— {escola}",
    ),
    "ERRO_SISTEMA": Tipo(
        "Erro no sistema (para o administrador)", "Quando uma página ou tarefa dá erro. O mesmo erro avisa de novo "
        "no máximo a cada 6 horas.",
        ("erro", "mensagem", "pagina", "origem", "ocorrencias", "quando", "link"),
        "[{sistema}] Erro: {erro} em {pagina}",
        "O sistema registrou um erro em {quando}.\n\nErro: {erro}\nMensagem: {mensagem}\nPágina: {pagina}\n"
        "Origem: {origem}\nVezes até agora: {ocorrencias}\n\nDetalhes e histórico: {link}",
    ),
}

NOMES_VARIAVEIS = {
    "nome": "primeiro nome da pessoa", "usuario": "usuário de acesso", "link": "endereço do botão/link",
    "validade": "por quanto tempo o link vale", "quando": "data e hora", "ip": "endereço de rede de quem fez",
    "tentativas": "número de senhas erradas", "minutos": "duração do bloqueio", "contato": "contato informado",
    "mensagem": "mensagem escrita pela pessoa", "sistema": "nome do sistema", "escola": "nome da escola",
    "site": "endereço do sistema", "quantidade": "número de presenças", "lista": "lista (dias ou estagiários)",
    "mes": "mês do resumo", "erro": "tipo do erro", "pagina": "página onde aconteceu",
    "origem": "arquivo e linha do código", "ocorrencias": "quantas vezes aconteceu",
    "papel": "perfil da conta (supervisor(a), orientador(a)…)", "proximo_passo": "o que fazer depois de confirmar",
}


def modelo(tipo):
    """(assunto, corpo, ativo) em vigor para o tipo."""
    from .models import ModeloEmail

    salvo = ModeloEmail.vigente(tipo)  # o da escola, senão o padrão da plataforma
    if salvo:
        return salvo.assunto, salvo.corpo, salvo.ativo
    t = TIPOS[tipo]
    return t.assunto, t.corpo, True


def _preencher(texto, valores):
    return re.sub(r"\{(\w+)\}", lambda m: str(valores[m.group(1)]) if m.group(1) in valores else m.group(0), texto)


def valores_comuns():
    from .models import Configuracao

    return {"sistema": settings.NOME_SISTEMA, "escola": Configuracao.atual().nome_escola or settings.NOME_SISTEMA,
            "site": settings.SITE_URL or ""}


def montar(tipo, assunto=None, corpo=None, **valores):
    """(assunto, corpo) prontos. `assunto`/`corpo` permitem pré-visualizar um texto ainda não salvo."""
    a, c, _ = modelo(tipo)
    v = {**valores_comuns(), **valores}
    assunto = " ".join(_preencher(assunto if assunto is not None else a, v).split())  # sem quebra de linha no assunto
    return assunto[:200], _preencher(corpo if corpo is not None else c, v)


def enviar(tipo, destinatarios, **valores):
    """Envia (em segundo plano) se houver servidor de e-mail e o tipo estiver ativo. Devolve True se mandou."""
    from .services import enviar_emails

    destinatarios = [d for d in destinatarios if d]
    if not (settings.EMAIL_ATIVO and destinatarios and modelo(tipo)[2]):
        return False
    assunto, corpo = montar(tipo, **valores)
    enviar_emails([(assunto, corpo, settings.DEFAULT_FROM_EMAIL, [d]) for d in destinatarios])
    return True


def quando(momento=None):
    return timezone.localtime(momento or timezone.now()).strftime("%d/%m/%Y às %H:%M")


def endereco(request, caminho):
    return request.build_absolute_uri(caminho) if request is not None else f"{settings.SITE_URL}{caminho}"


# ---------------------------------------------------------------- confirmação do e-mail


def token_confirmacao(user):
    return signing.dumps({"u": user.pk, "e": user.email.strip().lower()}, salt=SAL_CONFIRMACAO)


def usuario_do_token(token):
    """A conta do link, se o link for válido, não tiver vencido e o e-mail ainda for o mesmo."""
    from .models import Usuario

    try:
        dados = signing.loads(token, salt=SAL_CONFIRMACAO, max_age=VALIDADE_CONFIRMACAO)
    except signing.BadSignature:
        return None
    user = Usuario.objects.filter(pk=dados.get("u"), is_active=True).first()
    if user and user.email and user.email.strip().lower() == dados.get("e"):
        return user
    return None


PROXIMO_SENHA = ("Como você ainda não entrou no sistema, o link também leva direto para você criar a sua senha. "
                 "Depois, entre com o seu usuário ou com este e-mail.")
PROXIMO_ENTRAR = ("Com o e-mail confirmado, se um dia esquecer a senha, você mesmo cria outra pelo “Esqueci minha "
                  "senha”. Também dá para entrar com este e-mail no lugar do usuário.")


def enviar_confirmacao(request, user, pela_escola=False):
    """Link de confirmação do e-mail. `pela_escola`: texto de “confirme seu cadastro” (enviado pela gestão)."""
    link = endereco(request, reverse("confirmar_email", args=[token_confirmacao(user)]))
    if pela_escola:
        enviado = enviar("CONFIRMAR_CADASTRO", [user.email], nome=user.primeiro_nome, usuario=user.username,
                         papel=user.get_papel_display().lower(), link=link, validade="3 dias",
                         proximo_passo=PROXIMO_SENHA if user.deve_trocar_senha else PROXIMO_ENTRAR)
    else:
        enviado = enviar("CONFIRMAR_EMAIL", [user.email], nome=user.primeiro_nome, usuario=user.username, link=link,
                         validade="3 dias")
    if enviado and user.pk:
        from .models import Usuario

        user.confirmacao_enviada_em = timezone.now()
        Usuario.objects.filter(pk=user.pk).update(confirmacao_enviada_em=user.confirmacao_enviada_em)
    return enviado


def avisar_senha_alterada(request, user):
    from .seguranca import ip_de

    if user.email_confirmado_em:
        enviar("SENHA_ALTERADA", [user.email], nome=user.primeiro_nome, usuario=user.username, quando=quando(),
               ip=ip_de(request) or "desconhecido")
