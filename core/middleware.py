from django.shortcuts import redirect
from django.urls import reverse


class CaractereNuloMiddleware:
    """Recusa (400) endereço, parâmetros ou campos de formulário com o caractere NUL (\\x00).

    Nenhum navegador o envia ao digitar. O SQLite aceitava o texto; o PostgreSQL recusa qualquer texto com NUL e a
    consulta viraria um erro 500 (e um aviso de erro para os administradores), por exemplo numa busca ou no login."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.http import HttpResponseBadRequest

        if "\x00" in request.path or any("\x00" in v for v in request.GET.values()):
            return HttpResponseBadRequest("Caractere inválido no endereço.")
        if request.method == "POST" and any("\x00" in v for vs in request.POST.lists() for v in [vs[0], *vs[1]]):
            return HttpResponseBadRequest("Caractere inválido no formulário.")
        return self.get_response(request)


class CacheDaRequisicaoMiddleware:
    """Abre um cache que vale só durante esta requisição (ex.: a configuração geral, lida várias vezes por página)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from .models import CACHE_REQUISICAO

        token = CACHE_REQUISICAO.set({})
        try:
            return self.get_response(request)
        finally:
            CACHE_REQUISICAO.reset(token)


class ModoAdministradorMiddleware:
    """Administrador com o “Modo administrador” desligado (Meus dados) usa o sistema como um orientador comum: só os
    próprios estagiários e sem as telas de administração. Vale só para esta requisição (o banco continua dizendo que ele
    é administrador; Usuario.save protege isso)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and user.is_superuser and not user.modo_administrador:
            user.is_superuser = False
            user._admin_real = True
        return self.get_response(request)


class TrocaSenhaObrigatoriaMiddleware:
    """Antes de usar o sistema: criar a senha própria, configurar a verificação em duas etapas (quando a escola
    exige) e aceitar a versão atual dos Termos de Uso e do Aviso de Privacidade."""

    LIBERADOS = ("trocar_senha", "logout", "primeiro_acesso", "primeiro_acesso_senha", "esqueci_senha", "pedir_ajuda",
                 "privacidade", "termos", "aceitar_termos", "dois_fatores", "verificar_dois_fatores")
    PREFIXOS = ("/static/", "/sw.js", "/manifest.webmanifest", "/offline/", "/sugestoes/", "/saude/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            caminho = request.path
            if not caminho.startswith(self.PREFIXOS) and caminho not in [reverse(n) for n in self.LIBERADOS]:
                destino = self._destino(user, caminho)
                if destino:
                    return redirect(destino)
        return self.get_response(request)

    def _destino(self, user, caminho):
        from urllib.parse import quote

        from . import dois_fatores, termos

        if user.deve_trocar_senha:
            return None if caminho.startswith("/admin/") else reverse("trocar_senha")
        proximo = f"?next={quote(caminho)}" if caminho not in ("/", "") else ""
        if dois_fatores.exigido(user) and not user.dois_fatores_ativo:
            return reverse("dois_fatores") + proximo
        if termos.precisa_aceitar(user):
            return reverse("aceitar_termos") + proximo
        return None


class AreaDoResponsavelMiddleware:
    """Responsável legal só usa a própria área (só leitura) e as telas da conta. Qualquer outra tela do sistema
    (lançar dias, mensagens, atestados, folhas…) volta para a área dele, mesmo que alguém mande o link."""

    LIBERADAS = {
        "inicio", "responsavel_inicio", "responsavel_estagio", "comunicado", "meus_comunicados", "perfil", "trocar_senha",
        "logout", "login", "primeiro_acesso", "primeiro_acesso_senha", "privacidade", "termos", "aceitar_termos", "acessos",
        "notificacoes", "notificacao_abrir", "notificacoes_lidas", "novidades", "novidades_visto", "trocar_tema",
        "push_chave", "push_inscrever", "push_cancelar", "push_teste", "dois_fatores", "verificar_dois_fatores",
        "baixar_meus_dados", "foto_usuario", "sugestoes", "enviar_opiniao", "confirmar_email", "reenviar_confirmacao",
        "esqueci_senha", "redefinir_senha_email", "pedir_ajuda", "manifesto", "offline", "saude",
    }
    PREFIXOS = ("/static/", "/sw.js", "/manifest.webmanifest", "/offline/", "/saude/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and user.is_responsavel and not request.path.startswith(self.PREFIXOS):
            from django.core.exceptions import PermissionDenied
            from django.urls import Resolver404, resolve

            try:
                nome = resolve(request.path_info).url_name
            except Resolver404:
                nome = None
            if nome is not None and nome not in self.LIBERADAS:
                if request.method != "GET":
                    raise PermissionDenied
                return redirect("responsavel_inicio")
        return self.get_response(request)


class ResumoSemanalMiddleware:
    """Tarefas com hora marcada, disparadas pelo próprio movimento do sistema (sem precisar de cron): resumo semanal
    (segunda, 6h), lembretes de feedback e avaliações, lembrete de fim de expediente dos estagiários, e-mail
    “Confirmar todas” dos supervisores, resumo do mês dos supervisores e limpeza dos registros antigos.

    Consulta o banco no máximo a cada 10 minutos por processo do servidor. Uma tarefa que falha não impede as outras
    (e o erro chega ao administrador pelos avisos de erro).
    """

    INTERVALO = 600

    def __init__(self, get_response):
        self.get_response = get_response
        self.proxima = 0

    def __call__(self, request):
        response = self.get_response(request)
        import time

        from django.conf import settings

        agora = time.monotonic()
        if getattr(settings, "RESUMO_AUTOMATICO", True) and agora >= self.proxima:
            self.proxima = agora + self.INTERVALO
            self._tarefas()
        return response

    @staticmethod
    def _tarefas():
        import logging

        from . import auditoria, confirmacao, lembretes, sessoes
        from .acompanhamento import disparar_resumo_se_preciso
        from .avaliacoes import disparar_lembrete as lembrete_avaliacoes
        from .feedback import disparar_lembrete as lembrete_feedback

        for tarefa in (disparar_resumo_se_preciso, lembrete_feedback, lembrete_avaliacoes,
                       lembretes.disparar_lembretes_expediente, confirmacao.disparar_confirmacoes,
                       confirmacao.disparar_resumo_mensal, auditoria.limpar_antigos, sessoes.limpar_antigas):
            try:
                tarefa()
            except Exception:  # noqa: BLE001 — nunca atrapalhar a página
                logging.getLogger("core.tarefas").exception("Falha na tarefa %s", tarefa.__name__)
