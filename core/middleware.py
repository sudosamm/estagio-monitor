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
            if caminho not in livres and not caminho.startswith(("/static/", "/admin/")):
                return redirect("trocar_senha")
        return self.get_response(request)
