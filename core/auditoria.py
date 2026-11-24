"""Registro de ações: entradas na conta, senhas, verificação em duas etapas, mudanças feitas pela gestão e pelas
concedentes, e downloads de dados pessoais (relatórios, exportações, atestados, currículos).

Nada do que foi digitado nos formulários é guardado: só quem, o quê (pelo nome da tela), sobre quem/o quê, quando,
o IP e o tipo de aparelho. As mudanças em presenças já têm histórico próprio (HistoricoRegistro).
"""
import logging
import re
from datetime import timedelta

from django.utils import timezone

GUARDAR_DIAS = 365  # o Marco Civil pede no mínimo 6 meses para os registros de acesso

# tela (nome da URL) -> o que a pessoa fez. Telas fora da lista aparecem com o nome técnico.
DESCRICOES = {
    "criar_estagiarios": "Cadastrou estagiários",
    "criar_supervisores": "Cadastrou supervisores",
    "criar_orientador": "Criou conta de orientador",
    "criar_coordenador": "Criou conta de coordenador",
    "importar_csv": "Importou planilha de contas",
    "editar_usuario": "Editou a conta",
    "redefinir_senha": "Gerou código de primeiro acesso",
    "codigos_lote": "Gerou códigos de primeiro acesso em lote",
    "ativacao_usuario": "Ativou/desativou a conta",
    "editar_estagio": "Editou o estágio",
    "trocar_supervisor": "Trocou o supervisor",
    "nova_escala": "Mudou os dias e horários",
    "excluir_escala": "Excluiu uma escala",
    "escala_lote": "Mudou dias e horários em lote",
    "estagio_dia": "Lançou/ajustou um dia",
    "validar_registro": "Validou um registro",
    "confirmar_lote": "Confirmou presenças em lote",
    "cursos": "Salvou curso", "curso_editar": "Editou curso",
    "turmas": "Salvou turma", "turma_editar": "Editou turma",
    "local_novo": "Cadastrou concedente", "local_editar": "Editou a concedente",
    "ativacao_local": "Ativou/desativou a concedente",
    "configuracoes": "Mudou as configurações do sistema",
    "modelo_email": "Editou um modelo de e-mail",
    "encerramento": "Encerramento do ano / anonimização",
    "dias_sem_estagio": "Feriados e eventos", "importar_feriados": "Importou feriados", "recessos": "Recessos",
    "documentos_gerais": "Arquivos gerais", "excluir_documento": "Excluiu um arquivo",
    "comunicados": "Enviou aviso para a turma",
    "captacao_detalhe": "Analisou candidatura de concedente",
    "decidir_atestado": "Decidiu um atestado",
    "conferir_documento": "Conferiu documento da pasta",
    "folhas_lote": "Emitiu/enviou folhas de frequência",
    "excluir_folha": "Excluiu folha enviada",
    "novo_agendamento": "Agendou visita/conversa", "agendamento_detalhe": "Atualizou um agendamento",
    "cancelar_agendamento": "Cancelou um agendamento",
    "acompanhamento_novo": "Registrou acompanhamento de visita", "acompanhamento_editar": "Editou acompanhamento",
    "equipe": "Equipe da concedente", "equipe_concedente": "Equipe da concedente",
    "substituto": "Indicou substituto",
    "pedir_confirmacao": "Pediu confirmação de presenças ao supervisor",
    "marcar_erro": "Marcou erro do sistema", "marcar_opiniao": "Marcou opinião",
    "perguntas_avaliacao": "Editou perguntas de avaliação", "pergunta_avaliacao_editar": "Editou pergunta de avaliação",
    "tipos_documento": "Tipos de documento", "tipo_documento_editar": "Editou tipo de documento",
    "entregue_em_papel": "Marcou documento entregue em papel", "entregue_em_papel_lote": "Documentos em papel (lote)",
    "avisar_avaliacoes": "Lembrou avaliações",
}
# downloads de dados pessoais (GET): ficam registrados para qualquer pessoa, menos o próprio dono
DOWNLOADS = {
    "exportar_estagios": "Exportou a planilha de estagiários",
    "relatorio_turma": "Abriu o relatório da turma",
    "declaracao_estagio": "Emitiu declaração de estágio",
    "atestado_arquivo": "Abriu o arquivo de um atestado",
    "curriculo_usuario": "Abriu um currículo",
    "baixar_folha": "Baixou folha de frequência enviada",
}
# telas com POST que não interessam (preferências, marcar como lido…)
IGNORAR = {
    "trocar_tema", "notificacoes_lidas", "notificacao_abrir", "novidades_visto", "push_inscrever", "push_cancelar",
    "push_teste", "enviar_opiniao", "marcar_impressao", "login", "logout", "verificar_dois_fatores",
    "dois_fatores", "aceitar_termos", "perfil", "trocar_senha", "reenviar_confirmacao", "sugestoes",
    "primeiro_acesso", "primeiro_acesso_senha", "esqueci_senha", "redefinir_senha_email", "pedir_ajuda",
    "confirmar_por_link", "candidatura_publica", "checkin_qr", "checkin_qr_confirmar", "qr_novo", "buscar",
    "marcar_presenca", "registrar_saida", "informar_ausencia", "enviar_mensagem",
}
# tela -> modelo do pk da URL, para dizer “sobre quem”
ALVOS = {
    "editar_usuario": "Usuario", "redefinir_senha": "Usuario", "ativacao_usuario": "Usuario",
    "editar_estagio": "Estagio", "trocar_supervisor": "Estagio", "nova_escala": "Estagio", "estagio_dia": "Estagio",
    "declaracao_estagio": "Estagio", "curriculo_usuario": "Usuario", "local_editar": "LocalEstagio",
    "ativacao_local": "LocalEstagio", "equipe_concedente": "LocalEstagio", "turma_editar": "Turma",
    "curso_editar": "Curso", "relatorio_turma": "Turma", "atestado_arquivo": "Justificativa",
    "decidir_atestado": "Justificativa", "validar_registro": "Registro", "captacao_detalhe": "Candidatura",
    "agendamento_detalhe": "Agendamento", "cancelar_agendamento": "Agendamento",
}

log = logging.getLogger("core.auditoria")


def aparelho(request):
    """“Chrome no Android”, “Safari no iPhone”… (só para a pessoa reconhecer os próprios acessos)."""
    ua = (request.META.get("HTTP_USER_AGENT", "") if request is not None else "")[:400]
    if not ua:
        return ""
    so = next((n for p, n in ((r"iPhone|iPad", "iPhone/iPad"), (r"Android", "Android"), (r"Windows", "Windows"),
                              (r"Mac OS X|Macintosh", "Mac"), (r"CrOS", "Chromebook"), (r"Linux", "Linux"))
               if re.search(p, ua)), "")
    nav = next((n for p, n in ((r"Edg/", "Edge"), (r"OPR/|Opera", "Opera"), (r"SamsungBrowser", "Samsung Internet"),
                               (r"Firefox/|FxiOS", "Firefox"), (r"Chrome/|CriOS", "Chrome"), (r"Safari/", "Safari"))
                if re.search(p, ua)), "Navegador")
    return f"{nav} no {so}" if so else nav


def registrar(request, tipo, descricao, alvo="", usuario=None):
    """Guarda uma ação. Nunca derruba a página por causa do registro."""
    from .models import RegistroAcao
    from .seguranca import ip_de

    try:
        if usuario is None and request is not None and getattr(request, "user", None) is not None \
                and request.user.is_authenticated:
            usuario = request.user
        RegistroAcao.objects.create(
            usuario=usuario, quem=(f"{usuario.nome_completo} ({usuario.username})"[:160] if usuario else ""),
            tipo=tipo[:30], descricao=descricao[:255], alvo=str(alvo)[:255],
            caminho=(request.path[:255] if request is not None else ""), ip=ip_de(request),
            aparelho=aparelho(request)[:80],
        )
    except Exception:  # noqa: BLE001
        log.exception("Falha ao registrar a ação %s", tipo)


def _alvo(nome, kwargs):
    modelo = ALVOS.get(nome)
    pk = kwargs.get("pk")
    if not modelo or pk is None:
        return ""
    from django.apps import apps

    obj = apps.get_model("core", modelo).objects.filter(pk=pk).first()
    return str(obj) if obj else f"#{pk}"


def deve_registrar_post(user):
    """Ações de quem gerencia (gestão e responsáveis/substitutos das concedentes). Os estagiários e as presenças já
    têm histórico próprio."""
    return user.is_authenticated and not user.is_estagiario


class AuditoriaMiddleware:
    """Registra os POSTs que deram certo (redirecionamento ou resposta JSON) e os downloads de dados pessoais."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            self._anotar(request, response)
        except Exception:  # noqa: BLE001
            log.exception("Falha no registro de ações")
        return response

    def _anotar(self, request, response):
        match = getattr(request, "resolver_match", None)
        user = getattr(request, "user", None)
        if not match or not user or not user.is_authenticated or response.status_code >= 400:
            return
        nome = match.url_name or ""
        if request.method == "GET" and nome in DOWNLOADS and response.status_code == 200:
            if nome == "curriculo_usuario" and str(match.kwargs.get("pk")) == str(user.pk):
                return
            if nome == "atestado_arquivo" and _do_proprio(user, match.kwargs.get("pk")):
                return
            registrar(request, "DADOS", DOWNLOADS[nome], _alvo(nome, match.kwargs))
            return
        if request.method != "POST" or nome in IGNORAR or not deve_registrar_post(user):
            return
        json = response.get("Content-Type", "").startswith("application/json")
        arquivo = "attachment" in response.get("Content-Disposition", "")
        concluida = getattr(request, "_acao_concluida", False)  # tela de resultado (ex.: folha com os códigos)
        if not (300 <= response.status_code < 400 or json or arquivo or concluida):
            return  # formulário que voltou com erro: nada mudou
        descricao = DESCRICOES.get(nome, nome.replace("_", " ").capitalize())
        acao = (request.POST.get("acao") or "")[:30]
        if acao and acao.replace("_", "").isalnum():
            descricao += f" ({acao.replace('_', ' ')})"
        registrar(request, "GESTAO", descricao, _alvo(nome, match.kwargs))


def _do_proprio(user, pk):
    from .models import Justificativa

    return Justificativa.objects.filter(pk=pk, estagio__estagiario=user).exists()


# ---------------------------------------------------------------- entradas e saídas (sinais do Django)


def ao_entrar(sender, request, user, **kw):
    registrar(request, "LOGIN", "Entrou no sistema", usuario=user)


def ao_falhar(sender, credentials, request=None, **kw):
    """Só para usuários que existem (quem digita a senha no campo do usuário não deixa a senha guardada aqui)."""
    from .models import Usuario

    user = Usuario.objects.filter(username__iexact=(credentials.get("username") or "").strip()).first()
    if user:
        registrar(request, "LOGIN_FALHOU", "Senha errada ao entrar", usuario=user)


def ao_sair(sender, request, user, **kw):
    if user is not None:
        registrar(request, "LOGOUT", "Saiu do sistema", usuario=user)


def limpar_antigos():
    from .models import RegistroAcao

    RegistroAcao.objects.filter(quando__lt=timezone.now() - timedelta(days=GUARDAR_DIAS)).delete()
