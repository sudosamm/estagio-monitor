"""Instalação como app no celular (PWA): manifesto, service worker e página offline.

O service worker não guarda páginas com dados pessoais: só os arquivos estáticos e a página “sem conexão”.
"""
import hashlib

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.cache import cache_control


@cache_control(max_age=3600)
def manifesto(request):
    dados = {
        "name": settings.NOME_SISTEMA,
        "short_name": settings.NOME_SISTEMA if len(settings.NOME_SISTEMA) <= 15 else "Estágio",
        "description": "Acompanhamento de estágio supervisionado: presença, folha de frequência e avisos.",
        "lang": "pt-BR",
        "start_url": "/?origem=app",
        "scope": "/",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#005a2b",
        "icons": [
            {"src": static("img/app-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": static("img/app-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": static("img/app-maskable-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
        "shortcuts": [
            {"name": "Meu estágio", "url": "/?origem=app"},
            {"name": "Avisos", "url": "/notificacoes/"},
        ],
    }
    resposta = JsonResponse(dados, json_dumps_params={"ensure_ascii": False})
    resposta["Content-Type"] = "application/manifest+json; charset=utf-8"
    return resposta


@cache_control(max_age=0, no_cache=True)
def service_worker(request):
    arquivos = [static(p) for p in ("css/app.css", "js/app.js", "img/icone.svg", "img/app-192.png")]
    resposta = render(request, "pwa/sw.js", {"arquivos": arquivos, "rede_primeiro": settings.DEBUG, "versao": hashlib.sha1("|".join(arquivos).encode()).hexdigest()[:10]},
                      content_type="application/javascript; charset=utf-8")
    resposta["Service-Worker-Allowed"] = "/"
    return resposta


def offline(request):
    return render(request, "pwa/offline.html")
