from django.shortcuts import redirect
from django.urls import reverse


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
