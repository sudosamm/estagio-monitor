from django.shortcuts import redirect
from django.urls import reverse


class TrocaSenhaObrigatoriaMiddleware:
    """Obriga quem entrou com a senha padrão a criar uma senha própria."""

    LIBERADOS = ("trocar_senha", "logout")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated and user.deve_trocar_senha:
            caminho = request.path
            livres = [reverse(n) for n in self.LIBERADOS]
            if caminho not in livres and not caminho.startswith(("/static/", "/admin/", "/sw.js", "/manifest.webmanifest", "/offline/", "/sugestoes/")):
                return redirect("trocar_senha")
        return self.get_response(request)


class ResumoSemanalMiddleware:
    """Dispara o resumo semanal por e-mail no primeiro acesso depois de segunda, 6h (sem precisar de cron).

    Consulta o banco no máximo a cada 10 minutos por processo do servidor.
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
            try:
                from .acompanhamento import disparar_resumo_se_preciso
                from .feedback import disparar_lembrete

                disparar_resumo_se_preciso()
                disparar_lembrete()
            except Exception:  # noqa: BLE001 — nunca atrapalhar a página
                import logging

                logging.getLogger("core.resumo").exception("Falha ao verificar o resumo semanal")
        return response
